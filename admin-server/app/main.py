from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import AppException, app_exception_handler, http_exception_handler, validation_exception_handler
from app.core.logging import configure_logging
from app.schemas.response import ApiResponse


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    @app.get("/healthz", response_model=ApiResponse[dict])
    async def healthz() -> ApiResponse[dict]:
        return ApiResponse.ok({"status": "ok", "service": settings.app_name})

    return app


app = create_app()
