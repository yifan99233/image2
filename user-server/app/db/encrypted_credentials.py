"""Encrypted stored credentials, with read compatibility for legacy rows."""

import base64
import hashlib

from cryptography.fernet import Fernet
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.config import settings


class EncryptedCredential(TypeDecorator):
    impl = Text
    cache_ok = True
    prefix = "enc:v1:"

    @staticmethod
    def cipher() -> Fernet:
        # Domain separation from JWT signing; retain this secret when moving data.
        key = hashlib.sha256(
            ("image2-agent-credential-v1:" + settings.jwt_secret_key).encode()
        ).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return self.prefix + self.cipher().encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None or not value.startswith(self.prefix):
            return value
        return self.cipher().decrypt(value[len(self.prefix):].encode()).decode()
