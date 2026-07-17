from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.domain.enums import Category, KnowledgeSourceType

VERIFIED_AT = datetime(2026, 7, 16, tzinfo=UTC)


@dataclass(frozen=True)
class CorpusDocument:
    slug: str
    file_name: str
    title: str
    version: str
    source_type: KnowledgeSourceType
    categories: tuple[Category, ...]
    source_urls: tuple[str, ...]
    sections: tuple[tuple[str, str], ...]
    review_days: int = 90

    @property
    def verified_at(self) -> datetime:
        return VERIFIED_AT

    @property
    def review_after(self) -> datetime:
        return VERIFIED_AT + timedelta(days=self.review_days)


CORPUS_DOCUMENTS: tuple[CorpusDocument, ...] = (
    CorpusDocument(
        slug="canales-atencion-bmsc",
        file_name="01_canales_y_atencion_bmsc.pdf",
        title="Canales y atención del Banco Mercantil Santa Cruz",
        version="2026.07",
        source_type=KnowledgeSourceType.OFFICIAL,
        categories=(Category.CONSULTA_GENERAL,),
        source_urls=(
            "https://www.bmsc.com.bo/tech",
            "https://www.bmsc.com.bo/help",
            "https://www.bmsc.com.bo/clientBenefitDetails?key=detalle-beneficio-cinco",
        ),
        sections=(
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
                "La Línea Móvil 788-12000 está publicada como disponible las 24 horas. La línea "
                "gratuita 800-17-0777 atiende de lunes a sábado, de 09:00 a 18:00. El canal de "
                "WhatsApp 6377-0777 atiende de lunes a domingo, de 07:00 a 23:00. Estos canales "
                "pueden orientar sobre productos, activar o bloquear tarjetas, restablecer accesos "
                "digitales y registrar o seguir reclamos.",
            ),
            (
                "Atención en agencias",
                "En agencias se pueden realizar transferencias, pagos de servicios, retiros, "
                "depósitos, giros y solicitudes de crédito. Algunos puntos de Santa Cruz, La Paz "
                "y Cochabamba publican atención continua de lunes a sábado entre 09:00 y 20:00; "
                "el horario debe confirmarse para la agencia específica antes de la visita.",
            ),
            (
                "Orientación del kiosco",
                "Para consultas generales, el kiosco puede informar el canal apropiado y generar "
                "un ticket si la persona desea atención presencial. No debe prometer que un "
                "trámite "
                "podrá completarse por un canal determinado sin verificar la documentación y las "
                "condiciones vigentes del producto.",
            ),
        ),
    ),
    CorpusDocument(
        slug="cuentas-requisitos-bmsc",
        file_name="02_cuentas_y_requisitos_bmsc.pdf",
        title="Cuentas de ahorro y requisitos generales del BMSC",
        version="2026.07",
        source_type=KnowledgeSourceType.OFFICIAL,
        categories=(Category.CONSULTA_GENERAL,),
        source_urls=(
            "https://www.bmsc.com.bo/accountDetails/?key=super-mackrocuenta-detalle",
            "https://www.bmsc.com.bo/accountDetails?key=rendimax-plus-detalle",
            "https://www.bmsc.com.bo/",
        ),
        sections=(
            (
                "Apertura y documentación",
                "Para productos de ahorro publicados por el BMSC se solicita documentación de "
                "identidad vigente. Se acepta cédula de identidad boliviana y, para personas "
                "extranjeras, cédula de extranjero o documento especial de identificación. Las "
                "personas extranjeras deben respaldar su actividad económica como independientes "
                "o mediante boleta de pago como dependientes.",
            ),
            (
                "Súper Makro Cuenta",
                "La Súper Makro Cuenta puede abrirse en moneda nacional con monto mínimo publicado "
                "de Bs. 0. Permite participar en sorteos según el saldo y el reglamento vigente. "
                "Incluye acceso a Banca Móvil, Banca por Internet, cajeros y agencias.",
            ),
            (
                "Cuenta Rinde+",
                "La Cuenta de Ahorro Rinde+ publica un monto mínimo de apertura en agencia de "
                "Bs. 2.000 y apertura en línea sin monto mínimo. Las tasas, beneficios y montos "
                "pueden cambiar; antes de contratar se debe revisar el tarifario y reglamento "
                "vigente.",
            ),
            (
                "Menores de edad",
                "Para menores se solicita documento de identificación, certificado de nacimiento "
                "cuando el documento no identifica a los padres y documentos del padre, madre o "
                "tutor. Si existe tutor, puede requerirse la resolución judicial correspondiente.",
            ),
            (
                "Límite de la orientación",
                "El kiosco brinda información general. No confirma apertura, tasas definitivas, "
                "saldos ni elegibilidad. Las condiciones contractuales deben ser verificadas por "
                "el banco y aceptadas por el cliente mediante los canales habilitados.",
            ),
        ),
    ),
    CorpusDocument(
        slug="creditos-bmsc",
        file_name="03_creditos_bmsc.pdf",
        title="Orientación sobre créditos del Banco Mercantil Santa Cruz",
        version="2026.07",
        source_type=KnowledgeSourceType.OFFICIAL,
        categories=(Category.SOLICITUD_CREDITO, Category.CONSULTA_GENERAL),
        source_urls=(
            "https://www.bmsc.com.bo/loanDetails?key=prestamo-consumo-detalle",
            "https://asfi.gob.bo/pb/tiempos-maximos-atencion-creditos",
        ),
        sections=(
            (
                "Crédito de consumo",
                "El BMSC publica créditos de consumo con garantía de depósito a plazo fijo, "
                "garantía personal o a sola firma, sujetos a evaluación. La solicitud puede "
                "iniciarse en línea. La aprobación, tasa, plazo y garantía dependen del análisis "
                "crediticio y de las condiciones vigentes.",
            ),
            (
                "Requisitos generales",
                "Se requiere ser mayor de 18 años y presentar documento de identidad vigente. "
                "Para ingresos fijos se publican las últimas tres boletas de pago; para ingresos "
                "variables, las últimas seis. También pueden aceptarse extractos de AFP o de la "
                "cuenta donde se recibe el salario. Independientes presentan respaldo de compras "
                "o ventas del último año. Si existen otros préstamos, puede solicitarse su plan "
                "de pagos.",
            ),
            (
                "Cuenta para desembolso",
                "El desembolso requiere una cuenta de ahorro o corriente en el banco. Si el "
                "solicitante no tiene una, puede recibir orientación para abrirla. El kiosco no "
                "debe declarar que una solicitud fue aprobada ni calcular una cuota definitiva.",
            ),
            (
                "Derecho a información",
                "El consumidor puede solicitar explicaciones claras sobre condiciones, cargos y "
                "cálculo de cuotas. Si un crédito es rechazado, la normativa reconoce el derecho "
                "a recibir por escrito los motivos. Los tiempos publicados no incluyen demoras "
                "causadas por documentación externa pendiente.",
            ),
        ),
    ),
    CorpusDocument(
        slug="banca-digital-seguridad",
        file_name="04_banca_digital_y_seguridad.pdf",
        title="Banca digital y seguridad del BMSC",
        version="2026.07",
        source_type=KnowledgeSourceType.OFFICIAL,
        categories=(Category.BANCA_DIGITAL, Category.CONSULTA_GENERAL),
        source_urls=(
            "https://www.bmsc.com.bo/tech/internetBank",
            "https://www.bmsc.com.bo/tech",
            "https://www.bmsc.com.bo/",
        ),
        sections=(
            (
                "Servicios digitales",
                "La Banca por Internet y la Banca Móvil permiten consultas y transacciones desde "
                "canales digitales. Entre las funciones publicadas se encuentran transferencias, "
                "pagos y configuración de límites para tarjetas. Los límites existen como medida "
                "de seguridad y pueden gestionarse mediante los canales habilitados.",
            ),
            (
                "Recuperación de acceso",
                "El banco publica tutoriales para activación, primer ingreso y restablecimiento de "
                "contraseña. El Contact Center también orienta sobre habilitación, desbloqueo y "
                "restablecimiento de contraseñas de Banca Móvil y Banca por Internet.",
            ),
            (
                "Protección de credenciales",
                "El BMSC informa que nunca solicita usuarios, contraseñas, claves de tarjeta ni "
                "validación de cuenta mediante correos, redes sociales o enlaces externos. Si una "
                "persona recibe una solicitud de ese tipo, no debe abrir el enlace ni entregar "
                "datos; debe reportarla en una agencia o en la Central de Consultas.",
            ),
            (
                "Atención del kiosco",
                "El kiosco jamás solicita PIN, contraseña, código de verificación, token ni número "
                "completo de tarjeta. Los problemas de acceso propios requieren identificación "
                "demostrativa y, cuando no exista orientación pública suficiente, derivación a "
                "un ejecutivo.",
            ),
        ),
    ),
    CorpusDocument(
        slug="tarjetas-bloqueo-fraude",
        file_name="05_tarjetas_bloqueo_y_fraude.pdf",
        title="Tarjetas, bloqueo y reporte de fraude",
        version="2026.07",
        source_type=KnowledgeSourceType.HYBRID,
        categories=(Category.BLOQUEO_TARJETA, Category.REPORTE_FRAUDE),
        source_urls=(
            "https://www.bmsc.com.bo/tech",
            "https://www.bmsc.com.bo/",
            "https://www.bmsc.com.bo/insuranceDetails?key=Tarjeta-Debito-detalle",
        ),
        sections=(
            (
                "Bloqueo de tarjeta",
                "La activación y el bloqueo de tarjetas están incluidos entre las gestiones del "
                "Contact Center. Una tarjeta perdida, robada o posiblemente comprometida debe "
                "tratarse como caso de prioridad alta y derivarse sin solicitar PIN ni claves.",
            ),
            (
                "Movimiento no reconocido",
                "Un movimiento no reconocido o indicio de fraude se clasifica como caso crítico. "
                "El kiosco registra un resumen enmascarado, evita mostrar información financiera "
                "y deriva al perfil de prevención de fraude. No confirma que el banco devolverá "
                "fondos ni determina responsabilidades.",
            ),
            (
                "Canales inmediatos",
                "Para soporte se puede usar la Línea Móvil 788-12000, publicada como disponible "
                "las 24 horas, o la línea gratuita 800-17-0777 en su horario. También se puede "
                "acudir a una agencia. No se debe esperar el turno del kiosco si existe riesgo "
                "inmediato.",
            ),
            (
                "Seguros asociados",
                "El banco publica seguros opcionales de protección para tarjetas con coberturas "
                "sujetas a certificado, condiciones, costo y requisitos. El hecho de reportar un "
                "evento no implica cobertura automática; la evaluación corresponde a la "
                "aseguradora.",
            ),
        ),
    ),
    CorpusDocument(
        slug="reclamos-derechos",
        file_name="06_reclamos_y_derechos.pdf",
        title="Reclamos y derechos del consumidor financiero",
        version="2026.07",
        source_type=KnowledgeSourceType.REGULATORY,
        categories=(Category.CONSULTA_GENERAL,),
        source_urls=(
            "https://www.bmsc.com.bo/help",
            "https://asfi.gob.bo/la/derechos-del-consumidor-financiero",
            "https://www.asfi.gob.bo/sites/default/files/2025-09/Ley%20N%C2%B0%20393%20de%20Servicios%20Financieros.pdf",
        ),
        sections=(
            (
                "Derechos principales",
                "La Ley 393 reconoce acceso equitativo, servicios adecuados, información clara y "
                "oportuna, trato digno, canales eficientes de reclamo, confidencialidad y derecho "
                "a efectuar consultas, peticiones y solicitudes.",
            ),
            (
                "Primera instancia",
                "El reclamo se presenta inicialmente ante la entidad financiera mediante su Punto "
                "de Reclamo o canales publicados. El BMSC incluye registro y seguimiento de "
                "reclamos entre los servicios del Contact Center. Se debe conservar el número o "
                "constancia de seguimiento.",
            ),
            (
                "Segunda instancia",
                "Si la primera instancia concluye y el consumidor no está conforme, puede acudir a "
                "la Defensoría del Consumidor Financiero de ASFI. ASFI publica la línea gratuita "
                "800-103-103 para orientación. El kiosco no resuelve el fondo del reclamo.",
            ),
            (
                "Información y confidencialidad",
                "La entidad debe responder de forma comprensible y oportuna y resguardar la "
                "información del consumidor. Las métricas gerenciales del prototipo no exponen "
                "identificadores ni detalles financieros de casos individuales.",
            ),
        ),
    ),
    CorpusDocument(
        slug="manual-operativo-sucursal",
        file_name="07_manual_operativo_sucursal.pdf",
        title="Manual operativo de atención presencial",
        version="2026.07",
        source_type=KnowledgeSourceType.SIMULATED,
        categories=tuple(Category),
        source_urls=(),
        review_days=365,
        sections=(
            (
                "Clasificación de ventanillas",
                "Ventanilla 1 atiende prevención de fraude; Ventanilla 3, tarjetas y seguridad; "
                "Ventanilla 4, créditos y atención general; Ventanilla 5, banca digital. Si el "
                "especialista está ocupado, el caso queda pendiente sin reasignación a un perfil "
                "incompatible.",
            ),
            (
                "Prioridad",
                "Fraude y movimientos no reconocidos tienen prioridad crítica. Bloqueo por pérdida "
                "o robo tiene prioridad alta. Banca digital y crédito tienen prioridad media. "
                "Consultas generales tienen prioridad baja. La atención preferente eleva un nivel "
                "los casos bajos o medios, sin superar casos críticos de seguridad.",
            ),
            (
                "Identificación demostrativa",
                "Consultas generales se procesan de forma anónima. Consultas personalizadas o "
                "sensibles solicitan un identificador ficticio. La identificación no equivale a "
                "autenticación bancaria y nunca habilita saldos, movimientos ni operaciones.",
            ),
            (
                "Trazabilidad",
                "Cada atención genera ticket, categoría, prioridad, ruta, estado y eventos. La "
                "transcripción original no se guarda. El resumen debe estar enmascarado antes de "
                "ser visible para ejecutivos o gerencia.",
            ),
        ),
    ),
    CorpusDocument(
        slug="preguntas-frecuentes-bmsc",
        file_name="08_preguntas_frecuentes_bmsc.pdf",
        title="Preguntas frecuentes de atención bancaria",
        version="2026.07",
        source_type=KnowledgeSourceType.HYBRID,
        categories=tuple(Category),
        source_urls=(
            "https://www.bmsc.com.bo/tech",
            "https://www.bmsc.com.bo/",
            "https://asfi.gob.bo/la/derechos-del-consumidor-financiero",
        ),
        sections=(
            (
                "¿Qué necesito para abrir una cuenta?",
                "Como orientación general, documento de identidad vigente. Extranjeros pueden "
                "requerir respaldo de actividad económica y los menores documentación de sus "
                "padres o tutor. Los requisitos exactos dependen del producto.",
            ),
            (
                "¿Dónde puedo bloquear una tarjeta?",
                "El Contact Center atiende activación y bloqueo de tarjetas. La Línea Móvil "
                "788-12000 está publicada con atención de 24 horas. Una pérdida o robo se deriva "
                "con prioridad alta sin pedir PIN ni contraseña.",
            ),
            (
                "¿Qué hago si no reconozco un movimiento?",
                "No comparta claves ni códigos. Use inmediatamente los canales oficiales o una "
                "agencia. El kiosco clasifica el caso como crítico, enmascara los datos y lo "
                "deriva "
                "a prevención de fraude.",
            ),
            (
                "¿Cómo recupero el acceso digital?",
                "El banco publica flujos de restablecimiento y ofrece orientación en Contact "
                "Center. "
                "El kiosco no recibe contraseñas, PIN, tokens ni códigos de verificación.",
            ),
            (
                "¿Cómo presento un reclamo?",
                "Presente primero el reclamo ante el banco y conserve el seguimiento. Si concluye "
                "la primera instancia y no está conforme, puede acudir a la Defensoría del "
                "Consumidor Financiero de ASFI.",
            ),
        ),
    ),
)


CORPUS_BY_FILENAME = {document.file_name: document for document in CORPUS_DOCUMENTS}
