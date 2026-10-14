from fastapi import APIRouter

from app.api.endpoints import admin_data, admin_openapi, auth, dashboard, redemption, customer_vip
from app.schemas.response import ApiResponse

api_router = APIRouter()
api_router.include_router(redemption.router)
api_router.include_router(customer_vip.router, prefix="/admin", tags=["customer-vip"])
api_router.include_router(auth.router, prefix="/admin/auth", tags=["admin-auth"])
api_router.include_router(dashboard.router, prefix="/admin/dashboard", tags=["admin-dashboard"])
api_router.include_router(admin_data.router, prefix="/admin", tags=["admin-data"])
api_router.include_router(admin_openapi.router)
api_router.add_api_route(
    "/site/config",
    admin_data.public_site_config,
    methods=["GET"],
    response_model=ApiResponse[dict],
    tags=["site-public"],
)
