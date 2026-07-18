"""Genera los documentos operativos administrados junto con el sistema."""

import hashlib
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "backend" / "seed" / "operational_seed.json"
RAG_DIR = ROOT / "doc" / "rag"
OPERATIONS_DIR = ROOT / "doc" / "operacion"
VERSION = "2026.07.1"

BLUE = colors.HexColor("#0B4F8A")
LIGHT_BLUE = colors.HexColor("#EAF4FC")
INK = colors.HexColor("#172B3A")
MUTED = colors.HexColor("#52606D")


def styles():
    sheet = getSampleStyleSheet()
    sheet.add(
        ParagraphStyle(
            name="DocumentTitle",
            parent=sheet["Title"],
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=23,
            alignment=TA_CENTER,
            textColor=BLUE,
            spaceAfter=5 * mm,
        )
    )
    sheet.add(
        ParagraphStyle(
            name="DocumentSubtitle",
            parent=sheet["BodyText"],
            fontSize=8.5,
            leading=11,
            alignment=TA_CENTER,
            textColor=MUTED,
            spaceAfter=7 * mm,
        )
    )
    sheet.add(
        ParagraphStyle(
            name="Section",
            parent=sheet["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=BLUE,
            spaceBefore=3 * mm,
            spaceAfter=2 * mm,
        )
    )
    sheet.add(
        ParagraphStyle(
            name="BodyOperational",
            parent=sheet["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=INK,
            spaceAfter=3 * mm,
        )
    )
    sheet.add(
        ParagraphStyle(
            name="SmallOperational",
            parent=sheet["BodyText"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=MUTED,
        )
    )
    sheet.add(
        ParagraphStyle(
            name="CardTitle",
            parent=sheet["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=BLUE,
            spaceAfter=1.5 * mm,
        )
    )
    return sheet


def footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        document.leftMargin,
        10 * mm,
        "Sistema de Orquestación de Atención Bancaria",
    )
    canvas.drawRightString(
        letter[0] - document.rightMargin,
        10 * mm,
        f"Página {document.page}",
    )
    canvas.restoreState()


def render_document(
    target: Path,
    title: str,
    sections: list[tuple[str, str]],
    *,
    sources: list[str] | None = None,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    document_styles = styles()
    story = [
        Paragraph(title, document_styles["DocumentTitle"]),
        Paragraph(
            f"Versión {VERSION} · Vigente desde el 17/07/2026",
            document_styles["DocumentSubtitle"],
        ),
    ]
    for heading, content in sections:
        story.extend(
            [
                Paragraph(heading, document_styles["Section"]),
                Paragraph(content, document_styles["BodyOperational"]),
            ]
        )
    if sources:
        story.append(Paragraph("Fuentes consultadas", document_styles["Section"]))
        for source in sources:
            story.append(Paragraph(source, document_styles["SmallOperational"]))
            story.append(Spacer(1, 1.5 * mm))

    document = SimpleDocTemplate(
        str(target),
        pagesize=letter,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="Sistema de Orquestación de Atención Bancaria",
        invariant=1,
    )
    document.build(story, onFirstPage=footer, onLaterPages=footer)


def render_rag_documents() -> None:
    render_document(
        RAG_DIR / "04_banca_digital_y_seguridad.pdf",
        "Banca digital y seguridad del BMSC",
        [
            (
                "Servicios digitales",
                "La Banca por Internet y la Banca Móvil permiten consultas y transacciones "
                "desde canales digitales. Entre las funciones publicadas se encuentran "
                "transferencias, pagos y configuración de límites para tarjetas. Los límites "
                "existen como medida de seguridad y pueden gestionarse mediante los canales "
                "habilitados.",
            ),
            (
                "Recuperación de acceso",
                "El banco publica tutoriales para activación, primer ingreso y "
                "restablecimiento de contraseña. El Contact Center también orienta sobre "
                "habilitación, desbloqueo y restablecimiento de contraseñas de Banca Móvil y "
                "Banca por Internet.",
            ),
            (
                "Protección de credenciales",
                "El BMSC informa que nunca solicita usuarios, contraseñas, claves de tarjeta "
                "ni validación de cuenta mediante correos, redes sociales o enlaces externos. "
                "Ante una solicitud de ese tipo, no se debe abrir el enlace ni entregar datos; "
                "se debe reportar el evento en una agencia o en la Central de Consultas.",
            ),
            (
                "Atención en sucursal",
                "El asistente no solicita PIN, contraseña, código de verificación, token ni "
                "número completo de tarjeta. Los problemas de acceso propios requieren el "
                "código de cliente en el campo protegido y, cuando no exista orientación "
                "pública suficiente, se asignan a un ejecutivo de banca digital.",
            ),
        ],
        sources=[
            "https://www.bmsc.com.bo/tech/internetBank",
            "https://www.bmsc.com.bo/tech",
            "https://www.bmsc.com.bo/",
        ],
    )
    render_document(
        RAG_DIR / "06_reclamos_y_derechos.pdf",
        "Reclamos y derechos del consumidor financiero",
        [
            (
                "Derechos principales",
                "La Ley 393 reconoce acceso equitativo, servicios adecuados, información "
                "clara y oportuna, trato digno, canales eficientes de reclamo, "
                "confidencialidad y derecho a efectuar consultas, peticiones y solicitudes.",
            ),
            (
                "Primera instancia",
                "El reclamo se presenta inicialmente ante la entidad financiera mediante su "
                "Punto de Reclamo o canales publicados. El BMSC incluye registro y seguimiento "
                "de reclamos entre los servicios del Contact Center. Se debe conservar el "
                "número o constancia de seguimiento.",
            ),
            (
                "Segunda instancia",
                "Si la primera instancia concluye y el consumidor no está conforme, puede "
                "acudir a la Defensoría del Consumidor Financiero de ASFI. ASFI publica la "
                "línea gratuita 800-103-103 para orientación. El asistente registra y deriva "
                "el caso; la resolución corresponde al canal responsable.",
            ),
            (
                "Información y confidencialidad",
                "La entidad debe responder de forma comprensible y oportuna y resguardar la "
                "información del consumidor. Los paneles gerenciales presentan agregados "
                "operativos y omiten identificadores y detalles financieros de los casos.",
            ),
        ],
        sources=[
            "https://www.bmsc.com.bo/help",
            "https://asfi.gob.bo/la/derechos-del-consumidor-financiero",
            "https://www.asfi.gob.bo/sites/default/files/2025-09/"
            "Ley%20N%C2%B0%20393%20de%20Servicios%20Financieros.pdf",
        ],
    )
    render_document(
        RAG_DIR / "07_manual_operativo_sucursal.pdf",
        "Manual operativo de atención presencial",
        [
            (
                "Clasificación de ventanillas",
                "Ventanilla 1 atiende prevención de fraude; Ventanilla 3, tarjetas y "
                "seguridad; Ventanilla 4, créditos y atención general; Ventanilla 5, banca "
                "digital. Si el especialista está ocupado, el caso queda pendiente sin "
                "reasignación a un perfil incompatible.",
            ),
            (
                "Prioridad",
                "Fraude y movimientos no reconocidos tienen prioridad crítica. Bloqueo por "
                "pérdida o robo tiene prioridad alta. Banca digital y crédito tienen prioridad "
                "media. Consultas generales tienen prioridad baja. La atención preferente eleva "
                "un nivel los casos bajos o medios, sin superar casos críticos de seguridad.",
            ),
            (
                "Verificación protegida",
                "Las consultas generales pueden procesarse sin identificación. Las consultas "
                "personalizadas o sensibles solicitan un código de cliente escrito en el campo "
                "protegido. El valor se verifica mediante una huella criptográfica, se muestra "
                "parcialmente oculto y no se conserva de forma completa.",
            ),
            (
                "Asignación y espera",
                "La selección exige una habilidad compatible y pondera afinidad semántica, "
                "experiencia y carga activa. La espera estimada se calcula con ocho minutos por "
                "caso activo, incluida la atención recién asignada.",
            ),
            (
                "Trazabilidad",
                "Cada atención genera ticket, categoría, prioridad, ejecutivo, ventanilla, "
                "espera estimada, estado y eventos. El audio y la transcripción original no se "
                "guardan. El resumen se enmascara antes de ser visible para el personal.",
            ),
        ],
    )


def skill_label(value: str) -> str:
    return value.replace("_", " ").title()


def render_executive_catalog(data: dict) -> None:
    catalog = data["catalog"]
    document_styles = styles()
    story = [
        Paragraph("Catálogo operativo de perfiles ejecutivos", document_styles["DocumentTitle"]),
        Paragraph(
            f"{catalog['bank']} · {catalog['branch']} · Vigente desde el 17/07/2026",
            document_styles["DocumentSubtitle"],
        ),
        Paragraph("Criterio de asignación", document_styles["Section"]),
        Paragraph(
            "El orquestador considera únicamente perfiles con una habilidad compatible con "
            "la categoría del caso. Entre ellos calcula el puntaje con 70% de afinidad "
            "semántica, 20% de experiencia y 10% de disponibilidad. Los empates se resuelven "
            "por mayor tiempo desde la última asignación y luego por identificador estable.",
            document_styles["BodyOperational"],
        ),
        Paragraph("Capacidad y espera", document_styles["Section"]),
        Paragraph(
            "La espera informada al cliente es de "
            f"{catalog['estimated_service_minutes']} minutos por caso activo del ejecutivo, "
            "incluida la atención recién asignada. Un perfil inactivo o sin habilidad "
            "compatible no puede recibir el ticket.",
            document_styles["BodyOperational"],
        ),
    ]

    for index, executive in enumerate(data["executives"]):
        skill_rows = [
            [
                Paragraph("<b>Especialidad</b>", document_styles["SmallOperational"]),
                Paragraph("<b>Nivel</b>", document_styles["SmallOperational"]),
                Paragraph("<b>Alcance</b>", document_styles["SmallOperational"]),
            ]
        ]
        for category, skill in executive["skills"].items():
            skill_rows.append(
                [
                    Paragraph(skill_label(category), document_styles["SmallOperational"]),
                    Paragraph(f"{skill['level']} / 5", document_styles["SmallOperational"]),
                    Paragraph(skill["description"], document_styles["SmallOperational"]),
                ]
            )
        table = Table(skill_rows, colWidths=[38 * mm, 17 * mm, 105 * mm], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BLUE),
                    ("TEXTCOLOR", (0, 0), (-1, 0), BLUE),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C7D1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        card = [
            Paragraph(executive["name"], document_styles["CardTitle"]),
            Paragraph(
                f"{executive['title']} · {executive['window']}",
                document_styles["BodyOperational"],
            ),
            table,
            Spacer(1, 6 * mm),
        ]
        story.append(KeepTogether(card))
        if index == 1:
            story.append(PageBreak())

    target = OPERATIONS_DIR / "catalogo_perfiles_ejecutivos.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(target),
        pagesize=letter,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title="Catálogo operativo de perfiles ejecutivos",
        author="Sistema de Orquestación de Atención Bancaria",
        invariant=1,
    )
    document.build(story, onFirstPage=footer, onLaterPages=footer)


def update_manifest() -> None:
    manifest_path = RAG_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    managed = {
        "banca-digital-seguridad": {
            "verified_at": "2026-07-17T00:00:00+00:00",
            "review_after": "2026-10-15T00:00:00+00:00",
        },
        "reclamos-derechos": {
            "verified_at": "2026-07-17T00:00:00+00:00",
            "review_after": "2026-10-15T00:00:00+00:00",
        },
        "manual-operativo-sucursal": {
            "verified_at": "2026-07-17T00:00:00+00:00",
            "review_after": "2027-07-17T00:00:00+00:00",
            "source_type": "INTERNAL",
        },
    }
    manifest["generated_at"] = "2026-07-17T00:00:00+00:00"
    for specification in manifest["documents"]:
        changes = managed.get(specification["slug"])
        if not changes:
            continue
        specification.update(changes)
        specification["version"] = VERSION
        pdf_path = RAG_DIR / specification["file_name"]
        specification["sha256"] = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    data = json.loads(SEED.read_text(encoding="utf-8"))
    render_rag_documents()
    render_executive_catalog(data)
    update_manifest()
    print(RAG_DIR / "04_banca_digital_y_seguridad.pdf")
    print(RAG_DIR / "06_reclamos_y_derechos.pdf")
    print(RAG_DIR / "07_manual_operativo_sucursal.pdf")
    print(OPERATIONS_DIR / "catalogo_perfiles_ejecutivos.pdf")


if __name__ == "__main__":
    main()
