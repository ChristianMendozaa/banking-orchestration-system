from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None
    trace_id: str | None = None


class AppError(Exception):
    def __init__(
        self, code: str, message: str, status_code: int = 400, details: Any | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        body = ErrorBody(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            trace_id=getattr(request.state, "trace_id", None),
        )
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        body = ErrorBody(
            code="VALIDATION_ERROR",
            message="La solicitud contiene datos invalidos",
            details=[
                {key: value for key, value in error.items() if key not in {"input", "ctx"}}
                for error in exc.errors()
            ],
            trace_id=getattr(request.state, "trace_id", None),
        )
        return JSONResponse(status_code=422, content=body.model_dump())
