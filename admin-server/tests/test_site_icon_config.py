from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.endpoints.admin_data import (
    DEFAULT_SITE_ICON_URL,
    SiteContentConfigRequest,
    default_site_config,
    site_config_out,
    site_content_config_values,
)


def test_site_content_config_accepts_https_icon_and_persists_it():
    payload = SiteContentConfigRequest(site_icon_url=" https://cdn.example.com/brand/icon.webp ")

    values = site_content_config_values(payload, SimpleNamespace(id=27))

    assert values["site_icon_url"] == "https://cdn.example.com/brand/icon.webp"
    assert values["updated_by"] == 27


def test_site_content_config_rejects_unsafe_icon_protocol():
    with pytest.raises(ValidationError):
        SiteContentConfigRequest(site_icon_url="javascript:alert(1)")


def test_site_config_output_keeps_backward_compatible_default_icon():
    assert default_site_config()["site_icon_url"] == DEFAULT_SITE_ICON_URL
    assert site_config_out({"id": 8, "site_key": "child", "site_name": "子站"})["site_icon_url"] == DEFAULT_SITE_ICON_URL


def test_site_config_output_returns_configured_icon():
    icon_url = "https://cdn.example.com/brand/icon.svg"

    assert site_config_out({"site_icon_url": icon_url})["site_icon_url"] == icon_url
