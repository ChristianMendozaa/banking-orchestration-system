"""Builds the three-agent governance crew.

Sequential process (`Process.sequential`), three roles:
  1. Document Analyst -- proposes categories, section structure, a review-after date.
  2. Compliance Reviewer -- runs independently of the Analyst's output (deliberately not
     given it as context) so its judgment isn't anchored by the Analyst's framing; can veto.
  3. Retrieval QA -- given the Analyst's suggested categories, generates candidate customer
     questions and checks them against the *live* knowledge base via the MCP server's
     `search_knowledge` tool (CrewAI's native `mcps=` integration, not a custom wrapper),
     reporting which fail to retrieve groundedly.

Nothing here is auto-applied: `GovernanceProposal.from_task_outputs()` only combines the
three outputs into a recommendation for a manager to review.
"""

from crewai import Agent, Crew, Process, Task
from crewai.mcp.config import MCPServerHTTP

from crew.schemas import CATEGORIES, ComplianceReview, DocumentAnalysis, RetrievalQAReport

DOCUMENT_TEMPLATE = "--- Documento ({title}) ---\n{document_text}"


def build_crew(*, llm: str, mcp_url: str, mcp_token: str) -> Crew:
    analyst = Agent(
        role="Analista Documental",
        goal="Proponer categorias, estructura de secciones y fecha de revision para un "
        "documento bancario de cara al cliente.",
        backstory="Trabajas en el equipo de contenido de un banco boliviano. Conoces las "
        "cinco categorias de atencion: " + ", ".join(CATEGORIES) + ". Tu trabajo es leer un "
        "documento y clasificarlo con precision, sin inventar contenido que no este presente.",
        llm=llm,
        verbose=True,
    )
    compliance_reviewer = Agent(
        role="Revisor de Cumplimiento",
        goal="Detectar contenido no apto para respuestas automaticas a clientes: "
        "procedimientos internos, cifras desactualizadas, datos personales, o afirmaciones "
        "no verificables.",
        backstory="Eres el control de cumplimiento antes de que un documento pueda "
        "activarse para generar respuestas automaticas. Tu revision es independiente: no "
        "conoces el analisis de otros equipos, solo el documento original.",
        llm=llm,
        verbose=True,
    )
    retrieval_qa = Agent(
        role="QA de Recuperacion",
        goal="Generar preguntas realistas que un cliente haria sobre este documento y "
        "verificar, usando la herramienta de busqueda documental, si el sistema real "
        "encuentra evidencia fundamentada para responderlas.",
        backstory="Pruebas el sistema de respuesta automatica antes de que un documento "
        "se active, simulando preguntas reales de clientes.",
        llm=llm,
        mcps=[MCPServerHTTP(url=mcp_url, headers={"Authorization": f"Bearer {mcp_token}"})],
        verbose=True,
    )

    analyze_task = Task(
        description=(
            "Lee el siguiente documento y produce category_suggestions (subconjunto de "
            f"{CATEGORIES}), section_suggestions (encabezados reales presentes en el "
            "documento), review_after_suggestion (fecha ISO-8601 si el contenido implica "
            "una, si no null), y un resumen breve.\n\n" + DOCUMENT_TEMPLATE
        ),
        expected_output="Un DocumentAnalysis valido.",
        agent=analyst,
        output_pydantic=DocumentAnalysis,
    )
    compliance_task = Task(
        description=(
            "Revisa el siguiente documento de forma independiente -- no has visto ningun "
            "otro analisis. Determina si contiene procedimientos internos, cifras que "
            "podrian estar desactualizadas, cualquier dato que parezca informacion personal "
            "de un cliente, o afirmaciones que el documento no respalda. Si encuentras "
            "algo asi, veto debe ser true.\n\n" + DOCUMENT_TEMPLATE
        ),
        expected_output="Un ComplianceReview valido.",
        agent=compliance_reviewer,
        output_pydantic=ComplianceReview,
        context=[],
    )
    retrieval_task = Task(
        description=(
            "Usando las categorias sugeridas por el Analista Documental, genera de 2 a 4 "
            "preguntas realistas que un cliente haria sobre este documento. Para cada una, "
            "usa la herramienta search_knowledge (categoria = una de las sugeridas) y "
            "registra si devolvio evidencia que realmente responde la pregunta."
        ),
        expected_output="Un RetrievalQAReport valido con 2 a 4 resultados.",
        agent=retrieval_qa,
        output_pydantic=RetrievalQAReport,
        context=[analyze_task],
    )

    return Crew(
        agents=[analyst, compliance_reviewer, retrieval_qa],
        tasks=[analyze_task, compliance_task, retrieval_task],
        process=Process.sequential,
        verbose=True,
    )
