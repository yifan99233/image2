import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256
from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import BusinessError

PBKDF2_ITERATIONS = 120_000
_generated_private_key: rsa.RSAPrivateKey | None = None


def validate_password_strength(password: str) -> None:
    if len(password) < 8:
        raise BusinessError("密码至少需要8位")
    if len(password) > 128:
        raise BusinessError("密码不能超过128位")
    if password.lower() in {"password", "12345678", "qwerty", "admin123", "11111111"}:
        raise BusinessError("密码过于简单，请使用更复杂的密码")


def hash_password(password: str) -> str:
    validate_password_strength(password)
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), expected)
    except Exception:
        return False


def create_access_token(user_id: int, username: str, expires_delta: timedelta | None = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload: dict[str, Any] = {"sub": str(user_id), "username": username, "iat": now, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_impersonation_access_token(
    user_id: int,
    username: str,
    *,
    admin_id: int,
    admin_username: str,
    expires_delta: timedelta = timedelta(hours=1),
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "impersonation": True,
        "impersonated_by_admin_id": admin_id,
        "impersonated_by_admin_username": admin_username,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_export_access_token(user_id: int, *, task_ids: list[int], batch_id: str = "") -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "purpose": "image_export",
        "task_ids": task_ids,
        "batch_id": batch_id,
        "iat": now,
        "exp": now + timedelta(minutes=10),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_export_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise BusinessError("导出链接无效或已过期", code=40101, status_code=401) from exc
    if payload.get("purpose") != "image_export":
        raise BusinessError("导出链接无效", code=40101, status_code=401)
    return payload


def verify_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise BusinessError("令牌无效或已过期", code=40101, status_code=401) from exc


def _load_private_key() -> rsa.RSAPrivateKey:
    global _generated_private_key
    if settings.password_rsa_private_key:
        key_data = settings.password_rsa_private_key.replace("\\n", "\n").encode("utf-8")
        key = serialization.load_pem_private_key(key_data, password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise RuntimeError("PASSWORD_RSA_PRIVATE_KEY must be an RSA private key")
        return key
    if _generated_private_key is None:
        _generated_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _generated_private_key


def get_public_key_pem() -> str:
    public_key = _load_private_key().public_key()
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


def decrypt_password(encrypted_password: str) -> str:
    ciphertext = base64.b64decode(encrypted_password)
    plaintext = _load_private_key().decrypt(
        ciphertext,
        padding.OAEP(mgf=padding.MGF1(algorithm=SHA256()), algorithm=SHA256(), label=None),
    )
    return plaintext.decode("utf-8")


def resolve_submitted_password(password: str) -> str:
    try:
        return decrypt_password(password)
    except Exception as exc:
        if settings.allow_plaintext_password:
            return password
        raise BusinessError("密码必须使用 RSA 公钥加密", code=40002) from exc
