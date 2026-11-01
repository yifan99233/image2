"""Explicit site/model CDN scope; secrets come from private runtime configuration."""
import json
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ConfigDict, model_validator
from app.core.config import settings


class ModelCdnConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_id: int
    model_ids: list[int]
    cdn_key: str = Field(min_length=1, repr=False)
    public_base_url: str
    key_prefix: str
    endpoint: str
    region: str
    bucket: str
    access_key: str = Field(min_length=1, repr=False)
    secret_key: str = Field(min_length=1, repr=False)

    @model_validator(mode="after")
    def validate_target(self):
        for value in (self.public_base_url, self.endpoint):
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
                raise ValueError("CDN requires HTTPS origins")
        if not self.key_prefix or any(p in ("", ".", "..") for p in self.key_prefix.split("/")):
            raise ValueError("CDN requires an isolated object prefix")
        return self

    @property
    def result_base_url(self) -> str:
        return self.public_base_url.rstrip("/") + "/" + self.key_prefix + "/"


def for_model(site_id: int, model_id: int) -> ModelCdnConfig | None:
    raw = settings.model_cdn_config_json.strip()
    if not raw:
        return None
    # Do not include Pydantic input values (credentials) in errors/logs.
    try:
        value = json.loads(raw)
        configs = [ModelCdnConfig.model_validate(item) for item in (value if isinstance(value, list) else [value])]
        scopes = [(config.site_id, member) for config in configs for member in config.model_ids]
        if len(scopes) != len(set(scopes)):
            raise ValueError("Duplicate model CDN scope")
    except Exception:
        raise RuntimeError("Invalid model CDN configuration") from None
    return next((config for config in configs if config.site_id == site_id and model_id in config.model_ids), None)


def store_reference(*, config: ModelCdnConfig, content: bytes, storage_key: str, mime_type: str) -> str:
    from io import BytesIO
    from minio import Minio
    import urllib3
    from app.core.exceptions import BusinessError

    client = Minio(urlsplit(config.endpoint).netloc, access_key=config.access_key,
                   secret_key=config.secret_key, region=config.region, secure=True,
                   http_client=urllib3.PoolManager(timeout=urllib3.Timeout(connect=10, read=60), retries=False))
    # The bucket already exists. Never create it or modify its public policy here.
    try:
        client.put_object(config.bucket, storage_key, BytesIO(content), len(content), content_type=mime_type)
    except Exception:
        raise BusinessError("专属 CDN 图片上传失败，请稍后重试", code=50020, status_code=502) from None
    return config.public_base_url.rstrip("/") + "/" + storage_key
