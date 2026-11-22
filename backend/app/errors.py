"""
Standard error responses: `{"error": {"code", "message", "correlation_id"}}` (BUILD_PROMPT §5).

Messages are user-facing. Stack traces, SQL and file paths never reach the client (SEC-24).
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# Default user-facing message per status when the raising code gives none
DEFAULT_MESSAGES = {
    400: "The request could not be processed.",
    401: "Please log in to continue.",
    403: "You do not have permission to access this page.",
    404: "The requested resource was not found.",
    405: "This action is not allowed.",
    429: "Too many requests. Please wait a moment and try again.",
}


class AppError(StarletteHTTPException):
    """An HTTP error with a stable machine-readable code the frontend can act on."""

    def __init__(self, status_code: int, code: str, message: str, headers: dict[str, str] | None = None):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code


def error_body(code: str, message: str, correlation_id: str | None) -> dict:
    """Build the standard error body."""
    return {"error": {"code": code, "message": message, "correlation_id": correlation_id}}


def _correlation_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


def register_error_handlers(app: FastAPI) -> None:
    """Attach handlers that convert framework errors to the standard body."""

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else None
        if detail is None or detail == _status_phrase(exc.status_code):
            detail = DEFAULT_MESSAGES.get(exc.status_code, "The request could not be processed.")
        return JSONResponse(
            error_body(getattr(exc, "code", f"http_{exc.status_code}"), detail, _correlation_id(request)),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field names only: echoing submitted values back could reflect attacker input
        fields = sorted({".".join(str(p) for p in e["loc"][1:]) for e in exc.errors()})
        message = "Invalid request" + (f": check {', '.join(fields)}." if fields else ".")
        return JSONResponse(error_body("validation_error", message, _correlation_id(request)),
                            status_code=422)


def _status_phrase(status: int) -> str:
    from http import HTTPStatus

    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return ""
