import json
import os
from io import BytesIO

import requests
import streamlit as st
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


API_URL = os.getenv("REGULASYNTH_API_URL", "http://127.0.0.1:8000").rstrip("/")
STATUS_COLORS = {
    "Potential gap": "🔴",
    "Needs review": "🟡",
    "Likely covered": "🟢",
}

st.set_page_config(page_title="RegulaSynth AI", page_icon="⚖️", layout="wide")
st.title("⚖️ RegulaSynth AI")
st.caption("Evidence-first regulatory gap analysis · Human review required")


def api_request(method: str, path: str, **kwargs):
    kwargs.setdefault("timeout", 180)
    try:
        response = requests.request(method, f"{API_URL}{path}", **kwargs)
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Cannot connect to the API at {API_URL}. Start the FastAPI server and try again. ({exc})"
        ) from exc
    if not response.ok:
        try:
            message = response.json().get("detail", response.text)
        except ValueError:
            message = response.text
        raise RuntimeError(str(message))
    return response.json()


def _pdf_text(value: object) -> str:
    safe_text = str(value).encode("latin-1", "replace").decode("latin-1")
    from xml.sax.saxutils import escape

    return escape(safe_text)


def checklist_pdf(case: dict) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=letter, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("RegulaSynth AI - Review Checklist", styles["Title"]),
        Spacer(1, 8),
        Paragraph(f"Case: {_pdf_text(case['name'])}", styles["Normal"]),
        Paragraph(f"Analysis mode: {_pdf_text(case.get('analysis_mode') or 'Unknown')}", styles["Normal"]),
        Paragraph(
            "Advisory output only. A qualified reviewer must verify every finding against the source documents.",
            styles["Italic"],
        ),
        Spacer(1, 14),
    ]
    for number, finding in enumerate(case.get("findings", []), start=1):
        story.append(
            Paragraph(
                f"{number}. {_pdf_text(finding['status'])} - Regulation p. {finding['regulation_page']}",
                styles["Heading3"],
            )
        )
        story.append(Paragraph(_pdf_text(finding["requirement"]), styles["BodyText"]))
        story.append(Paragraph(f"<b>Action:</b> {_pdf_text(finding['action'])}", styles["BodyText"]))
        story.append(Paragraph(f"<b>Review:</b> {_pdf_text(finding['decision'])}", styles["BodyText"]))
        story.append(Paragraph(f"<b>Regulation evidence:</b> {_pdf_text(finding['regulation_evidence'])}", styles["BodyText"]))
        for evidence in json.loads(finding["policy_evidence"]):
            story.append(
                Paragraph(
                    f"<b>Policy evidence ({_pdf_text(evidence['evidence_id'])}, p. {evidence['page']}):</b> "
                    f"{_pdf_text(evidence['text'])}",
                    styles["BodyText"],
                )
            )
        story.append(Spacer(1, 10))
    document.build(story)
    return buffer.getvalue()


def render_case(case: dict) -> None:
    if case.get("error"):
        st.error(f"Analysis failed: {case['error']}")
    if case["status"] != "complete":
        st.info(f"Case status: {case['status']}")
        return

    findings = case["findings"]
    gaps = sum(item["status"] == "Potential gap" for item in findings)
    review = sum(item["status"] == "Needs review" for item in findings)
    covered = sum(item["status"] == "Likely covered" for item in findings)
    first, second, third = st.columns(3)
    first.metric("Potential gaps", gaps)
    second.metric("Needs review", review)
    third.metric("Likely covered", covered)

    st.warning(
        "These are screening signals, not legal advice or a compliance certification. "
        "A low text similarity is not proof that a control is absent."
    )
    st.subheader("Findings and evidence")
    for finding in findings:
        marker = STATUS_COLORS.get(finding["status"], "⚪")
        title = (
            f"{marker} {finding['status']} · Regulation p. {finding['regulation_page']} "
            f"· Review: {finding['decision']}"
        )
        with st.expander(title, expanded=finding["status"] == "Potential gap"):
            st.markdown("**Requirement**")
            st.write(finding["requirement"])
            st.markdown("**Recommended next step**")
            st.write(finding["action"])
            st.caption(
                f"Retrieval similarity: {finding['similarity']:.2f} · "
                f"{finding['rationale']}"
            )
            st.markdown("**Regulation evidence**")
            st.info(finding["regulation_evidence"])
            st.markdown("**Policy evidence candidates**")
            evidence_items = json.loads(finding["policy_evidence"])
            if not evidence_items:
                st.write("No matching policy passage was retrieved.")
            for evidence in evidence_items:
                st.write(
                    f"**{evidence['evidence_id']} · Policy p. {evidence['page']} "
                    f"· Similarity {evidence['similarity']:.2f}**"
                )
                st.write(evidence["text"])
            with st.form(f"review-{finding['finding_id']}"):
                decision = st.selectbox(
                    "Reviewer decision",
                    ["pending", "confirmed", "dismissed", "resolved"],
                    index=["pending", "confirmed", "dismissed", "resolved"].index(
                        finding["decision"]
                    ),
                    key=f"decision-{finding['finding_id']}",
                )
                note = st.text_input(
                    "Review note (optional)",
                    value=finding["review_note"],
                    key=f"note-{finding['finding_id']}",
                )
                if st.form_submit_button("Save review"):
                    if decision == "pending":
                        st.error("Choose confirmed, dismissed, or resolved to record a review.")
                    else:
                        try:
                            api_request(
                                "POST",
                                f"/cases/{case['case_id']}/findings/{finding['finding_id']}/review",
                                json={"decision": decision, "note": note},
                            )
                            st.success("Review decision recorded in the audit log.")
                            st.rerun()
                        except RuntimeError as exc:
                            st.error(str(exc))

    st.download_button(
        "Download review checklist (PDF)",
        data=checklist_pdf(case),
        file_name=f"regulasynth-{case['case_id'][:8]}-checklist.pdf",
        mime="application/pdf",
    )
    st.download_button(
        "Download findings (JSON)",
        data=json.dumps(case, indent=2, ensure_ascii=False),
        file_name=f"regulasynth-{case['case_id'][:8]}-findings.json",
        mime="application/json",
    )


