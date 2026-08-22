"""Accepting a PDF into the corpus, and the form parsing that comes with it.

Everything a file has to survive before it is allowed to become a document: content
type, size ceiling, PDF signature, malware scan, page count, and the presence of
extractable text. The bytes land in a dotfile first and are only moved into place once
every check has passed, so a rejected upload never leaves a readable document behind.
"""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from pypdf import PdfReader

from app.core.config import Settings
from app.core.errors import AppError
from app.core.malware import scan_bytes


async def store_upload(
    upload: UploadFile, settings: Settings, storage_dir: Path
) -> tuple[Path, str, int, int, str]:
    if upload.content_type not in {None, "application/pdf", "application/octet-stream"}:
        raise AppError("INVALID_PDF", "El archivo debe ser un PDF", 415)
    max_bytes = settings.knowledge_max_upload_mb * 1024 * 1024
    data = await upload.read(max_bytes + 1)
    if not data or len(data) > max_bytes:
        raise AppError(
            "PDF_TOO_LARGE",
            f"El PDF no debe superar {settings.knowledge_max_upload_mb} MB",
            413,
        )
    if not data.startswith(b"%PDF-"):
        raise AppError("INVALID_PDF", "El archivo no contiene una firma PDF valida", 422)
    await scan_bytes(
        data,
        host=settings.clamav_host,
        port=settings.clamav_port,
        timeout_seconds=settings.clamav_timeout_seconds,
    )
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_key = f"{uuid4()}.pdf"
    path = storage_dir / storage_key
    temporary = storage_dir / f".{storage_key}.tmp"
    temporary.write_bytes(data)
    try:
        reader = PdfReader(str(temporary))
        page_count = len(reader.pages)
        if page_count == 0 or page_count > settings.knowledge_max_pages:
            raise AppError(
                "INVALID_PDF_PAGE_COUNT",
                f"El PDF debe tener entre 1 y {settings.knowledge_max_pages} paginas",
                422,
            )
        if not any((page.extract_text() or "").strip() for page in reader.pages):
            raise AppError(
                "PDF_WITHOUT_TEXT",
                "El PDF no contiene texto extraible para indexar",
                422,
            )
        temporary.replace(path)
    except AppError:
        temporary.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise AppError("INVALID_PDF", "No fue posible leer el PDF", 422) from exc
    original_name = Path(upload.filename or "documento.pdf").name[:255]
    return path, hashlib.sha256(data).hexdigest(), len(data), page_count, original_name


def parse_json_list(raw: str, field_name: str) -> list[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AppError("INVALID_FORM_FIELD", f"{field_name} debe ser JSON valido", 422) from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise AppError("INVALID_FORM_FIELD", f"{field_name} debe ser una lista de textos", 422)
    return list(dict.fromkeys(item.strip() for item in value if item.strip()))
