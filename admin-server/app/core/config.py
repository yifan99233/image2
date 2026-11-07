from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "image2-admin-server"
    app_env: str = "local"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/image2"
    redis_url: str = "redis://127.0.0.1:6379/0"
    cors_origins: str = (
        "http://localhost:5173,http://localhost:5174,http://localhost:5175,"
        "http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:5175"
    )

    admin_jwt_secret_key: str = Field(default="dev-admin-secret-change-me", min_length=16)
    admin_jwt_algorithm: str = "HS256"
    admin_access_token_expire_minutes: int = 60 * 24 * 15
    admin_jwt_audience: str = "image2-admin"

    admin_rsa_private_key: str | None = None
    allow_plaintext_password_login: bool = True

    super_admin_username: str = "admin"
    super_admin_email: str = "admin@example.com"
    super_admin_password: str = "ChangeMe123!"
    qiniu_access_key: str = ""
    qiniu_secret_key: str = ""
    qiniu_bucket: str = ""
    qiniu_cdn_base_url: str = ""
    qiniu_upload_host: str = "https://upload.qiniup.com"
    openagent_release_prefix: str = "openagent/releases"
    material_asset_prefix: str = "material-assets"
    minio_endpoint: str = "minio:9000"
    minio_public_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "image2minio"
    minio_secret_key: str = "image2minio123"
    minio_bucket: str = "image2-assets"
    minio_secure: bool = False
    minio_public_read: bool = True
    site_frontend_root_domain: str = "shyfai.com"
    site_admin_root_domain: str = "shyfai.com"
    site_frontend_base_subdomain: str = "magic"
    site_admin_base_subdomain: str = "magic-admin"
    site_frontend_url: str = ""
    site_host_root_domain_aliases: str = "shyfai.com,shyfai.cn"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def site_host_root_domain_alias_list(self) -> list[str]:
        return [
            item.strip().strip(".").lower()
            for item in self.site_host_root_domain_aliases.split(",")
            if item.strip().strip(".")
        ]

    @property
    def resolved_site_frontend_url(self) -> str:
        configured_url = self.site_frontend_url.strip().rstrip("/")
        if configured_url:
            return configured_url
        root_domain = self.site_frontend_root_domain.strip().strip(".")
        base_subdomain = self.site_frontend_base_subdomain.strip().strip(".") or "magic"
        return f"https://{base_subdomain}.{root_domain}" if root_domain else ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
