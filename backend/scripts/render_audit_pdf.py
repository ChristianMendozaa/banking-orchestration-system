"""Renderiza la auditoría Markdown como PDF sin duplicar su contenido."""

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "doc" / "AUDITORIA_IMPLEMENTACION.md"
TARGET = ROOT / "doc" / "auditoria_backend_arquitectura.pdf"


def inline_markup(value: str) -> str:
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    escaped = html.escape(value)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', escaped)
    return escaped


def table_rows(lines: list[str]) -> list[list[str]]:
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


def page_footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setTitle("Auditoría integral del sistema de orquestación bancaria")
    canvas.setAuthor("Sistema de Orquestación de Atención Bancaria")
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#52606D"))
    canvas.drawString(
        document.leftMargin,
        0.42 * inch,
        "Auditoría contra TG1_ChristianMendoza.pdf",
    )
    canvas.drawRightString(
        letter[0] - document.rightMargin,
        0.42 * inch,
        f"Página {document.page}",
    )
    canvas.restoreState()


def build_story(markdown: str):
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="AuditTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#0B3A67"),
            alignment=TA_CENTER,
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="AuditH2",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=colors.HexColor("#1168BD"),
            spaceBefore=12,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            name="AuditH3",
            parent=styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13,
            textColor=colors.HexColor("#17324D"),
            spaceBefore=9,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="AuditBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.7,
            leading=12,
            textColor=colors.HexColor("#1F2933"),
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="AuditBullet",
            parent=styles["AuditBody"],
            leftIndent=14,
            firstLineIndent=-7,
            bulletIndent=5,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="AuditCode",
            parent=styles["Code"],
            fontName="Courier",
            fontSize=7.5,
            leading=10,
            leftIndent=10,
            backColor=colors.HexColor("#F1F5F9"),
            borderPadding=6,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            name="AuditCell",
            parent=styles["AuditBody"],
            fontSize=7.2,
            leading=9,
            spaceAfter=0,
        )
    )
    styles.add(
        ParagraphStyle(
            name="AuditCellHeader",
            parent=styles["AuditCell"],
            fontName="Helvetica-Bold",
            textColor=colors.white,
        )
    )

    story = []
    lines = markdown.splitlines()
    index = 0
    in_code = False
    code_lines: list[str] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            text = " ".join(line.strip() for line in paragraph_lines)
            story.append(Paragraph(inline_markup(text), styles["AuditBody"]))
            paragraph_lines.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            if in_code:
                story.append(
                    Paragraph(
                        "<br/>".join(html.escape(item) or " " for item in code_lines),
                        styles["AuditCode"],
                    )
                )
                code_lines.clear()
            in_code = not in_code
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if stripped.startswith("|"):
            flush_paragraph()
            block = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                block.append(lines[index])
                index += 1
            rows = table_rows(block)
            if rows:
                cells = [
                    [
                        Paragraph(
                            inline_markup(cell),
                            styles["AuditCellHeader" if row_index == 0 else "AuditCell"],
                        )
                        for cell in row
                    ]
                    for row_index, row in enumerate(rows)
                ]
                if len(rows[0]) == 3:
                    widths = [0.48 * inch, 0.95 * inch, 5.72 * inch]
                else:
                    widths = [7.15 * inch / len(rows[0])] * len(rows[0])
                table = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1168BD")),
                            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 4),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            (
                                "ROWBACKGROUNDS",
                                (0, 1),
                                (-1, -1),
                                [colors.white, colors.HexColor("#F8FAFC")],
                            ),
                        ]
                    )
                )
                story.extend([table, Spacer(1, 8)])
            continue
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        if stripped.startswith("# "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(stripped[2:]), styles["AuditTitle"]))
        elif stripped.startswith("## "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(stripped[3:]), styles["AuditH2"]))
        elif stripped.startswith("### "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(stripped[4:]), styles["AuditH3"]))
        elif re.match(r"^[-*] ", stripped):
            flush_paragraph()
            story.append(
                Paragraph(
                    inline_markup(stripped[2:]),
                    styles["AuditBullet"],
                    bulletText="•",
                )
            )
        elif match := re.match(r"^(\d+)\. (.+)", stripped):
            flush_paragraph()
            story.append(
                Paragraph(
                    inline_markup(match.group(2)),
                    styles["AuditBullet"],
                    bulletText=f"{match.group(1)}.",
                )
            )
        elif stripped == "\\pagebreak":
            flush_paragraph()
            story.append(PageBreak())
        else:
            paragraph_lines.append(stripped)
        index += 1

    flush_paragraph()
    return story


def main() -> None:
    document = SimpleDocTemplate(
        str(TARGET),
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.65 * inch,
        title="Auditoría integral del sistema de orquestación bancaria",
        author="Sistema de Orquestación de Atención Bancaria",
    )
    document.build(
        build_story(SOURCE.read_text(encoding="utf-8")),
        onFirstPage=page_footer,
        onLaterPages=page_footer,
    )
    print(TARGET)


if __name__ == "__main__":
    main()
