import hashlib
import json
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.knowledge.corpus import CORPUS_DOCUMENTS, CorpusDocument


class InvariantCanvas(Canvas):
    def __init__(self, *args, **kwargs):
        kwargs["invariant"] = 1
        super().__init__(*args, **kwargs)


def _styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="DocumentTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=24,
            textColor=colors.HexColor("#12385B"),
            alignment=TA_CENTER,
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionTitle",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=colors.HexColor("#12385B"),
            spaceBefore=12,
            spaceAfter=7,
        )
    )
    styles["BodyText"].fontName = "Helvetica"
    styles["BodyText"].fontSize = 10.5
    styles["BodyText"].leading = 15
    styles["BodyText"].spaceAfter = 8
    return styles


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D5DEE7"))
    canvas.line(2 * cm, 1.35 * cm, letter[0] - 2 * cm, 1.35 * cm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#5C6B78"))
    canvas.drawString(2 * cm, 0.9 * cm, "Sistema de Orquestación de Atención Bancaria")
    canvas.drawRightString(letter[0] - 2 * cm, 0.9 * cm, f"Página {document.page}")
    canvas.restoreState()


def _document(output: Path, title: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(output),
        pagesize=letter,
        title=title,
        author="Sistema de Orquestación de Atención Bancaria",
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
    )


def _build_corpus_pdf(spec: CorpusDocument, output: Path) -> None:
    styles = _styles()
    story: list[Any] = [
        Paragraph(spec.title, styles["DocumentTitle"]),
        Paragraph(
            f"Versión {spec.version} · Información verificada el {spec.verified_at:%d/%m/%Y}",
            styles["BodyText"],
        ),
        Spacer(1, 6),
    ]
    for heading, body in spec.sections:
        story.append(Paragraph(heading, styles["SectionTitle"]))
        story.append(Paragraph(body, styles["BodyText"]))
    if spec.source_urls:
        story.append(Paragraph("Fuentes consultadas", styles["SectionTitle"]))
        for url in spec.source_urls:
            story.append(Paragraph(url, styles["BodyText"]))
    _document(output, spec.title).build(
        story,
        onFirstPage=_footer,
        onLaterPages=_footer,
        canvasmaker=InvariantCanvas,
    )


FUNCTIONAL_REQUIREMENTS = (
    ("RF-01", "Voz en español", "Parcial", "Token Realtime disponible; frontend actual simulado."),
    ("RF-02", "Confirmación", "Cumple", "Resumen, confirmación y corrección implementados."),
    ("RF-03", "Clasificación", "Cumple", "Cinco categorías bancarias estructuradas."),
    ("RF-04", "Desambiguación", "Cumple", "Preguntas breves con límite configurable."),
    (
        "RF-05",
        "Enmascaramiento PII",
        "Parcial",
        "PII local antes de análisis; audio llega al transcriptor.",
    ),
    ("RF-06", "Priorización", "Cumple", "Reglas, señales de riesgo y atención preferente."),
    ("RF-07", "Casos críticos", "Cumple", "Fraude y bloqueo activan prioridad alta/crítica."),
    ("RF-08", "Atención inicial", "Cumple", "RAG con evidencia o derivación humana."),
    ("RF-09", "Derivación", "Cumple", "Perfil, embedding, experiencia y carga."),
    ("RF-10", "Ticket y trazabilidad", "Cumple", "Ticket, estados y eventos auditables."),
    ("RF-11", "Vista operativa", "Cumple", "Listado y detalle con control por ejecutivo."),
    ("RF-12", "Vista gerencial", "Cumple", "Métricas, filtros y casos agregados."),
    ("RF-13", "Reclamo", "Cumple", "Corpus BMSC/ASFI y seguimiento en resultado."),
    ("RF-14", "Atención preferente", "Cumple", "Marca y elevación controlada de prioridad."),
    ("RF-15", "Identificación básica", "Cumple", "Identificador ficticio solicitado por nivel."),
    ("RF-16", "Validación demostrativa", "Cumple", "Hash contra clientes de demostración."),
    ("RF-17", "Control de respuesta", "Cumple", "Solo consultas generales admiten automatización."),
)

NON_FUNCTIONAL_REQUIREMENTS = (
    ("RNF-01", "Usabilidad", "No verificable", "Depende del frontend, fuera de este alcance."),
    ("RNF-02", "Privacidad", "Parcial", "Minimización y masking; transcripción es externa."),
    ("RNF-03", "Seguridad de acceso", "Cumple", "JWT, sesión de kiosco y roles."),
    ("RNF-04", "Auditoría", "Cumple", "Eventos y trazas RAG sin texto original."),
    ("RNF-05", "Disponibilidad", "Cumple", "Fallback conservador y derivación ante fallo RAG."),
    ("RNF-06", "Rendimiento", "Cumple", "Timeouts, batching, índice HNSW y top-k."),
    ("RNF-07", "Modularidad", "Cumple", "Agentes, orquestador, repositorios y conocimiento."),
    ("RNF-08", "Escalabilidad lógica", "Cumple", "Corpus versionado y reglas configurables."),
    ("RNF-09", "Mantenibilidad", "Cumple", "CLI reproducible, tipado y pruebas."),
    ("RNF-10", "Accesibilidad", "No verificable", "Corresponde a la interfaz web."),
    ("RNF-11", "Alcance académico", "Cumple", "Datos ficticios, sin core bancario."),
    ("RNF-12", "Cumplimiento documental", "Cumple", "Matriz, PDFs, fuentes y evaluación."),
    ("RNF-13", "Minimización", "Cumple", "Hashes e identificadores enmascarados."),
    ("RNF-14", "Identificación/autenticación", "Cumple", "Separación explícita en dominio y voz."),
    ("RNF-15", "Exposición por rol", "Cumple", "Resúmenes enmascarados y métricas agregadas."),
)


def _audit_table(rows, styles):
    data = [["ID", "Requisito", "Estado", "Evidencia / observación"]]
    data.extend([Paragraph(value, styles["BodyText"]) for value in row] for row in rows)
    table = Table(data, colWidths=[1.8 * cm, 3.4 * cm, 2.3 * cm, 9.8 * cm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12385B")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#AAB7C4")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6F9")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _build_audit_pdf(output: Path) -> None:
    styles = _styles()
    story: list[Any] = [
        Paragraph("Auditoría del backend, arquitectura y agentes", styles["DocumentTitle"]),
        Paragraph(
            "Documento de verificación contra TG1_ChristianMendoza.pdf. La auditoría parte de "
            "una línea base con análisis estático limpio y 17 pruebas automatizadas aprobadas.",
            styles["BodyText"],
        ),
        Paragraph("Conclusión ejecutiva", styles["SectionTitle"]),
        Paragraph(
            "El backend materializa el monolito modular FastAPI, el orquestador central y los "
            "cuatro agentes del diseño. La extensión incorpora conocimiento RAG versionado, "
            "embeddings locales/Supabase, evidencia por respuesta y fallback humano. Los puntos "
            "que dependen del frontend continúan sin verificación porque la interfaz existente "
            "usa mocks.",
            styles["BodyText"],
        ),
        Paragraph("Correspondencia arquitectónica", styles["SectionTitle"]),
        Paragraph(
            "Interacción: endpoints de kiosco y credenciales efímeras. Privacidad: "
            "PIIMaskingService. "
            "Orquestación: OrchestratorService. Agentes: clasificación, priorización, derivación y "
            "atención inicial. Persistencia: SQLAlchemy sobre PostgreSQL/pgvector. Visualización: "
            "endpoints ejecutivos y gerenciales. Conocimiento: repositorio RAG usado por atención "
            "inicial.",
            styles["BodyText"],
        ),
        Paragraph("Requerimientos funcionales", styles["SectionTitle"]),
        _audit_table(FUNCTIONAL_REQUIREMENTS, styles),
        PageBreak(),
        Paragraph("Requerimientos no funcionales", styles["SectionTitle"]),
        _audit_table(NON_FUNCTIONAL_REQUIREMENTS, styles),
        Paragraph("Controles de grounding", styles["SectionTitle"]),
        Paragraph(
            "Una respuesta automática exige recuperación sobre consulta enmascarada, umbral "
            "mínimo, "
            "salida estructurada y referencias a chunks recuperados. Si falta evidencia, el modelo "
            "no responde y el caso se deriva. Realtime no crea respuestas autónomas.",
            styles["BodyText"],
        ),
        Paragraph("Limitaciones conocidas", styles["SectionTitle"]),
        Paragraph(
            "La transcripción de voz requiere enviar audio a OpenAI antes del enmascaramiento. "
            "Supabase necesita cadenas PostgreSQL adicionales a SUPABASE_URL y la service-role "
            "key. "
            "La veracidad de contenido simulado depende de la política del corpus; RAG garantiza "
            "restricción a evidencia, no que una regla simulada represente una política bancaria "
            "real.",
            styles["BodyText"],
        ),
    ]
    _document(output, "Auditoría del backend y arquitectura").build(
        story,
        onFirstPage=_footer,
        onLaterPages=_footer,
        canvasmaker=InvariantCanvas,
    )


def generate_pdfs(corpus_dir: Path, audit_path: Path) -> dict[str, Any]:
    corpus_dir.mkdir(parents=True, exist_ok=True)
    manifest_documents = []
    for spec in CORPUS_DOCUMENTS:
        output = corpus_dir / spec.file_name
        _build_corpus_pdf(spec, output)
        checksum = hashlib.sha256(output.read_bytes()).hexdigest()
        manifest_documents.append(
            {
                "slug": spec.slug,
                "file_name": spec.file_name,
                "title": spec.title,
                "version": spec.version,
                "source_type": spec.source_type.value,
                "categories": [category.value for category in spec.categories],
                "source_urls": list(spec.source_urls),
                "verified_at": spec.verified_at.isoformat(),
                "review_after": spec.review_after.isoformat(),
                "sha256": checksum,
            }
        )
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    _build_audit_pdf(audit_path)
    manifest = {
        "generated_at": "2026-07-16T00:00:00+00:00",
        "documents": manifest_documents,
    }
    (corpus_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
