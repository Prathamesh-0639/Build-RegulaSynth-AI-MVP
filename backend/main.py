from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from backend import database, services
from backend.models import ReviewRequest, RunRequest
from backend.utils.pdf_extractor import extract_pdf


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize_database()
    yield


app = FastAPI(
    title="RegulaSynth API",
    description="Source-grounded regulatory gap analysis MVP",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _valid_uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Resource not found.") from exc


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/cases", status_code=201)
async def create_case(
    case_name: Annotated[str, Form()] = "Compliance review",
    regulation_pdf: Annotated[UploadFile, File()] = ...,
    policy_pdfs: Annotated[list[UploadFile], File()] = ...,
) -> dict:
    if not policy_pdfs:
        raise HTTPException(status_code=422, detail="Upload at least one policy PDF.")
    uploads = [(regulation_pdf, "regulation"), *((upload, "policy") for upload in policy_pdfs)]
    extracted = []
    for upload, kind in uploads:
        data = await upload.read()
        if len(data) > 25 * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"{upload.filename} exceeds the 25 MB limit.")
        try:
            document = extract_pdf(data, upload.filename or "upload.pdf")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        extracted.append(
            {
                "kind": kind,
                "name": upload.filename or "document.pdf",
                "page_count": document.page_count,
                "text": document.text,
            }
        )
    case_id = services.create_case(case_name, extracted[0], extracted[1:])
    return {"case_id": case_id, "status": "ready"}


@app.get("/cases/{case_id}")
def read_case(case_id: str) -> dict:
    case = services.get_case(_valid_uuid(case_id))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found.")
    return case


@app.post("/cases/{case_id}/run")
def run_case(case_id: str, request: RunRequest) -> dict:
    case_id = _valid_uuid(case_id)
    try:
        return services.run_analysis(case_id, request.mode)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analysis failed: {exc}") from exc


@app.get("/documents/{doc_id}")
def read_document(doc_id: str) -> dict:
    document = services.get_document(_valid_uuid(doc_id))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


@app.post("/cases/{case_id}/findings/{finding_id}/review")
def review_case_finding(case_id: str, finding_id: str, request: ReviewRequest) -> dict:
    case_id = _valid_uuid(case_id)
    finding_id = _valid_uuid(finding_id)
    finding = services.review_finding(
        case_id, finding_id, request.decision, request.note.strip()
    )
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found in this case.")
    return finding
