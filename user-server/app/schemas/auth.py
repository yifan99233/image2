from pydantic import BaseModel, EmailStr, Field, field_validator


class AuthUser(BaseModel):
    id: int
    username: str
    email: str
    nickname: str | None = None
    avatar_url: str | None = None
    is_active: bool
    invited_by_user_id: int | None = None
    created_at: str | None = None
    last_login_at: str | None = None


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email: EmailStr
    password: str = Field(min_length=1, max_length=2048)
    nickname: str | None = Field(default=None, max_length=128)
    invite_code: str | None = Field(default=None, max_length=32)
    referral_token: str | None = Field(default=None, max_length=2048)
    team_invite_token: str | None = Field(default=None, max_length=2048)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        username = value.strip()
        if not username:
            raise ValueError("用户名不能为空")
        if any(char.isspace() for char in username):
            raise ValueError("用户名不能包含空白字符")
        return username


class LoginRequest(BaseModel):
    username: str
    password: str = Field(min_length=1, max_length=2048)


class ImpersonationExchangeRequest(BaseModel):
    code: str = Field(min_length=32, max_length=256)


class ProfileUpdateRequest(BaseModel):
    email: EmailStr
    nickname: str | None = Field(default=None, max_length=128)
    avatar_url: str | None = Field(default=None, max_length=1024)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=2048)
    new_password: str = Field(min_length=8, max_length=2048)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUser


class PublicKeyResponse(BaseModel):
    public_key: str
