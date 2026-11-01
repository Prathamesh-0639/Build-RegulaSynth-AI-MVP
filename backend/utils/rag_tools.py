import math
import re
from collections import Counter
from dataclasses import dataclass


REQUIREMENT_TERMS = re.compile(
    r"\b(shall|must|required|is required to|are required to|prohibited|"
    r"must not|shall not|at least|no later than|within \d+|ensure|maintain|"
    r"retain|notify|provide|establish|implement|report|record)\b",
    re.IGNORECASE,
)
WORD_PATTERN = re.compile(r"[a-z0-9]+")
PAGE_PATTERN = re.compile(r"\[Page (\d+)\]")


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    page: int
    text: str


def _page_number(text: str) -> int:
    match = PAGE_PATTERN.search(text)
    return int(match.group(1)) if match else 1


def _sentences(text: str) -> list[str]:
    cleaned = PAGE_PATTERN.sub("", text)
    parts = re.split(r"(?<=[.!?;])\s+|\n+", cleaned)
    return [part.strip(" \t-*•") for part in parts if len(part.strip()) >= 35]


def extract_requirements(text: str, limit: int = 50) -> list[TextChunk]:
    candidates = []
    seen = set()
    for page_block in re.split(r"(?=\[Page \d+\])", text):
        page = _page_number(page_block)
        for sentence in _sentences(page_block):
            normalized = " ".join(sentence.split())
            if REQUIREMENT_TERMS.search(normalized):
                key = normalized.casefold()
                if key not in seen:
                    candidates.append((page, normalized))
                    seen.add(key)

    if not candidates:
        for page_block in re.split(r"(?=\[Page \d+\])", text):
            page = _page_number(page_block)
            for sentence in _sentences(page_block):
                normalized = " ".join(sentence.split())
                if normalized and normalized.casefold() not in seen:
                    candidates.append((page, normalized))
                    seen.add(normalized.casefold())

    return [
        TextChunk(chunk_id=f"R{index}", page=page, text=sentence[:1200])
        for index, (page, sentence) in enumerate(candidates[:limit], start=1)
    ]


def policy_chunks(documents: list[dict]) -> list[TextChunk]:
    chunks = []
    for document_index, document in enumerate(documents, start=1):
        for page_block in re.split(r"(?=\[Page \d+\])", document["text"]):
            page = _page_number(page_block)
            for sentence_index, sentence in enumerate(_sentences(page_block), start=1):
                chunks.append(
                    TextChunk(
                        chunk_id=f"P{document_index}-{page}-{sentence_index}",
                        page=page,
                        text=" ".join(sentence.split())[:1200],
                    )
                )
    if not chunks:
        for document_index, document in enumerate(documents, start=1):
            for sentence_index, sentence in enumerate(_sentences(document["text"]), start=1):
                chunks.append(
                    TextChunk(
                        chunk_id=f"P{document_index}-1-{sentence_index}",
                        page=1,
                        text=" ".join(sentence.split())[:1200],
                    )
                )
    return chunks


def _terms(text: str) -> list[str]:
    return WORD_PATTERN.findall(text.casefold())


def similarity(left: str, right: str) -> float:
    left_terms = Counter(_terms(left))
    right_terms = Counter(_terms(right))
    if not left_terms or not right_terms:
        return 0.0
    vocabulary = set(left_terms) | set(right_terms)
    left_norm = math.sqrt(sum(left_terms[word] ** 2 for word in vocabulary))
    right_norm = math.sqrt(sum(right_terms[word] ** 2 for word in vocabulary))
    dot = sum(left_terms[word] * right_terms[word] for word in vocabulary)
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def retrieve_policy_evidence(
    requirement: str, chunks: list[TextChunk], limit: int = 2
) -> list[tuple[TextChunk, float]]:
    scored = [(chunk, similarity(requirement, chunk.text)) for chunk in chunks]
    return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]
