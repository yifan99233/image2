import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import AppException
from app.models.admin_user import AdminUser

PBKDF2_ITERATIONS = 210_000
COMMON_WEAK_PASSWORDS = frozenset({"password", "12345678", "qwerty", "admin123", "11111111"})


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise AppException(code=40010, message="密码至少需要 8 位", status_code=400)
    if len(password) > 128:
        raise AppException(code=40011, message="密码不能超过 128 位", status_code=400)


def validate_user_password(password: str) -> None:
    validate_password(password)
    if password.lower() in COMMON_WEAK_PASSWORDS:
        raise AppException(code=40012, message="密码过于简单，请更换更安全的密码", status_code=400)


def hash_password(password: str, salt: str | None = None) -> str:
    validate_password(password)
    password_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), password_salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${password_salt}${digest.hex()}"


def hash_user_password(password: str, salt: str | None = None) -> str:
    validate_user_password(password)
    return hash_password(password, salt)


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except Exception:
        return False


def issue_admin_token(admin: AdminUser, expires_delta: timedelta | None = None) -> str:
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.admin_access_token_expire_minutes))
    payload: dict[str, Any] = {
        "sub": str(admin.id),
        "username": admin.username,
        "role": admin.role.value,
        "system_super_admin": admin.system_super_admin,
        "aud": settings.admin_jwt_audience,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.admin_jwt_secret_key, algorithm=settings.admin_jwt_algorithm)


def verify_admin_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.admin_jwt_secret_key,
            algorithms=[settings.admin_jwt_algorithm],
            audience=settings.admin_jwt_audience,
        )
    except JWTError:
        raise
