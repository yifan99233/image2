from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

VALIDATION_ERROR_MESSAGE = "请求参数无效"


class BusinessError(Exception):
    def __init__(self, message: str, code: int = 40000, status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code


def validation_error_response(exc: RequestValidationError) -> JSONResponse:
    errors = list(exc.errors())
    message = VALIDATION_ERROR_MESSAGE
    if errors:
        first_error = errors[0]
        context = first_error.get("ctx")
        context_error = context.get("error") if isinstance(context, dict) else None
        if context_error:
            message = str(context_error)
        elif first_error.get("msg"):
            message = str(first_error["msg"]).removeprefix("Value error, ")

    return JSONResponse(
        status_code=422,
        content=jsonable_encoder(
            {"code": 422, "message": message, "data": errors},
            custom_encoder={ValueError: str},
        ),
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(IntegrityError)
    async def expired_reference_handler(_: Request, exc: IntegrityError) -> JSONResponse:
        if getattr(exc.orig, "sqlstate", None) == "23514" and "Image has expired" in str(exc.orig):
            return JSONResponse(status_code=410, content={"code": 41040, "message": "图片已过期", "data": None})
        # Preserve the existing error/logging behavior for unrelated failures.
        raise exc

    @app.exception_handler(BusinessError)
    async def business_error_handler(_: Request, exc: BusinessError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "data": None},
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code, "message": str(exc.detail), "data": None},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return validation_error_response(exc)
