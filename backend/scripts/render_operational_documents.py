"""Generate the managed operational documents alongside the system."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
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
# Bumped on every content revision: `KnowledgeIngestionService._ingest_document` refuses
# to re-ingest a slug whose bytes changed while its version stayed the same, so an
# edit here without a bump is a failed corpus bootstrap rather than a silent swap.
VERSION = "2026.08.1"
VIGENTE_DESDE = "18/08/2026"

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
) -> list[str]:
    """Renders one RAG document and returns the exact heading strings it wrote, in order
    -- including "Fuentes consultadas" when `sources` is given. The chunker in
    `app/knowledge/chunking.py` splits a document by exact (case-insensitive) match
    against `manifest.json`'s `sections` list, so returning the real headings here lets
    the manifest be generated from what was actually rendered instead of hand-copied --
    the two can no longer drift apart, which is what silently dropped content out of the
    index before."""
    target.parent.mkdir(parents=True, exist_ok=True)
    document_styles = styles()
    story = [
        Paragraph(title, document_styles["DocumentTitle"]),
        Paragraph(
            f"Versión {VERSION} · Vigente desde el {VIGENTE_DESDE}",
            document_styles["DocumentSubtitle"],
        ),
    ]
    headings = [heading for heading, _ in sections]
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
        headings.append("Fuentes consultadas")

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
    return headings


def render_rag_documents() -> dict[str, list[str]]:
    """Renders every RAG document and returns `{slug: headings}` for `update_manifest`."""
    sections: dict[str, list[str]] = {}

    sections["canales-atencion-bmsc"] = render_document(
        RAG_DIR / "01_canales_y_atencion_bmsc.pdf",
        "Canales y atención del Banco Mercantil Santa Cruz",
        [
            (
                "Canales de atención",
                "El Banco Mercantil Santa Cruz ofrece Banca Móvil, Banca por Internet, "
                "cajeros automáticos, agencias y Contact Center. La Banca Móvil y la Banca "
                "por Internet permiten realizar consultas y operaciones sin acudir a una "
                "agencia. La red de agencias tiene cobertura en los nueve departamentos de "
                "Bolivia.",
            ),
            (
                "Contact Center",
                "La Línea Móvil 788-12000 está publicada como disponible las 24 horas. La "
                "línea gratuita 800-17-0777 atiende de lunes a sábado, de 09:00 a 18:00. El "
                "canal de WhatsApp 6377-0777 atiende de lunes a domingo, de 07:00 a 23:00. "
                "Estos canales pueden orientar sobre productos, activar o bloquear "
                "tarjetas, restablecer accesos digitales y registrar o seguir reclamos.",
            ),
            (
                "Atención en agencias",
                "En agencias se pueden realizar transferencias, pagos de servicios, "
                "retiros, depósitos, giros y solicitudes de crédito.",
            ),
            (
                "Horarios de agencias",
                "La Sucursal Centro atiende de lunes a viernes de 08:30 a 19:00 y sábados "
                "de 09:00 a 13:00. En Santa Cruz de la Sierra, las agencias de la Av. "
                "Cristo Redentor y del Segundo Anillo atienden de lunes a viernes de 08:30 "
                "a 19:00 y sábados de 09:00 a 13:00; la agencia del Plan 3000 atiende de "
                "lunes a viernes de 08:30 a 18:00, sin atención sabatina. En La Paz, la "
                "agencia El Prado atiende de lunes a viernes de 08:30 a 18:30 y sábados de "
                "09:30 a 13:00. En Cochabamba, la agencia Av. Ballivián atiende de lunes a "
                "viernes de 08:30 a 18:30 y sábados de 09:00 a 13:00. Los horarios pueden "
                "variar en feriados y fechas especiales; se recomienda confirmar el "
                "horario de la agencia específica antes de una visita en esas fechas.",
            ),
            (
                "Orientación del kiosco",
                "Para consultas generales, el kiosco puede informar el canal apropiado y "
                "generar un ticket si la persona desea atención presencial. No debe "
                "prometer que un trámite podrá completarse por un canal determinado sin "
                "verificar la documentación y las condiciones vigentes del producto.",
            ),
        ],
        sources=[
            "https://www.bmsc.com.bo/tech",
            "https://www.bmsc.com.bo/help",
            "https://www.bmsc.com.bo/clientBenefitDetails?key=detalle-beneficio-cinco",
        ],
    )

    sections["cuentas-requisitos-bmsc"] = render_document(
        RAG_DIR / "02_cuentas_y_requisitos_bmsc.pdf",
        "Cuentas de ahorro y requisitos generales del BMSC",
        [
            (
                "Apertura y documentación",
                "Para abrir un producto de ahorro publicado por el BMSC se solicita: (1) "
                "documento de identidad vigente -- cédula de identidad boliviana, o "
                "cédula de extranjero o documento especial de identificación para "
                "personas extranjeras; (2) un comprobante de domicilio con antigüedad no "
                "mayor a 90 días cuando el titular no cuenta con historial previo en el "
                "banco; y (3), para personas extranjeras, respaldo de su actividad "
                "económica, como independientes o mediante boleta de pago como "
                "dependientes.",
            ),
            (
                "Súper Makro Cuenta",
                "La Súper Makro Cuenta puede abrirse en moneda nacional con monto mínimo "
                "publicado de Bs. 0. Permite participar en sorteos según el saldo y el "
                "reglamento vigente. Incluye acceso a Banca Móvil, Banca por Internet, "
                "cajeros y agencias.",
            ),
            (
                "Cuenta Rinde+",
                "La Cuenta de Ahorro Rinde+ publica un monto mínimo de apertura en agencia "
                "de Bs. 2.000 y apertura en línea sin monto mínimo. Las tasas, beneficios "
                "y montos pueden cambiar; antes de contratar se debe revisar el tarifario "
                "y reglamento vigente.",
            ),
            (
                "Cuenta de ahorro para menores de edad",
                "La Cuenta de Ahorro para Menores puede abrirse desde el nacimiento hasta "
                "los 17 años, siempre a nombre del menor y bajo la representación de un "
                "padre, madre o tutor legal. Se solicita: documento de identificación del "
                "menor -- cédula de identidad, o certificado de nacimiento cuando el "
                "documento no identifica a los padres; documento de identidad vigente del "
                "padre, madre o tutor que realiza la apertura; y, si existe tutor "
                "designado judicialmente, la resolución judicial correspondiente. El "
                "monto mínimo de apertura publicado es de Bs. 50. El padre, madre o tutor "
                "mantiene la administración de la cuenta hasta que el menor cumple 18 "
                "años, momento en el que la cuenta se convierte automáticamente en una "
                "cuenta de ahorro regular a su nombre.",
            ),
            (
                "Abono de rentas y pagos periódicos",
                "El BMSC recibe el abono de rentas, jubilaciones y otros pagos periódicos "
                "en cuentas de ahorro a nombre del propio beneficiario; no se acreditan "
                "rentas en cuentas de terceros. El trámite se inicia en cualquier agencia "
                "y requiere: (1) cédula de identidad vigente del beneficiario; (2) una "
                "cuenta de ahorro activa a su nombre en el banco, que puede abrirse en la "
                "misma visita; y (3) el documento que acredita la renta o el pago "
                "periódico, emitido por la entidad pagadora. Con esos documentos la "
                "agencia emite la constancia con el número de cuenta que el beneficiario "
                "presenta ante la entidad pagadora para registrar o cambiar la cuenta de "
                "abono. La acreditación queda habilitada a partir del siguiente ciclo de "
                "pago de la entidad pagadora; el banco no define ni adelanta esa fecha. "
                "Una vez acreditada, la renta puede cobrarse en cajeros, agencias y "
                "puntos habilitados, y consultarse por Banca Móvil y Banca por Internet. "
                "Quien no pueda acudir personalmente puede realizar el trámite mediante "
                "poder notarial vigente. Las personas adultas mayores acceden a atención "
                "preferencial en agencia para este trámite.",
            ),
            (
                "Límite de la orientación",
                "El kiosco brinda información general. No confirma apertura, tasas "
                "definitivas, saldos ni elegibilidad. Las condiciones contractuales deben "
                "ser verificadas por el banco y aceptadas por el cliente mediante los "
                "canales habilitados.",
            ),
        ],
        sources=[
            "https://www.bmsc.com.bo/accountDetails/?key=super-mackrocuenta-detalle",
            "https://www.bmsc.com.bo/accountDetails?key=rendimax-plus-detalle",
            "https://www.bmsc.com.bo/",
        ],
    )

    sections["creditos-bmsc"] = render_document(
        RAG_DIR / "03_creditos_bmsc.pdf",
        "Orientación sobre créditos del Banco Mercantil Santa Cruz",
        [
            (
                "Crédito de consumo",
                "El BMSC publica créditos de consumo con garantía de depósito a plazo "
                "fijo, garantía personal o a sola firma, sujetos a evaluación. La "
                "solicitud puede iniciarse en línea. La aprobación, tasa, plazo y "
                "garantía dependen del análisis crediticio y de las condiciones vigentes.",
            ),
            (
                "Requisitos generales",
                "Para solicitar un crédito de consumo se requiere: (1) ser mayor de 18 "
                "años y presentar documento de identidad vigente; (2) para ingresos "
                "fijos, las últimas tres boletas de pago, o para ingresos variables, las "
                "últimas seis; (3) alternativamente, extractos de AFP o de la cuenta "
                "donde se recibe el salario; (4) para personas independientes, respaldo "
                "de compras o ventas del último año; y (5), si existen otros préstamos "
                "vigentes, el plan de pagos correspondiente.",
            ),
            (
                "Tasas y condiciones",
                "La tasa de interés, el plazo y la garantía exigida se determinan "
                "mediante el análisis crediticio individual de cada solicitud y las "
                "condiciones vigentes publicadas por el banco en el momento de la "
                "evaluación; no existe una tasa única aplicable a todas las solicitudes. "
                "Un ejecutivo de créditos comunica la tasa y las condiciones exactas una "
                "vez completado el análisis. El kiosco no calcula ni informa una tasa "
                "definitiva.",
            ),
            (
                "Cuenta para desembolso",
                "El desembolso requiere una cuenta de ahorro o corriente en el banco. Si "
                "el solicitante no tiene una, puede recibir orientación para abrirla. El "
                "kiosco no debe declarar que una solicitud fue aprobada ni calcular una "
                "cuota definitiva.",
            ),
            (
                "Derecho a información",
                "El consumidor puede solicitar explicaciones claras sobre condiciones, "
                "cargos y cálculo de cuotas. Si un crédito es rechazado, la normativa "
                "reconoce el derecho a recibir por escrito los motivos. Los tiempos "
                "publicados no incluyen demoras causadas por documentación externa "
                "pendiente.",
            ),
        ],
        sources=[
            "https://www.bmsc.com.bo/loanDetails?key=prestamo-consumo-detalle",
            "https://asfi.gob.bo/pb/tiempos-maximos-atencion-creditos",
        ],
    )

    sections["banca-digital-seguridad"] = render_document(
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
                "Bloqueo por intentos fallidos",
                "El acceso a Banca Móvil y Banca por Internet se bloquea de forma "
                "preventiva después de varios intentos fallidos de ingreso consecutivos. El "
                "desbloqueo lo realiza el banco: se gestiona en agencia con cédula de "
                "identidad vigente del titular, o a través del Contact Center, que verifica "
                "la identidad antes de habilitar nuevamente el acceso. El personal del "
                "banco no solicita ni recibe la contraseña en ningún momento del trámite; "
                "el titular define una nueva clave por sí mismo al reingresar. Un acceso "
                "bloqueado no afecta los fondos ni las tarjetas asociadas a la cuenta.",
            ),
            (
                "Transferencias que no se completan",
                "Una transferencia puede no completarse por límites diarios o por operación "
                "configurados en el canal, por datos de cuenta destino incorrectos, por "
                "fondos insuficientes o por una interrupción del servicio. En todos esos "
                "casos la operación no se registra y el dinero permanece en la cuenta de "
                "origen. Cuando el intento se repite, corresponde revisarlo con un ejecutivo "
                "en agencia, con cédula de identidad vigente del titular y el detalle de "
                "fecha, hora y monto de los intentos; el ejecutivo verifica los límites "
                "configurados y el estado del canal. El titular no debe reintentar la "
                "operación de forma indefinida ni compartir sus credenciales con nadie para "
                "que la realice en su nombre.",
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
                "CI del cliente en el campo protegido y, cuando no exista orientación "
                "pública suficiente, se asignan a un ejecutivo de banca digital.",
            ),
        ],
        sources=[
            "https://www.bmsc.com.bo/tech/internetBank",
            "https://www.bmsc.com.bo/tech",
            "https://www.bmsc.com.bo/",
        ],
    )

    sections["tarjetas-bloqueo-fraude"] = render_document(
        RAG_DIR / "05_tarjetas_bloqueo_y_fraude.pdf",
        "Tarjetas, bloqueo y reporte de fraude",
        [
            (
                "Bloqueo de tarjeta",
                "La activación y el bloqueo de tarjetas están incluidos entre las "
                "gestiones del Contact Center. Una tarjeta perdida, robada o posiblemente "
                "comprometida debe tratarse como caso de prioridad alta y derivarse sin "
                "solicitar PIN ni claves.",
            ),
            (
                "Movimiento no reconocido",
                "Un movimiento no reconocido o indicio de fraude se clasifica como caso "
                "crítico. El kiosco registra un resumen enmascarado, evita mostrar "
                "información financiera y deriva al perfil de prevención de fraude. No "
                "confirma que el banco devolverá fondos ni determina responsabilidades.",
            ),
            (
                "Canales inmediatos",
                "Para soporte se puede usar la Línea Móvil 788-12000, publicada como "
                "disponible las 24 horas, o la línea gratuita 800-17-0777 en su horario. "
                "También se puede acudir a una agencia. No se debe esperar el turno del "
                "kiosco si existe riesgo inmediato.",
            ),
            (
                "Seguros asociados",
                "El banco publica seguros opcionales de protección para tarjetas con "
                "coberturas sujetas a certificado, condiciones, costo y requisitos. El "
                "hecho de reportar un evento no implica cobertura automática; la "
                "evaluación corresponde a la aseguradora.",
            ),
        ],
        sources=[
            "https://www.bmsc.com.bo/tech",
            "https://www.bmsc.com.bo/",
            "https://www.bmsc.com.bo/insuranceDetails?key=Tarjeta-Debito-detalle",
        ],
    )

    sections["reclamos-derechos"] = render_document(
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

    sections["manual-operativo-sucursal"] = render_document(
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
                "Atención preferencial",
                "Corresponde atención preferencial a personas adultas mayores, mujeres "
                "embarazadas, personas con discapacidad y personas con niñas o niños en "
                "brazos. No se exige acreditación documental para otorgarla: basta con que "
                "la persona lo solicite o con que el personal lo advierta. El kiosco marca "
                "la sesión como preferente y esa marca acompaña al caso hasta la ventanilla, "
                "de modo que el turno se antepone a los turnos ordinarios de la misma "
                "prioridad sin desplazar los casos críticos de seguridad. En agencia, la "
                "persona con atención preferencial no hace fila general y puede pedir "
                "acompañamiento del personal para completar formularios. Cuando la persona "
                "llega acompañada, el acompañante puede permanecer con ella, pero los datos "
                "y la firma corresponden siempre al titular.",
            ),
            (
                "Verificación protegida",
                "Las consultas generales pueden procesarse sin identificación. Las consultas "
                "personalizadas o sensibles solicitan el CI del cliente escrito en el campo "
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

    sections["preguntas-frecuentes-bmsc"] = render_document(
        RAG_DIR / "08_preguntas_frecuentes_bmsc.pdf",
        "Preguntas frecuentes de atención bancaria",
        [
            (
                "¿Qué necesito para abrir una cuenta?",
                "Como orientación general se solicita documento de identidad vigente -- "
                "cédula de identidad boliviana, o cédula de extranjero para personas "
                "extranjeras -- y, si no tienes historial previo en el banco, un "
                "comprobante de domicilio reciente. Los extranjeros pueden requerir "
                "respaldo de actividad económica, y los menores de edad, su documento de "
                "identificación junto con el documento del padre, madre o tutor. Los "
                "requisitos exactos dependen del producto elegido.",
            ),
            (
                "¿En qué horarios atienden las agencias?",
                "La Sucursal Centro atiende de lunes a viernes de 08:30 a 19:00 y sábados "
                "de 09:00 a 13:00. Otras agencias en Santa Cruz, La Paz y Cochabamba "
                "tienen horarios similares, con variaciones puntuales según el punto de "
                "atención. La Línea Móvil 788-12000 está disponible las 24 horas para "
                "consultas y gestiones que no requieren presencia física.",
            ),
            (
                "¿Dónde puedo bloquear una tarjeta?",
                "El Contact Center atiende activación y bloqueo de tarjetas. La Línea Móvil "
                "788-12000 está publicada con atención de 24 horas. Una pérdida o robo se "
                "deriva con prioridad alta sin pedir PIN ni contraseña.",
            ),
            (
                "¿Qué hago si no reconozco un movimiento?",
                "No comparta claves ni códigos. Use inmediatamente los canales oficiales o "
                "una agencia. El kiosco clasifica el caso como crítico, enmascara los "
                "datos y lo deriva a prevención de fraude.",
            ),
            (
                "¿Cómo recupero el acceso digital?",
                "El banco publica flujos de restablecimiento y ofrece orientación en "
                "Contact Center. El kiosco no recibe contraseñas, PIN, tokens ni códigos "
                "de verificación.",
            ),
            (
                "¿Cómo presento un reclamo?",
                "Presente primero el reclamo ante el banco y conserve el seguimiento. Si "
                "concluye la primera instancia y no está conforme, puede acudir a la "
                "Defensoría del Consumidor Financiero de ASFI.",
            ),
            (
                "¿Cómo hago para que me depositen mi renta o jubilación en el banco?",
                "El abono de rentas y jubilaciones se registra en una cuenta de ahorro a "
                "nombre del propio beneficiario. El trámite se hace en cualquier agencia con "
                "cédula de identidad vigente, una cuenta de ahorro activa a su nombre -- que "
                "puede abrirse en la misma visita -- y el documento de la entidad pagadora "
                "que acredita la renta. La agencia emite una constancia con el número de "
                "cuenta para presentarla ante la entidad pagadora, y la acreditación empieza "
                "en el siguiente ciclo de pago de esa entidad. Las personas adultas mayores "
                "tienen atención preferencial para este trámite.",
            ),
            (
                "¿Quién tiene atención preferencial y cómo se solicita?",
                "Tienen atención preferencial las personas adultas mayores, las mujeres "
                "embarazadas, las personas con discapacidad y quienes llegan con niñas o "
                "niños en brazos. No hace falta presentar ningún documento para pedirla: "
                "basta con indicarlo al llegar o al iniciar la sesión en el kiosco. El turno "
                "se antepone a los turnos ordinarios de la misma prioridad, y el personal de "
                "la agencia puede acompañar el llenado de formularios.",
            ),
            (
                "¿Por qué se bloqueó mi acceso a la banca digital?",
                "El acceso se bloquea de forma preventiva tras varios intentos fallidos de "
                "ingreso. El desbloqueo se gestiona en agencia con cédula de identidad "
                "vigente o a través del Contact Center, que verifica la identidad antes de "
                "habilitarlo. El banco nunca pide la contraseña para desbloquear; el titular "
                "define una nueva al reingresar. Los fondos y las tarjetas no se ven "
                "afectados.",
            ),
        ],
        sources=[
            "https://www.bmsc.com.bo/tech",
            "https://www.bmsc.com.bo/",
            "https://asfi.gob.bo/la/derechos-del-consumidor-financiero",
        ],
    )

    return sections


def skill_label(value: str) -> str:
    return value.replace("_", " ").title()


def render_executive_catalog(data: dict) -> None:
    catalog = data["catalog"]
    document_styles = styles()
    story = [
        Paragraph("Catálogo operativo de perfiles ejecutivos", document_styles["DocumentTitle"]),
        Paragraph(
            f"{catalog['bank']} · {catalog['branch']} · Vigente desde el {VIGENTE_DESDE}",
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


# Every RAG slug is now managed by this script (see `render_rag_documents`). Only the
# fields that differ from the OFFICIAL/90-day-review default need stating here;
# `update_manifest` fills verified_at/review_after/version/sha256/sections for all of them.
_INTERNAL_SLUGS = {"manual-operativo-sucursal"}
_REVIEW_WINDOW_DAYS = {"manual-operativo-sucursal": 365}


def update_manifest(rendered_sections: dict[str, list[str]]) -> None:
    manifest_path = RAG_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verified_at = datetime.strptime(VIGENTE_DESDE, "%d/%m/%Y").replace(tzinfo=UTC)
    manifest["generated_at"] = verified_at.isoformat()

    for specification in manifest["documents"]:
        slug = specification["slug"]
        if slug not in rendered_sections:
            continue
        window_days = _REVIEW_WINDOW_DAYS.get(slug, 90)
        specification["version"] = VERSION
        specification["sections"] = rendered_sections[slug]
        specification["verified_at"] = verified_at.isoformat()
        specification["review_after"] = (verified_at + timedelta(days=window_days)).isoformat()
        if slug in _INTERNAL_SLUGS:
            specification["source_type"] = "INTERNAL"
        pdf_path = RAG_DIR / specification["file_name"]
        specification["sha256"] = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    data = json.loads(SEED.read_text(encoding="utf-8"))
    rendered_sections = render_rag_documents()
    render_executive_catalog(data)
    update_manifest(rendered_sections)
    for pdf_path in sorted(RAG_DIR.glob("*.pdf")):
        print(pdf_path)
    print(OPERATIONS_DIR / "catalogo_perfiles_ejecutivos.pdf")


if __name__ == "__main__":
    main()
