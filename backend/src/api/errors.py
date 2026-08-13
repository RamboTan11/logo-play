"""Exception handlers that keep HTTP failures in the PyCore response envelope."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from pycore.api.responses import error_response


class ApplicationHTTPException(HTTPException):
    """An HTTP failure carrying a stable public error code and optional cookie cleanup."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        error_code: str,
        *,
        clear_cookie: str | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code
        self.clear_cookie = clear_cookie


def _json_error(message: str, error_code: str, status_code: int) -> JSONResponse:
    """Convert PyCore's error DTO to a FastAPI JSON response."""

    body, http_status = error_response(
        message,
        error_code=error_code,
        status_code=status_code,
    )
    return JSONResponse(status_code=http_status, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    """Register standard response handlers once for an application instance."""

    @app.exception_handler(HTTPException)
    async def handle_http_exception(_: Request, exc: HTTPException) -> JSONResponse:
        error_code = getattr(exc, "error_code", None) or {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
        }.get(exc.status_code, "request_failed")
        response = _json_error(str(exc.detail), error_code, exc.status_code)
        clear_cookie = getattr(exc, "clear_cookie", None)
        if clear_cookie:
            response.delete_cookie(clear_cookie, path="/api/v1", samesite="lax")
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details: list[str] = []
        for error in exc.errors():
            location = error.get("loc", ())
            field = str(location[-1]) if location else "request"
            reason = str(error.get("msg") or "invalid value")
            details.append(f"{field}: {reason}")
        return _json_error("请求参数校验失败：" + "；".join(details), "validation_error", 422)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, __: Exception) -> JSONResponse:
        return _json_error("Internal server error", "internal_error", 500)
