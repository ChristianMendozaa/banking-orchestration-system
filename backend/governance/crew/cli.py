"""CLI entrypoint: `python -m crew <document_id>`.

Reads connection details and manager credentials from environment variables -- there is
no dedicated "service account" baked into seed data or CI. A manager runs this with their
own credentials (or a second manager account they create for the purpose), exactly the
same way they'd use any other authenticated staff tool.

Required env vars:
  GOVERNANCE_API_BASE_URL   e.g. http://localhost:8000
  GOVERNANCE_MCP_URL        e.g. http://localhost:8100/mcp
  GOVERNANCE_MANAGER_EMAIL
  GOVERNANCE_MANAGER_PASSWORD
Optional:
  GOVERNANCE_LLM            default: gpt-4o-mini
"""

import os
import sys

import structlog

from crew.build import build_crew
from crew.client import BackendClient
from crew.pdf import extract_text
from crew.schemas import ComplianceReview, DocumentAnalysis, GovernanceProposal, RetrievalQAReport

logger = structlog.get_logger()

_REQUIRED_ENV = (
    "GOVERNANCE_API_BASE_URL",
    "GOVERNANCE_MCP_URL",
    "GOVERNANCE_MANAGER_EMAIL",
    "GOVERNANCE_MANAGER_PASSWORD",
)


def _require_env() -> dict[str, str]:
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Faltan variables de entorno: {', '.join(missing)}")
    return {name: os.environ[name] for name in _REQUIRED_ENV}


def review_document(document_id: str) -> dict:
    env = _require_env()
    llm = os.environ.get("GOVERNANCE_LLM", "gpt-4o-mini")

    with BackendClient(env["GOVERNANCE_API_BASE_URL"]) as client:
        client.login(env["GOVERNANCE_MANAGER_EMAIL"], env["GOVERNANCE_MANAGER_PASSWORD"])
        logger.info("governance_review_started", document_id=document_id)

        pdf_bytes = client.download_document(document_id)
        document_text = extract_text(pdf_bytes)
        if not document_text.strip():
            raise SystemExit(f"El documento {document_id} no produjo texto extraible")

        crew = build_crew(
            llm=llm,
            mcp_url=env["GOVERNANCE_MCP_URL"],
            mcp_token=client.access_token,
        )
        result = crew.kickoff(inputs={"title": document_id, "document_text": document_text})

        analysis, compliance, retrieval_qa = (output.pydantic for output in result.tasks_output)
        assert isinstance(analysis, DocumentAnalysis)
        assert isinstance(compliance, ComplianceReview)
        assert isinstance(retrieval_qa, RetrievalQAReport)

        proposal = GovernanceProposal.from_task_outputs(analysis, compliance, retrieval_qa)
        submitted = client.submit_governance_proposal(document_id, proposal.to_payload())
        logger.info(
            "governance_review_submitted",
            document_id=document_id,
            proposal_id=submitted["id"],
            compliance_veto=proposal.compliance_veto,
        )
        return submitted


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python -m crew <document_id>")
    submitted = review_document(sys.argv[1])
    print(submitted)


if __name__ == "__main__":
    main()
