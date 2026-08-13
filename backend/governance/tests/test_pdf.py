from io import BytesIO

from reportlab.pdfgen import canvas

from crew.pdf import extract_pages, extract_text


def _pdf_bytes(*page_texts: str) -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output)
    for text in page_texts:
        document.drawString(72, 760, text)
        document.showPage()
    document.save()
    return output.getvalue()


def test_extract_pages_returns_one_entry_per_page() -> None:
    pages = extract_pages(_pdf_bytes("Primera pagina", "Segunda pagina"))
    assert len(pages) == 2
    assert "Primera pagina" in pages[0]
    assert "Segunda pagina" in pages[1]


def test_extract_text_joins_pages_with_markers() -> None:
    text = extract_text(_pdf_bytes("Contenido de prueba"))
    assert "Página 1" in text
    assert "Contenido de prueba" in text


def test_extract_text_respects_max_chars() -> None:
    text = extract_text(_pdf_bytes("X" * 50), max_chars=10)
    assert len(text) <= 10
