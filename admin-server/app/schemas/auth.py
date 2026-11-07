from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.admin_user import AdminRole


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    role: AdminRole
    system_super_admin: bool = False
    site_id: int = 1
    is_active: bool
    last_login_at: datetime | None = None


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=4096)


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin: AdminUserOut


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=4096)
    new_password: str = Field(min_length=8, max_length=128)
