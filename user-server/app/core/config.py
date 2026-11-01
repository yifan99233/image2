from functools import lru_cache

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")

    app_name: str = "image2-user-server"
    debug: bool = False
    database_url: str = Field(
        validation_alias=AliasChoices("DATABASE_URL", "USER_DATABASE_URL"),
    )
    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias=AliasChoices("REDIS_URL", "USER_REDIS_URL"))
    cors_origins: str = Field(default="*", validation_alias=AliasChoices("CORS_ORIGINS", "USER_CORS_ORIGINS"))
    cors_origin_regex: str | None = Field(default=".*", validation_alias=AliasChoices("CORS_ORIGIN_REGEX", "USER_CORS_ORIGIN_REGEX"))
    site_host_root_domain_aliases: str = Field(
        default="shyfai.cn",
        validation_alias=AliasChoices(
            "SITE_HOST_ROOT_DOMAIN_ALIASES",
            "USER_SITE_HOST_ROOT_DOMAIN_ALIASES",
        ),
    )
    jwt_secret_key: str = Field(default="change-me-in-production", min_length=16, validation_alias=AliasChoices("JWT_SECRET_KEY", "USER_JWT_SECRET_KEY"))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 15
    team_invite_token_expire_days: int = Field(
        default=30,
        ge=1,
        le=365,
        validation_alias=AliasChoices("TEAM_INVITE_TOKEN_EXPIRE_DAYS", "USER_TEAM_INVITE_TOKEN_EXPIRE_DAYS"),
    )
    password_rsa_private_key: str | None = None
    allow_plaintext_password: bool = Field(default=True, validation_alias=AliasChoices("ALLOW_PLAINTEXT_PASSWORD", "USER_ALLOW_PLAINTEXT_PASSWORD"))
    login_rate_limit_max_attempts: int = 5
    login_rate_limit_window_seconds: int = 60
    image_retention_enabled: bool = False
    image_retention_batch_size: int = Field(default=500, ge=1, le=500)
    image_retention_interval_seconds: int = Field(default=60, ge=10)
    upload_max_bytes: int = 10 * 1024 * 1024
    batch_upload_max_bytes: int = Field(default=64 * 1024 * 1024, ge=1024, le=128 * 1024 * 1024)
    batch_upload_max_prompt_chars: int = Field(default=100_000, ge=1, le=1_000_000)
    batch_upload_worker_interval_seconds: float = Field(default=2, ge=0.1, le=60)
    batch_upload_worker_max_inflight: int = Field(default=2, ge=1, le=8)
    batch_upload_worker_max_attempts: int = Field(default=3, ge=1, le=10)
    canvas_max_document_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    canvas_max_nodes: int = Field(default=10000, ge=1)
    upload_allowed_mime_types: str = "image/jpeg,image/png,image/webp"
    material_cdn_upload_credit_cost: int = Field(
        default=1,
        ge=0,
        validation_alias=AliasChoices(
            "MATERIAL_CDN_UPLOAD_CREDIT_COST",
            "USER_MATERIAL_CDN_UPLOAD_CREDIT_COST",
        ),
    )
    minio_endpoint: str = Field(default="minio:9000", validation_alias=AliasChoices("MINIO_ENDPOINT", "USER_MINIO_ENDPOINT"))
    minio_public_endpoint: str = Field(default="http://localhost:9000", validation_alias=AliasChoices("MINIO_PUBLIC_ENDPOINT", "USER_MINIO_PUBLIC_ENDPOINT"))
    minio_access_key: str = Field(default="image2minio", validation_alias=AliasChoices("MINIO_ACCESS_KEY", "MINIO_ROOT_USER"))
    minio_secret_key: str = Field(default="image2minio123", validation_alias=AliasChoices("MINIO_SECRET_KEY", "MINIO_ROOT_PASSWORD"))
    minio_bucket: str = Field(default="image2-assets", validation_alias=AliasChoices("MINIO_BUCKET", "USER_MINIO_BUCKET"))
    minio_secure: bool = False
    minio_public_read: bool = True
    upload_storage_provider: str = Field(default="minio", validation_alias=AliasChoices("UPLOAD_STORAGE_PROVIDER", "USER_UPLOAD_STORAGE_PROVIDER"))
    model_cdn_config_json: str = Field(default="", repr=False)
    image_storage_target: str = Field(default="", validation_alias=AliasChoices("IMAGE_STORAGE_TARGET", "USER_IMAGE_STORAGE_TARGET"))
    image_storage_targets_json: str = Field(default="", validation_alias=AliasChoices("IMAGE_STORAGE_TARGETS_JSON", "USER_IMAGE_STORAGE_TARGETS_JSON"))
    qiniu_access_key: str = Field(default="", validation_alias=AliasChoices("USER_QINIU_ACCESS_KEY", "QINIU_ACCESS_KEY"))
    qiniu_secret_key: str = Field(default="", validation_alias=AliasChoices("USER_QINIU_SECRET_KEY", "QINIU_SECRET_KEY"))
    qiniu_bucket: str = Field(default="", validation_alias=AliasChoices("USER_QINIU_BUCKET", "QINIU_BUCKET"))
    qiniu_cdn_base_url: str = Field(default="", validation_alias=AliasChoices("USER_QINIU_CDN_BASE_URL", "QINIU_CDN_BASE_URL"))
    qiniu_upload_host: str = Field(default="https://upload.qiniup.com", validation_alias=AliasChoices("USER_QINIU_UPLOAD_HOST", "QINIU_UPLOAD_HOST"))
    qiniu_image_prefix: str = Field(default="image2-assets", validation_alias=AliasChoices("USER_QINIU_IMAGE_PREFIX", "QINIU_IMAGE_PREFIX"))
    qiniu_verify_timeout_seconds: float = Field(default=10, gt=0, le=60)
    qiniu_verify_budget_seconds: float = Field(default=15, gt=0, le=120)
    # Cloudflare R2 is a short-lived hot layer. Secrets must only be supplied
    # through the environment; never commit them to the repository.
    r2_enabled: bool = Field(default=False, validation_alias=AliasChoices("USER_R2_ENABLED", "R2_ENABLED"))
    r2_endpoint: str = Field(default="", validation_alias=AliasChoices("USER_R2_ENDPOINT", "R2_ENDPOINT"))
    r2_access_key_id: str = Field(default="", validation_alias=AliasChoices("USER_R2_ACCESS_KEY_ID", "R2_ACCESS_KEY_ID"))
    r2_secret_access_key: str = Field(default="", validation_alias=AliasChoices("USER_R2_SECRET_ACCESS_KEY", "R2_SECRET_ACCESS_KEY"))
    r2_bucket: str = Field(default="", validation_alias=AliasChoices("USER_R2_BUCKET", "R2_BUCKET"))
    r2_public_base_url: str = Field(default="", validation_alias=AliasChoices("USER_R2_PUBLIC_BASE_URL", "R2_PUBLIC_BASE_URL"))
    r2_upload_expires_seconds: int = Field(
        default=900,
        ge=60,
        le=7 * 24 * 60 * 60,
        validation_alias=AliasChoices("USER_R2_UPLOAD_EXPIRES_SECONDS", "R2_UPLOAD_EXPIRES_SECONDS"),
    )
    r2_hot_url_ttl_seconds: int = Field(
        default=3 * 24 * 60 * 60,
        ge=60,
        le=30 * 24 * 60 * 60,
        validation_alias=AliasChoices("USER_R2_HOT_URL_TTL_SECONDS", "R2_HOT_URL_TTL_SECONDS"),
    )
    database_pool_size: int = Field(
        # Keep the default connection footprint bounded. Image tasks spend
        # most of their time outside PostgreSQL; a large pool per worker
        # leaves many idle backends after a short request burst.
        default=40,
        ge=1,
        le=1000,
        validation_alias=AliasChoices("DATABASE_POOL_SIZE", "USER_DATABASE_POOL_SIZE"),
    )
    database_max_overflow: int = Field(
        default=40,
        ge=0,
        le=2000,
        validation_alias=AliasChoices("DATABASE_MAX_OVERFLOW", "USER_DATABASE_MAX_OVERFLOW"),
    )
    database_pool_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        validation_alias=AliasChoices("DATABASE_POOL_TIMEOUT_SECONDS", "USER_DATABASE_POOL_TIMEOUT_SECONDS"),
    )
    # Bound redis-py connection fan-out.  The default redis asyncio pool is
    # effectively unbounded, so a burst of health checks/status polls can
    # leave hundreds of idle sockets per worker.
    redis_max_connections: int = Field(
        default=100,
        ge=1,
        le=2000,
        validation_alias=AliasChoices("REDIS_MAX_CONNECTIONS", "USER_REDIS_MAX_CONNECTIONS"),
    )
    image_generation_rate_limit_retry_attempts: int = 5
    image_export_max_concurrency: int = Field(default=2, ge=1, le=16)
    image_export_download_workers: int = Field(default=4, ge=1, le=8)
    # Legacy exports still assemble in memory; keep their small hard cap.
    # Prompt exports use ZIP64 streaming with bounded image prefetch.
    image_export_stream_max_bytes: int = Field(default=100 * 1024**3, ge=1, le=1024**4)
    image_export_max_bytes: int = Field(
        default=512 * 1024 * 1024,
        ge=16 * 1024 * 1024,
        le=4 * 1024 * 1024 * 1024,
        validation_alias=AliasChoices("IMAGE_EXPORT_MAX_BYTES", "USER_IMAGE_EXPORT_MAX_BYTES"),
    )
    image_generation_rate_limit_retry_delay_seconds: int = 20
    image_task_reaper_enabled: bool = True
    image_task_reaper_interval_seconds: int = 30
    image_task_reaper_batch_size: int = 100
    image_task_running_stale_seconds: int = 30 * 60
    image_task_worker_heartbeat_interval_seconds: int = 30
    image_task_worker_heartbeat_stale_seconds: int = 10 * 60
    # Bound queued work per account independently from execution concurrency.
    # This prevents repeated batch submissions from creating an unbounded
    # credit-backed queue while still allowing one full 20,000-item batch.
    image_task_queue_limit_per_user: int = Field(
        default=20000,
        ge=100,
        le=100_000,
        validation_alias=AliasChoices("IMAGE_TASK_QUEUE_LIMIT_PER_USER", "USER_IMAGE_TASK_QUEUE_LIMIT_PER_USER"),
    )
    image_task_dispatcher_enabled: bool = True
    image_task_dispatcher_interval_seconds: int = 2
    # These are per-process limits. Keep the safe default conservative because
    # multiple Uvicorn workers multiply the effective upstream concurrency.
    # Increase them only after measuring the provider and host capacity.
    image_task_dispatcher_batch_size: int = Field(
        default=64,
        ge=1,
        le=4000,
        validation_alias=AliasChoices("IMAGE_TASK_DISPATCHER_BATCH_SIZE", "USER_IMAGE_TASK_DISPATCHER_BATCH_SIZE"),
    )
    # 同时处于 execute_claimed_image_task 的 asyncio 任务上限（批量提交限流）
    image_task_dispatcher_max_inflight: int = Field(
        default=64,
        ge=1,
        le=4000,
        validation_alias=AliasChoices("IMAGE_TASK_DISPATCHER_MAX_INFLIGHT", "USER_IMAGE_TASK_DISPATCHER_MAX_INFLIGHT"),
    )
    # 实际打上游 HTTP 的并发上限（信号量）；与 dispatcher 保持接近，避免本地排队被算进生图耗时
    image_task_generation_max_inflight: int = Field(
        default=64,
        ge=1,
        le=4000,
        validation_alias=AliasChoices("IMAGE_TASK_GENERATION_MAX_INFLIGHT", "USER_IMAGE_TASK_GENERATION_MAX_INFLIGHT"),
    )
    image_task_generation_thread_pool_size: int = Field(
        default=64,
        ge=1,
        le=4000,
        validation_alias=AliasChoices("IMAGE_TASK_GENERATION_THREAD_POOL_SIZE", "USER_IMAGE_TASK_GENERATION_THREAD_POOL_SIZE"),
    )
    image_task_storage_thread_pool_size: int = Field(
        default=64,
        ge=1,
        le=4000,
        validation_alias=AliasChoices("IMAGE_TASK_STORAGE_THREAD_POOL_SIZE", "USER_IMAGE_TASK_STORAGE_THREAD_POOL_SIZE"),
    )

    @model_validator(mode="after")
    def validate_image_capacity_alignment(self) -> "Settings":
        required_inflight = self.image_task_generation_max_inflight
        capacity_layers = {
            "image_task_generation_thread_pool_size": self.image_task_generation_thread_pool_size,
            "image_task_storage_thread_pool_size": self.image_task_storage_thread_pool_size,
            "image_task_dispatcher_batch_size": self.image_task_dispatcher_batch_size,
            "image_task_dispatcher_max_inflight": self.image_task_dispatcher_max_inflight,
        }
        undersized = {
            name: value
            for name, value in capacity_layers.items()
            if value < required_inflight
        }
        if undersized:
            details = ", ".join(
                f"{name}={value}"
                for name, value in sorted(undersized.items())
            )
            raise ValueError(
                "image generation capacity layers must be at least "
                f"image_task_generation_max_inflight={required_inflight}: "
                f"{details}"
            )
        return self

    # 结果下载不再使用独立并发阈值：任务在下载与存储完成前会一直占用
    # image_models.concurrency_limit 对应的 running 槽位，因此下载自然跟随模型并发。
    image_result_download_timeout_seconds: int = Field(
        default=600,
        ge=30,
        le=3600,
        validation_alias=AliasChoices(
            "IMAGE_RESULT_DOWNLOAD_TIMEOUT_SECONDS",
            "USER_IMAGE_RESULT_DOWNLOAD_TIMEOUT_SECONDS",
        ),
    )
    image_result_download_read_timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        validation_alias=AliasChoices(
            "IMAGE_RESULT_DOWNLOAD_READ_TIMEOUT_SECONDS",
            "USER_IMAGE_RESULT_DOWNLOAD_READ_TIMEOUT_SECONDS",
        ),
    )
    image_download_retry_attempts: int = Field(
        default=5,
        ge=1,
        le=5,
        validation_alias=AliasChoices(
            "IMAGE_DOWNLOAD_RETRY_ATTEMPTS",
            "USER_IMAGE_DOWNLOAD_RETRY_ATTEMPTS",
        ),
    )
    image_download_retry_delay_seconds: float = Field(
        default=0.5,
        ge=0,
        le=10,
        validation_alias=AliasChoices(
            "IMAGE_DOWNLOAD_RETRY_DELAY_SECONDS",
            "USER_IMAGE_DOWNLOAD_RETRY_DELAY_SECONDS",
        ),
    )
    image_result_download_max_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1024 * 1024,
        le=1024 * 1024 * 1024,
        validation_alias=AliasChoices(
            "IMAGE_RESULT_DOWNLOAD_MAX_BYTES",
            "USER_IMAGE_RESULT_DOWNLOAD_MAX_BYTES",
        ),
    )
    image_video_download_max_bytes: int = Field(
        default=256 * 1024 * 1024,
        ge=16 * 1024 * 1024,
        le=2 * 1024 * 1024 * 1024,
        validation_alias=AliasChoices(
            "IMAGE_VIDEO_DOWNLOAD_MAX_BYTES",
            "USER_IMAGE_VIDEO_DOWNLOAD_MAX_BYTES",
        ),
    )
    image_provider_response_max_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1024 * 1024,
        le=256 * 1024 * 1024,
        validation_alias=AliasChoices(
            "IMAGE_PROVIDER_RESPONSE_MAX_BYTES",
            "USER_IMAGE_PROVIDER_RESPONSE_MAX_BYTES",
        ),
    )
    gateway_connect_timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=120,
        validation_alias=AliasChoices("GATEWAY_CONNECT_TIMEOUT_SECONDS", "USER_GATEWAY_CONNECT_TIMEOUT_SECONDS"),
    )
    gateway_read_timeout_seconds: int = Field(
        default=600,
        ge=30,
        le=3600,
        validation_alias=AliasChoices("GATEWAY_READ_TIMEOUT_SECONDS", "USER_GATEWAY_READ_TIMEOUT_SECONDS"),
    )
    gateway_write_timeout_seconds: int = Field(
        default=600,
        ge=30,
        le=3600,
        validation_alias=AliasChoices("GATEWAY_WRITE_TIMEOUT_SECONDS", "USER_GATEWAY_WRITE_TIMEOUT_SECONDS"),
    )
    gateway_max_connections: int = Field(
        default=500,
        ge=10,
        le=5000,
        validation_alias=AliasChoices("GATEWAY_MAX_CONNECTIONS", "USER_GATEWAY_MAX_CONNECTIONS"),
    )
    gateway_max_keepalive_connections: int = Field(
        default=100,
        ge=1,
        le=1000,
        validation_alias=AliasChoices(
            "GATEWAY_MAX_KEEPALIVE_CONNECTIONS",
            "USER_GATEWAY_MAX_KEEPALIVE_CONNECTIONS",
        ),
    )
    zpay_enabled: bool = Field(default=False, validation_alias=AliasChoices("ZPAY_ENABLED", "USER_ZPAY_ENABLED"))
    zpay_pid: str = Field(default="", validation_alias=AliasChoices("ZPAY_PID", "USER_ZPAY_PID"))
    zpay_pkey: str = Field(default="", validation_alias=AliasChoices("ZPAY_PKEY", "USER_ZPAY_PKEY"))
    zpay_api_base: str = Field(default="", validation_alias=AliasChoices("ZPAY_API_BASE", "USER_ZPAY_API_BASE"))
    zpay_notify_url: str = Field(default="", validation_alias=AliasChoices("ZPAY_NOTIFY_URL", "USER_ZPAY_NOTIFY_URL"))
    zpay_return_url: str = Field(default="", validation_alias=AliasChoices("ZPAY_RETURN_URL", "USER_ZPAY_RETURN_URL"))
    zpay_payment_type: str = Field(default="alipay", validation_alias=AliasChoices("ZPAY_PAYMENT_TYPE", "USER_ZPAY_PAYMENT_TYPE"))
    zpay_payment_mode: str = Field(default="qrcode", validation_alias=AliasChoices("ZPAY_PAYMENT_MODE", "USER_ZPAY_PAYMENT_MODE"))
    zpay_timeout_seconds: int = Field(default=10, validation_alias=AliasChoices("ZPAY_TIMEOUT_SECONDS", "USER_ZPAY_TIMEOUT_SECONDS"))
    recharge_order_expire_minutes: int = Field(default=30, validation_alias=AliasChoices("RECHARGE_ORDER_EXPIRE_MINUTES", "USER_RECHARGE_ORDER_EXPIRE_MINUTES"))

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def site_host_root_domain_alias_list(self) -> list[str]:
        return [
            item.strip().strip(".").lower()
            for item in self.site_host_root_domain_aliases.split(",")
            if item.strip().strip(".")
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
