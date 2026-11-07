from pydantic import BaseModel


class ImageAssetOut(BaseModel):
    id: int
    url: str
    thumbnail_url: str | None = None
    local_url: str | None = None
    r2_url: str | None = None
    r2_expires_at: str | None = None
    mime_type: str
    width: int | None = None
    height: int | None = None
    size_bytes: int
    sha256: str
    source: str
