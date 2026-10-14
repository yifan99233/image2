from pydantic import BaseModel, ConfigDict, Field


class AdminImageModelCreate(BaseModel):
    provider_id: int | None = None
    provider_name: str | None = Field(default=None, max_length=80)
    provider_code: str | None = Field(default=None, max_length=80)
    base_url: str | None = Field(default=None, max_length=512)
    access_mode: str = Field(default="api", max_length=32)
    api_key: str | None = Field(default=None, max_length=1024)
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=120)
    vendor_model: str = Field(min_length=1, max_length=160)
    work_type: str = Field(default="image_edit", max_length=80)
    capability_type: str = Field(default="image", max_length=32)
    image_capabilities: list[str] = Field(default_factory=list)
    video_capabilities: list[str] = Field(default_factory=list)
    supported_resolution_ids: list[int] = Field(default_factory=list)
    supported_aspect_ratio_ids: list[int] = Field(default_factory=list)
    supported_duration_ids: list[int] = Field(default_factory=list)
    supports_image_edit: bool = False
    description: str = ""
    is_recommended: bool = False
    is_stable: bool = True
    is_new: bool = False
    speed_hint: str | None = None
    risk_hint: str | None = None
    max_input_images: int = Field(default=1, ge=0)
    max_output_images: int = Field(default=1, ge=0)
    concurrency_limit: int = Field(default=1, ge=0)
    sort_order: int = Field(default=50, ge=0)
    is_active: bool = False
    is_public: bool = True
    storage_mode: str = Field(default="local", max_length=32)
    timeout_seconds: int | None = Field(default=None, ge=10, le=3600)
    disable_retry: bool = False


class AdminImageModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_id: int
    provider_name: str
    provider_code: str
    name: str
    code: str
    vendor_model: str
    work_type: str
    capability_type: str
    supports_image_edit: bool
    description: str
    base_url: str
    access_mode: str
    base_url_masked: str
    api_key_masked: str
    is_recommended: bool
    is_stable: bool
    is_new: bool
    max_input_images: int
    max_output_images: int
    concurrency_limit: int
    is_active: bool
    is_public: bool
    storage_mode: str = "local"
    sort_order: int
    timeout_seconds: int | None = None
    disable_retry: bool = False
    supported_resolutions: list[dict] = Field(default_factory=list)
    supported_aspect_ratios: list[dict] = Field(default_factory=list)
    supported_durations: list[dict] = Field(default_factory=list)
