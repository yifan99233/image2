from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppException(Exception):
    def __init__(self, *, code: int, message: str, status_code: int = 400, data: object | None = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.data = data


def response_body(code: int, message: str, data: object | None = None) -> dict:
    return {"code": code, "message": message, "data": data}


async def app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=response_body(exc.code, exc.message, exc.data))


async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = str(exc.detail) if exc.detail else "请求失败"
    code = exc.status_code * 100
    return JSONResponse(status_code=exc.status_code, content=response_body(code, message))


async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content=response_body(42200, "请求参数错误", exc.errors()))

