import hashlib
from types import SimpleNamespace

import pytest

from app.api.endpoints.admin_data import (
    create_user_impersonation,
    ensure_can_impersonate_users,
    normalize_impersonation_frontend_url,
)
from app.core.exceptions import AppException
from app.models.admin_user import AdminRole


def admin(*, username: str = "yifan", role: AdminRole = AdminRole.super_admin, system_super_admin: bool = True):
    return SimpleNamespace(
        id=1,
        username=username,
        role=role,
        system_super_admin=system_super_admin,
        is_active=True,
    )


def test_yifan_system_super_admin_can_impersonate_users() -> None:
    ensure_can_impersonate_users(admin(username="YiFan"))


@pytest.mark.parametrize(
    ("username", "role", "system_super_admin"),
    [
        ("other", AdminRole.super_admin, True),
        ("yifan", AdminRole.operator, True),
        ("yifan", AdminRole.super_admin, False),
    ],
)
def test_other_admins_cannot_impersonate_users(
    username: str,
    role: AdminRole,
    system_super_admin: bool,
) -> None:
    with pytest.raises(AppException) as exc_info:
        ensure_can_impersonate_users(
            admin(username=username, role=role, system_super_admin=system_super_admin)
        )

    assert exc_info.value.status_code == 403


def test_impersonation_url_requires_https_except_local_development() -> None:
    assert normalize_impersonation_frontend_url("https://magic-demo.shyfai.com/") == "https://magic-demo.shyfai.com"
    assert normalize_impersonation_frontend_url("http://localhost:5173/") == "http://localhost:5173"

    with pytest.raises(AppException):
        normalize_impersonation_frontend_url("http://magic-demo.shyfai.com")


class FakeSession:
    def __init__(self) -> None:
        self.statements = []
        self.audit_entries = []
        self.commit_count = 0

    async def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            user = SimpleNamespace(id=42, site_id=3, username="target", is_active=True)
            return SimpleNamespace(one_or_none=lambda: user)
        return SimpleNamespace()

    async def scalar(self, _statement):
        return "https://magic-demo.shyfai.com/"

    def add(self, value) -> None:
        self.audit_entries.append(value)

    async def commit(self) -> None:
        self.commit_count += 1


@pytest.mark.asyncio
async def test_create_user_impersonation_stores_only_hash_and_returns_fragment_code() -> None:
    db = FakeSession()

    response = await create_user_impersonation(
        42,
        db=db,
        current_admin=admin(),
    )

    login_url = response.data["login_url"]
    assert login_url.startswith("https://magic-demo.shyfai.com/admin-login#code=")
    code = login_url.rsplit("#code=", 1)[1]
    insert_params = db.statements[2].compile().params
    assert insert_params["token_hash"] == hashlib.sha256(code.encode("utf-8")).hexdigest()
    assert code not in insert_params.values()
    assert db.commit_count == 1
    assert db.audit_entries[0].action == "create_user_impersonation"
