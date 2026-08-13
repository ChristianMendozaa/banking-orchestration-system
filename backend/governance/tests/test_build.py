"""Verifies the crew's wiring (agents, tasks, MCP config) compiles correctly.

Does not call kickoff() -- that would need a real LLM API key and real API cost. This is
the same "verify wiring, not live behavior" split used for the MCP server in Phase 1.
"""

from crewai import Process

from crew.build import build_crew
from crew.schemas import ComplianceReview, DocumentAnalysis, RetrievalQAReport


def _build():
    return build_crew(
        llm="gpt-4o-mini",
        mcp_url="http://mcp.test/mcp",
        mcp_token="fake-token-for-wiring-check",
    )


def test_crew_has_three_agents_and_tasks() -> None:
    crew = _build()
    assert [agent.role for agent in crew.agents] == [
        "Analista Documental",
        "Revisor de Cumplimiento",
        "QA de Recuperacion",
    ]
    assert len(crew.tasks) == 3
    assert crew.process == Process.sequential


def test_tasks_declare_the_expected_structured_outputs() -> None:
    crew = _build()
    analyze_task, compliance_task, retrieval_task = crew.tasks
    assert analyze_task.output_pydantic is DocumentAnalysis
    assert compliance_task.output_pydantic is ComplianceReview
    assert retrieval_task.output_pydantic is RetrievalQAReport


def test_compliance_review_is_independent_of_the_analyst() -> None:
    """Deliberate design choice: compliance judgment should not be anchored by the
    Analyst's framing. See build.py's module docstring."""
    crew = _build()
    _, compliance_task, _ = crew.tasks
    assert compliance_task.context == []


def test_retrieval_qa_agent_is_wired_to_the_mcp_server() -> None:
    crew = _build()
    retrieval_agent = crew.agents[2]
    assert retrieval_agent.mcps is not None
    assert retrieval_agent.mcps[0].url == "http://mcp.test/mcp"
    assert retrieval_agent.mcps[0].headers == {
        "Authorization": "Bearer fake-token-for-wiring-check"
    }


def test_retrieval_task_receives_analyst_context() -> None:
    crew = _build()
    analyze_task, _, retrieval_task = crew.tasks
    assert retrieval_task.context == [analyze_task]
