"""统一 OpenAI-compatible 错误信封与异常处理。

信封格式：{"error": {"message": ..., "type": ..., "param": null, "code": ...}}
错误信息不得包含完整 request body 或任何密钥内容。
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("easymodelgate.errors")


def error_envelope(
    status_code: int,
    message: str,
    err_type: str = "invalid_request_error",
    code: str | None = None,
    param: str | None = None,
) -> dict:
    return {
        "error": {
            "message": message,
            "type": err_type,
            "param": param,
            "code": code,
        }
    }


class ApiError(Exception):
    """业务错误；由全局异常处理器转换为信封响应。"""

    def __init__(
        self,
        status_code: int,
        message: str,
        err_type: str = "invalid_request_error",
        code: str | None = None,
        param: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.err_type = err_type
        self.code = code
        self.param = param
        self.headers = headers or {}

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content=error_envelope(self.status_code, self.message, self.err_type, self.code, self.param),
            headers=self.headers,
        )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return exc.to_response()

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else None
        err_type = "invalid_request_error" if exc.status_code < 500 else "api_error"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(exc.status_code, str(exc.detail), err_type, code),
        )

    @app.exception_handler(Exception)
    async def _handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常（不输出请求体）")
        return JSONResponse(
            status_code=500,
            content=error_envelope(500, "Internal server error", "api_error", "internal_error"),
        )
