from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    page_count: int


def extract_pdf(data: bytes, filename: str) -> ExtractedDocument:
    if not filename.lower().endswith(".pdf") or not data.startswith(b"%PDF"):
        raise ValueError(f"{filename} is not a valid PDF file.")

    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError(f"{filename} is password-protected. Upload an unlocked PDF.")
        pages = []
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = (page.extract_text() or "").strip()
            if page_text:
                pages.append(f"[Page {page_number}]\n{page_text}")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Could not read {filename}: {exc}") from exc

    text = "\n\n".join(pages).strip()
    if not text:
        raise ValueError(
            f"No selectable text was found in {filename}. OCR is not included in this MVP; "
            "use a text-based PDF."
        )
    return ExtractedDocument(text=text, page_count=len(reader.pages))