with st.sidebar:
    st.subheader("Analysis mode")
    mode = st.radio(
        "Choose analysis",
        ["Local (free, private)", "Gemini API (optional)"],
        help="Local mode uses transparent lexical matching and needs no API key. "
        "Gemini sends extracted document text to Google; use it only if permitted.",
    )
    st.caption("Local mode makes no external AI calls. Gemini quotas and pricing depend on Google's current terms.")
    try:
        health = api_request("GET", "/health", timeout=5)
        st.success(f"Backend: {health['status']}")
    except RuntimeError as exc:
        st.error(str(exc))

with st.form("new-case"):
    st.subheader("Start a document review")
    case_name = st.text_input("Case name", placeholder="e.g. Data privacy policy review")
    regulation_file = st.file_uploader(
        "New regulation PDF", type=["pdf"], key="regulation", max_upload_size=25
    )
    policy_files = st.file_uploader(
        "Existing policy / SOP PDF(s)",
        type=["pdf"],
        accept_multiple_files=True,
        key="policies",
        max_upload_size=25,
    )
    submitted = st.form_submit_button("Analyze documents", type="primary")

if submitted:
    if not regulation_file or not policy_files:
        st.error("Upload one regulation PDF and at least one policy PDF.")
    else:
        file_parts = [
            (
                "regulation_pdf",
                (regulation_file.name, regulation_file.getvalue(), "application/pdf"),
            )
        ]
        file_parts.extend(
            (
                "policy_pdfs",
                (policy.name, policy.getvalue(), "application/pdf"),
            )
            for policy in policy_files
        )
        try:
            with st.spinner("Extracting text and creating your case..."):
                created = api_request(
                    "POST",
                    "/cases",
                    data={"case_name": case_name or "Compliance review"},
                    files=file_parts,
                )
            st.session_state["current_case_id"] = created["case_id"]
            selected_mode = "gemini" if mode.startswith("Gemini") else "local"
            with st.spinner("Comparing requirements with policy evidence..."):
                result = api_request(
                    "POST",
                    f"/cases/{created['case_id']}/run",
                    json={"mode": selected_mode},
                )
            st.session_state["current_case_id"] = result["case_id"]
            st.success("Analysis complete. Review each finding and evidence passage.")
        except RuntimeError as exc:
            st.error(str(exc))

case_id = st.session_state.get("current_case_id")
if case_id:
    st.divider()
    try:
        current_case = api_request("GET", f"/cases/{case_id}")
        if current_case["status"] in {"ready", "failed"}:
            if current_case.get("error"):
                st.error(f"Analysis failed: {current_case['error']}")
            st.info("The case and extracted documents are saved. Retry with local analysis.")
            if st.button("Retry with local analysis"):
                try:
                    api_request(
                        "POST", f"/cases/{case_id}/run", json={"mode": "local"}
                    )
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))
        else:
            render_case(current_case)
    except RuntimeError as exc:
        st.error(str(exc))
