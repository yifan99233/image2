import pytest
from types import SimpleNamespace

from app.api.endpoints import admin_data
from app.api.endpoints.admin_data import (
    agent_config_out,
    default_agent_config,
    default_zpay_config,
    generated_site_urls,
    invite_reward_config_out,
    resolve_agent_group_credentials,
)
from app.core.exceptions import AppException


def test_agent_config_exposes_unified_image_billing_switch():
    assert default_agent_config()["base_url"] == ""
    assert default_agent_config()["image_billing_enabled"] is False
    assert agent_config_out({"is_enabled": True, "image_billing_enabled": True})["image_billing_enabled"] is True


def test_image_billing_switch_does_not_leak_into_invite_reward_config():
    assert "image_billing_enabled" not in invite_reward_config_out({"is_enabled": True})


def test_group_query_reuses_only_the_key_bound_to_the_same_base_url():
    assert resolve_agent_group_credentials(
        "https://agent5.example.test/",
        "",
        {"base_url": "https://agent5.example.test", "admin_api_key": "agent5-key"},
    ) == ("https://agent5.example.test", "agent5-key")


def test_group_query_does_not_mix_a_new_base_url_with_the_stored_site_key():
    with pytest.raises(AppException) as exc_info:
        resolve_agent_group_credentials(
            "https://agent5.example.test",
            "",
            {"base_url": "https://agent3.example.test", "admin_api_key": "agent3-key"},
        )

    assert exc_info.value.message == "Base URL 已变更，请填写该 Agent 服务对应的管理员 Key"


def test_domain_defaults_follow_runtime_settings(monkeypatch):
    monkeypatch.setattr(
        admin_data,
        "settings",
        SimpleNamespace(
            resolved_site_frontend_url="https://studio.example.test",
            site_frontend_root_domain="example.test",
            site_admin_root_domain="example.test",
            site_frontend_base_subdomain="studio",
            site_admin_base_subdomain="studio-admin",
        ),
    )

    assert default_zpay_config()["notify_url"] == "https://studio.example.test/api/recharge/zpay/notify"
    assert default_zpay_config()["return_url"] == "https://studio.example.test/billing/recharge"
    assert generated_site_urls("Demo Site") == {
        "frontend_url": "https://studio-demo-site.example.test",
        "admin_url": "https://studio-admin-demo-site.example.test",
    }


async def test_new_site_defaults_to_art_template_when_available():
    class FakeResult:
        def __init__(self, row):
            self.row = row

        def mappings(self):
            return self

        def first(self):
            return self.row

    class FakeSession:
        async def execute(self, statement):
            assert "site_configs.site_key" in str(statement)
            return FakeResult({"id": 2, "site_key": "art"})

    template = await admin_data.resolve_site_template_row(FakeSession(), None)
    assert template == {"id": 2, "site_key": "art"}
