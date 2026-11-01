import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from backend import database
from backend.utils.rag_tools import (
    TextChunk,
    extract_requirements,
    policy_chunks,
    retrieve_policy_evidence,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_case(name: str, regulation: dict, policies: list[dict]) -> str:
    case_id = str(uuid.uuid4())
    database.execute(
        "INSERT INTO cases(case_id, name, status, created_at) VALUES (?, ?, 'ready', ?)",
        (case_id, name.strip() or "Compliance review", _now()),
    )
    documents = [regulation, *policies]
    database.execute_many(
        """INSERT INTO documents(doc_id, case_id, kind, name, page_count, text)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (
                str(uuid.uuid4()),
                case_id,
                document["kind"],
                document["name"],
                document["page_count"],
                document["text"],
            )
            for document in documents
        ],
    )
    return case_id


def get_case(case_id: str) -> dict[str, Any] | None:
    case = database.fetch_one("SELECT * FROM cases WHERE case_id = ?", (case_id,))
    if not case:
        return None
    case["documents"] = database.fetch_all(
        "SELECT doc_id, kind, name, page_count FROM documents WHERE case_id = ?",
        (case_id,),
    )
    case["findings"] = database.fetch_all(
        "SELECT * FROM findings WHERE case_id = ? ORDER BY regulation_page, finding_id",
        (case_id,),
    )
    return case


def get_document(doc_id: str) -> dict[str, Any] | None:
    return database.fetch_one("SELECT * FROM documents WHERE doc_id = ?", (doc_id,))


def _local_analysis(requirements: list[TextChunk], evidence_chunks: list[TextChunk]) -> list[dict]:
    results = []
    for requirement in requirements:
        matches = retrieve_policy_evidence(requirement.text, evidence_chunks)
        best_score = matches[0][1] if matches else 0.0
        if best_score >= 0.30:
            status = "Likely covered"
            action = "Verify that the cited policy language meets the full requirement."
        elif best_score >= 0.14:
            status = "Needs review"
            action = "Review the cited policy passage and clarify or strengthen it if needed."
        else:
            status = "Potential gap"
            action = "Add or locate a policy control that addresses this requirement."
        results.append(
            {
                "requirement": requirement,
                "status": status,
                "similarity": best_score,
                "matches": matches,
                "action": action,
                "rationale": (
                    "Local lexical similarity is a retrieval signal, not a legal conclusion. "
                    "A reviewer must verify whether the policy satisfies the requirement."
                ),
            }
        )
    return results


def _gemini_analysis(
    requirements: list[TextChunk], evidence_chunks: list[TextChunk]
) -> list[dict]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured on the backend.")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    rows = []
    for requirement in requirements:
        matches = retrieve_policy_evidence(requirement.text, evidence_chunks)
        rows.append(
            {
                "requirement_id": requirement.chunk_id,
                "requirement": requirement.text,
                "regulation_page": requirement.page,
                "policy_candidates": [
                    {
                        "evidence_id": chunk.chunk_id,
                        "page": chunk.page,
                        "text": chunk.text,
                        "similarity": round(score, 3),
                    }
                    for chunk, score in matches
                    if score > 0
                ],
            }
        )

    prompt = (
        "You are a careful compliance analysis assistant. Compare each regulation requirement "
        "with only the supplied policy candidates. This is not legal advice. Do not invent "
        "requirements, evidence, citations, policy meaning, or actions. For each row, return "
        "status (exactly one of 'Likely covered', 'Needs review', 'Potential gap'), action, "
        "rationale, and evidence_ids copied only from that row's policy_candidates. If no "
        "candidate supports the requirement, use an empty evidence_ids list and 'Potential gap'. "
        "Return only a JSON array with objects containing requirement_id, status, action, "
        "rationale, evidence_ids.\n\nInput:\n"
        + json.dumps(rows, ensure_ascii=False)
    )
    response = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    if not response.text:
        raise ValueError("Gemini returned an empty analysis.")
    try:
        model_results = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise ValueError("Gemini returned invalid JSON; no findings were saved.") from exc
    if not isinstance(model_results, list):
        raise ValueError("Gemini returned an unexpected response shape.")

    requirements_by_id = {item.chunk_id: item for item in requirements}
    output = []
    for item in model_results:
        if not isinstance(item, dict) or item.get("requirement_id") not in requirements_by_id:
            continue
        requirement = requirements_by_id[item["requirement_id"]]
        candidates = retrieve_policy_evidence(requirement.text, evidence_chunks)
        valid_evidence = {chunk.chunk_id: (chunk, score) for chunk, score in candidates}
        evidence_ids = item.get("evidence_ids", [])
        if not isinstance(evidence_ids, list):
            evidence_ids = []
        matches = [valid_evidence[evidence_id] for evidence_id in evidence_ids if evidence_id in valid_evidence]
        status = item.get("status")
        if status not in {"Likely covered", "Needs review", "Potential gap"}:
            status = "Needs review"
        output.append(
            {
                "requirement": requirement,
                "status": status,
                "similarity": candidates[0][1] if candidates else 0.0,
                "matches": matches,
                "action": str(item.get("action") or "Review this requirement against the source documents."),
                "rationale": str(item.get("rationale") or "Human verification is required."),
            }
        )

    if len(output) != len(requirements):
        raise ValueError("Gemini did not return a finding for every extracted requirement.")
    return output


def run_analysis(case_id: str, mode: str) -> dict[str, Any]:
    case = database.fetch_one("SELECT * FROM cases WHERE case_id = ?", (case_id,))
    if not case:
        raise LookupError("Case not found.")
    if mode not in {"local", "gemini"}:
        raise ValueError("Analysis mode must be 'local' or 'gemini'.")
    documents = database.fetch_all(
        "SELECT * FROM documents WHERE case_id = ? ORDER BY kind DESC, name",
        (case_id,),
    )
    regulation = next((doc for doc in documents if doc["kind"] == "regulation"), None)
    policies = [doc for doc in documents if doc["kind"] == "policy"]
    if not regulation or not policies:
        raise ValueError("A regulation and at least one policy document are required.")

    requirements = extract_requirements(regulation["text"])
    if not requirements:
        raise ValueError("No analyzable text was extracted from the regulation.")
    chunks = policy_chunks(policies)
    if not chunks:
        raise ValueError("No analyzable text was extracted from the policy documents.")

    database.execute(
        "UPDATE cases SET status = 'analyzing', analysis_mode = ?, error = NULL WHERE case_id = ?",
        (mode, case_id),
    )
    try:
        results = _local_analysis(requirements, chunks) if mode == "local" else _gemini_analysis(requirements, chunks)
        database.execute("DELETE FROM findings WHERE case_id = ?", (case_id,))
        database.execute_many(
            """INSERT INTO findings(
                finding_id, case_id, requirement, regulation_page, status, similarity,
                regulation_evidence, policy_evidence, action, rationale
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    str(uuid.uuid4()),
                    case_id,
                    result["requirement"].text,
                    result["requirement"].page,
                    result["status"],
                    result["similarity"],
                    result["requirement"].text,
                    json.dumps(
                        [
                            {
                                "evidence_id": chunk.chunk_id,
                                "page": chunk.page,
                                "text": chunk.text,
                                "similarity": score,
                            }
                            for chunk, score in result["matches"]
                        ],
                        ensure_ascii=False,
                    ),
                    result["action"],
                    result["rationale"],
                )
                for result in results
            ],
        )
        database.execute(
            "UPDATE cases SET status = 'complete' WHERE case_id = ?", (case_id,)
        )
    except Exception as exc:
        database.execute(
            "UPDATE cases SET status = 'failed', error = ? WHERE case_id = ?",
            (str(exc)[:1000], case_id),
        )
        raise
    return get_case(case_id) or {}


def review_finding(case_id: str, finding_id: str, decision: str, note: str) -> dict | None:
    finding = database.fetch_one(
        "SELECT finding_id FROM findings WHERE case_id = ? AND finding_id = ?",
        (case_id, finding_id),
    )
    if not finding:
        return None
    database.execute(
        "UPDATE findings SET decision = ?, review_note = ? WHERE finding_id = ?",
        (decision, note, finding_id),
    )
    database.execute(
        """INSERT INTO audits(audit_id, case_id, finding_id, decision, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), case_id, finding_id, decision, note, _now()),
    )
    return database.fetch_one("SELECT * FROM findings WHERE finding_id = ?", (finding_id,))
