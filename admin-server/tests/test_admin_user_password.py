from types import SimpleNamespace

import pytest

from app.api.endpoints.admin_data import UserPasswordResetRequest, reset_user_password
from app.core.exceptions import AppException
from app.models.admin_user import AdminRole, AdminUser
from app.services.security import hash_user_password, verify_password


class FakeSession:
    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount
        self.statement = None
        self.added: list[object] = []
        self.committed = False

    async def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(rowcount=self.rowcount)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed = True


def admin_user() -> AdminUser:
    return AdminUser(
        id=7,
        username="operator",
        email="operator@example.com",
        role=AdminRole.operator,
        site_id=1,
        system_super_admin=False,
        is_active=True,
        password_hash="unused",
    )


@pytest.mark.asyncio
async def test_reset_user_password_hashes_value_and_writes_audit() -> None:
    db = FakeSession()
    plaintext = "SafePassword!2026"

    response = await reset_user_password(
        42,
        UserPasswordResetRequest(new_password=plaintext),
        db=db,
        current_admin=admin_user(),
    )

    assert response.data == {"id": 42, "changed": True}
    assert response.message == "用户密码已重置"
    assert db.statement is not None
    password_hash = db.statement.compile().params["password_hash"]
    assert password_hash != plaintext
    assert verify_password(plaintext, password_hash)
    assert db.committed is True
    assert len(db.added) == 1
    audit = db.added[0]
    assert audit.action == "reset_user_password"
    assert plaintext not in (audit.reason or "")


@pytest.mark.asyncio
async def test_reset_user_password_returns_not_found_without_audit() -> None:
    db = FakeSession(rowcount=0)

    with pytest.raises(AppException) as exc_info:
        await reset_user_password(
            404,
            UserPasswordResetRequest(new_password="SafePassword!2026"),
            db=db,
            current_admin=admin_user(),
        )

    assert exc_info.value.status_code == 404
    assert db.committed is False
    assert db.added == []


def test_user_password_hash_rejects_common_weak_password() -> None:
    with pytest.raises(AppException) as exc_info:
        hash_user_password("12345678")

    assert exc_info.value.status_code == 400
