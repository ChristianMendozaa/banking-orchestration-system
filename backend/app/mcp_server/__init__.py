"""MCP server exposing read-only domain tools to AI clients.

This package is deliberately separate from the FastAPI application in `app.main`.
It serves authenticated external MCP clients and must never be consumed by the kiosk,
executive, or gerencial frontends -- those keep calling the typed REST API in `app.api`
directly. The LangGraph kiosk flow and AutoGen evaluation harness also use that REST
contract rather than routing through this server.

The server never exposes kiosk-session mutation or identifier reveal; every tool here
is a read/reporting operation backed by the same repositories the REST API uses.
"""
