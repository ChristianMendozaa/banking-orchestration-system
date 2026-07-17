import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import tiktoken
from pypdf import PdfReader


@dataclass(frozen=True)
class TextChunk:
    ordinal: int
    page: int
    section: str | None
    content: str
    token_count: int
    content_sha256: str


def _encoding(model: str):
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def extract_pdf_pages(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    return [re.sub(r"[ \t]+", " ", page.extract_text() or "").strip() for page in reader.pages]


def chunk_pdf(
    path: Path,
    model: str,
    chunk_tokens: int,
    overlap_tokens: int,
    known_headings: set[str] | None = None,
) -> list[TextChunk]:
    encoding = _encoding(model)
    headings = {heading.casefold(): heading for heading in (known_headings or set())}
    result: list[TextChunk] = []
    ordinal = 0
    for page_number, page_text in enumerate(extract_pdf_pages(path), start=1):
        segments: list[tuple[str | None, list[str]]] = []
        current_section: str | None = f"Página {page_number}"
        current_lines: list[str] = []
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("Sistema de Orquestación") or line.startswith("Página "):
                continue
            matched = headings.get(line.casefold())
            if matched:
                if current_lines:
                    segments.append((current_section, current_lines))
                current_section = matched
                current_lines = []
                continue
            current_lines.append(line)
        if current_lines:
            segments.append((current_section, current_lines))

        for section, lines in segments:
            content = "\n".join(lines).strip()
            tokens = encoding.encode(content)
            start = 0
            while start < len(tokens):
                window = tokens[start : start + chunk_tokens]
                text = encoding.decode(window).strip()
                if text:
                    result.append(
                        TextChunk(
                            ordinal=ordinal,
                            page=page_number,
                            section=section,
                            content=text,
                            token_count=len(window),
                            content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                        )
                    )
                    ordinal += 1
                if start + chunk_tokens >= len(tokens):
                    break
                start += chunk_tokens - overlap_tokens
    return result
