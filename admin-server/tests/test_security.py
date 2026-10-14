from datetime import timedelta
from types import SimpleNamespace

from app.api.endpoints.admin_data import model_task_timeout_seconds, normalize_system_announcement
from app.models.admin_user import AdminRole, AdminUser
from app.services.security import hash_password, issue_admin_token, verify_admin_token, verify_password


def test_password_hash_verification() -> None:
    password_hash = hash_password("ChangeMe123!")

    assert verify_password("ChangeMe123!", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_admin_token_contains_admin_audience() -> None:
    admin = AdminUser(
        id=1,
        username="admin",
        email="admin@example.com",
        role=AdminRole.super_admin,
        system_super_admin=True,
        is_active=True,
        password_hash="x",
    )
    token = issue_admin_token(admin, expires_delta=timedelta(minutes=5))

    payload = verify_admin_token(token)

    assert payload["sub"] == "1"
    assert payload["username"] == "admin"
    assert payload["role"] == "super_admin"
    assert payload["system_super_admin"] is True


def test_model_generation_test_uses_the_model_timeout_not_the_provider_default() -> None:
    assert model_task_timeout_seconds(SimpleNamespace(timeout_seconds=1200)) == 1200
    assert model_task_timeout_seconds(SimpleNamespace(timeout_seconds=7200)) == 3600


def test_system_announcement_requires_content_before_it_is_exposed() -> None:
    assert normalize_system_announcement({"is_enabled": True, "title": "维护通知", "content": ""}) == {
        "is_enabled": False,
        "title": "维护通知",
        "content": "",
        "image_url": "",
    }
    assert normalize_system_announcement('{"is_enabled": true, "title": "  维护通知  ", "content": "  服务将于凌晨维护。  "}') == {
        "is_enabled": True,
        "title": "维护通知",
        "content": "服务将于凌晨维护。",
        "image_url": "",
    }
