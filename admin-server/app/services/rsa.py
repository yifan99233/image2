from functools import lru_cache

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.config import settings
from app.core.exceptions import AppException


@lru_cache
def _private_key() -> rsa.RSAPrivateKey:
    if settings.admin_rsa_private_key:
        key_data = settings.admin_rsa_private_key.encode("utf-8").replace(b"\\n", b"\n")
        key = serialization.load_pem_private_key(key_data, password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise RuntimeError("ADMIN_RSA_PRIVATE_KEY must be an RSA private key")
        return key
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def get_public_key_pem() -> str:
    public_key = _private_key().public_key()
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


def decrypt_password_if_needed(password: str) -> str:
    if password.startswith("rsa:"):
        import base64

        encrypted = base64.b64decode(password.removeprefix("rsa:"))
        try:
            return _private_key().decrypt(
                encrypted,
                padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
            ).decode("utf-8")
        except Exception as exc:
            raise AppException(code=40002, message="密码解密失败", status_code=400) from exc

    if not settings.allow_plaintext_password_login:
        raise AppException(code=40003, message="当前环境不允许明文密码登录", status_code=400)
    return password

