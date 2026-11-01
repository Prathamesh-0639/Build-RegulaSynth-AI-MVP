# RegulaSynth AI

RegulaSynth is a source-grounded MVP for screening a new regulation against one or
more internal policy PDFs. It extracts selectable PDF text, retrieves likely
matching policy passages, produces a review checklist, and records reviewer
decisions. It is designed as a demonstration of auditable GenAI and operations
automation for the Thomson Reuters AI Intern role.

> **Important:** This prototype is not legal advice, a compliance certification,
> or a replacement for qualified review. Local similarity scores are retrieval
> signals only. Scanned/image-only PDFs need OCR, which is not included.

## What works

- Streamlit UI to upload one regulation and multiple policy/SOP PDFs.
- FastAPI endpoints for case creation, analysis, document retrieval, and review.
- Page-aware text extraction using `pypdf`.
- Local, zero-API-cost matching (TF-IDF-style term weighting is not used; the
  MVP uses transparent token cosine similarity) with no document data sent out.
- Optional Gemini analysis when the user explicitly selects it and configures a
  key. Extracted document text is sent to Google in that mode. Quota, model
  availability, and pricing are controlled by Google's current terms.
- SQLite persistence for cases, extracted text, findings, and reviewer audit
  events. SQLite is the no-account, local MVP alternative to MongoDB.
- Findings show the exact regulation excerpt and retrieved policy evidence
  candidates with page numbers and IDs.
- Reviewer decisions (confirmed, dismissed, resolved) are persisted.
- Downloadable PDF checklist and JSON findings export.
- Per-PDF 25 MB upload limit.

## Run locally (Windows PowerShell)

Python 3.10+ recommended.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

In the first PowerShell terminal, start the API:

```powershell
python -m uvicorn backend.main:app --reload
```

In a second terminal, activate the same environment and start Streamlit:

```powershell
.\.venv\Scripts\Activate.ps1
python -m streamlit run frontend/app.py
```

Open the Streamlit URL printed in the terminal (normally
`http://localhost:8501`). API documentation is at `http://127.0.0.1:8000/docs`.
The app's default mode is local and requires no API key, database service, or
paid credits.

### Optional Gemini mode

Create a key in Google AI Studio if eligible for its current free tier. Set it
only in the API server's environment; do not commit it:

```powershell
$env:GEMINI_API_KEY = "your-key"
$env:GEMINI_MODEL = "gemini-2.5-flash"
python -m uvicorn backend.main:app --reload
```

Select **Gemini API (optional)** in the Streamlit sidebar. The free quota and
availability can change; confirm Google's current AI Studio terms before
sending any confidential document. The local mode remains available without
Gemini.

## API

- `GET /health`
- `POST /cases` — multipart `regulation_pdf`, one or more `policy_pdfs`, and
  optional `case_name`
- `GET /cases/{case_id}` — case, source documents' metadata, and findings
- `POST /cases/{case_id}/run` — JSON `{"mode":"local"}` or `{"mode":"gemini"}`
- `GET /documents/{doc_id}` — extracted text for a document
- `POST /cases/{case_id}/findings/{finding_id}/review` — JSON
  `{"decision":"confirmed|dismissed|resolved","note":"..."}`

## Demo suggestion

Use a public regulation and an internal/sample policy you are authorized to
share. Include clauses using clear obligation language (such as “must,”
“shall,” or “within 72 hours”) and compare against a policy with both covered
and missing controls. Inspect the cited excerpts, record one reviewer decision,
and download the checklist. The provided project-summary PDF is project
background, not a regulation/policy demo pair.

## Interview / resume framing

After you run the demo and can explain its limitations, an accurate project
bullet is:

> Built RegulaSynth AI, a Python/FastAPI and Streamlit compliance-screening MVP
> that extracts PDF requirements, retrieves policy evidence, and records
> human-reviewed findings with SQLite audit history; added optional
source-grounded Gemini analysis with a no-key local mode.

## Design and limitations

- Local mode deliberately labels matches as “Likely covered,” “Needs review,”
  or “Potential gap”; it does not claim that a control is legally sufficient.
- Requirement extraction prioritizes obligation terms and falls back to
  sentences when none are found. Dense tables, unusual layouts, and OCR-only
  content may not be parsed correctly.
- The prototype limits analysis to 50 extracted regulation requirements.
- The backend currently binds to localhost by default; do not expose it to the
  public internet without authentication, authorization, HTTPS, and appropriate
  data-protection controls.
- SQLite is for a single-user/local prototype. A multi-user deployment should
  use an access-controlled database and add authentication and retention
  controls.

## Project structure

```text
backend/
  main.py                 FastAPI endpoints
  database.py             SQLite schema and data helpers
  models.py               Request models
  services.py             Retrieval, analysis, and review workflow
  utils/
    pdf_extractor.py      PDF text extraction
    rag_tools.py          Requirement extraction and lexical retrieval
frontend/
  app.py                  Streamlit interface and exports
```
