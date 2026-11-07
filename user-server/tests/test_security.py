from datetime import timedelta

import pytest

from app.core.exceptions import BusinessError
from app.services.security import create_access_token, hash_password, verify_access_token, verify_password


def test_password_hash_and_verify():
    password_hash = hash_password("strong-pass-123")

    assert password_hash != "strong-pass-123"
    assert verify_password("strong-pass-123", password_hash)
    assert not verify_password("wrong-pass-123", password_hash)


def test_weak_password_rejected():
    with pytest.raises(BusinessError):
        hash_password("12345678")


def test_expired_token_rejected():
    token = create_access_token(1, "alice", expires_delta=timedelta(seconds=-1))

    with pytest.raises(BusinessError) as exc:
        verify_access_token(token)

    assert exc.value.status_code == 401
