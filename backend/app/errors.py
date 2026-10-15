"""ApiError helpers: every error body is { "error": { "code", "message" } }."""
from __future__ import annotations

import logging
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("rolo.api")


class ApiException(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def not_found() -> ApiException:
    return ApiException(404, "not_found", "Contact not found.")


def _body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def _validation_message(exc: RequestValidationError) -> str:
    """Always "<field>: <problem>" so the UI can place it under the right input."""
    errs = exc.errors()
    if not errs:
        return "body: invalid request"
    e = errs[0]
    loc = [str(p) for p in e.get("loc", ()) if p not in ("body", "query", "path")]
    field = ".".join(loc) or "body"
    etype = e.get("type")
    if etype == "json_invalid":
        return "body: is not valid JSON"
    if etype == "missing":
        return f"{field}: is required"
    msg = str(e.get("msg", "invalid value")).removeprefix("Value error, ")
    if not loc and etype == "value_error" and re.match(r"^[a-z_]+: ", msg):
        return msg  # model-level rule that already names its field
    if field == "body" and etype in ("model_attributes_type", "dict_type"):
        return "body: must be a JSON object"
    return f"{field}: {msg[:1].lower() + msg[1:]}"


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiException)
    async def _api(_: Request, exc: ApiException):
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, exc: RequestValidationError):
        return JSONResponse(_body("validation_error", _validation_message(exc)), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        msg = "Not found." if exc.status_code == 404 else str(exc.detail)
        return JSONResponse(_body(code, msg), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _any(_: Request, exc: Exception):
        log.exception("Unhandled error")
        return JSONResponse(_body("internal_error", "Something went wrong. Please try again."), status_code=500)
