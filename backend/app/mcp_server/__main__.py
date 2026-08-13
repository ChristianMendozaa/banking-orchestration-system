"""Entrypoint: `python -m app.mcp_server`.

Follows the same "shared image, dedicated command" convention already used for
`knowledge-worker` (see `app/knowledge/worker.py` and `docker-compose.yml`) rather than
introducing a second Docker image for Phase 1.
"""

import os

import uvicorn

from app.mcp_server.server import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 - bound inside the compose network, not exposed publicly
        port=int(os.environ.get("MCP_SERVER_PORT", "8100")),
    )
