"""Local PDF text extraction for downloaded documents.

Mirrors `app/knowledge/chunking.py:extract_pdf_pages` in spirit -- extracted text is
fed to the Document Analyst as plain text, not re-chunked or re-indexed. Kept standalone
rather than imported from `backend/app` per this package's isolation (see pyproject.toml).
"""

import re
from io import BytesIO

from pypdf import PdfReader


def extract_pages(pdf_bytes: bytes) -> list[str]:
    reader = PdfReader(BytesIO(pdf_bytes))
    return [re.sub(r"[ \t]+", " ", page.extract_text() or "").strip() for page in reader.pages]


def extract_text(pdf_bytes: bytes, *, max_chars: int = 20_000) -> str:
    """Full document text, bounded so a large PDF doesn't blow the crew's context budget."""
    joined = "\n\n".join(
        f"--- Página {number} ---\n{text}"
        for number, text in enumerate(extract_pages(pdf_bytes), start=1)
        if text
    )
    return joined[:max_chars]
