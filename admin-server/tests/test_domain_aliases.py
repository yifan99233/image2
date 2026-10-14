from __future__ import annotations

from starlette.requests import Request

from app.api.endpoints.admin_data import current_site_config_row
from app.services.site_scope import (
    current_site_id,
    normalized_host,
    site_host_aliases,
)


def _request(host: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"host", host.encode())],
        }
    )


def _bound_string_values(statement) -> set[str]:
    return {
        value
        for value in statement.compile().params.values()
        if isinstance(value, str)
    }


class _ScalarResult:
    def scalar_one_or_none(self):
        return 4


class _MappingResult:
    def mappings(self):
        return self

    def first(self):
        return {"id": 4, "site_key": "sqcm"}


class _SiteIdSession:
    async def execute(self, statement):
        values = _bound_string_values(statement)
        assert "%magic-admin-yy.shyfai.com%" in values
        assert "%magic-admin-yy.shyfai.cn%" in values
        return _ScalarResult()


class _SiteConfigSession:
    async def execute(self, statement):
        values = _bound_string_values(statement)
        assert "%magic-admin-yy.shyfai.com%" in values
        assert "%magic-admin-yy.shyfai.cn%" in values
        return _MappingResult()


def test_admin_host_aliases_keep_cn_and_com_equivalent():
    assert site_host_aliases("magic-admin-yy.shyfai.cn") == (
        "magic-admin-yy.shyfai.com",
        "magic-admin-yy.shyfai.cn",
    )
    assert site_host_aliases("magic-admin-yy.shyfai.com") == (
        "magic-admin-yy.shyfai.com",
        "magic-admin-yy.shyfai.cn",
    )
    assert normalized_host("https://MAGIC-ADMIN-YY.shyfai.cn:443/path") == (
        "magic-admin-yy.shyfai.cn"
    )


async def test_admin_authorization_scope_matches_cn_alias_to_com_site_config():
    assert await current_site_id(
        _SiteIdSession(),
        _request("magic-admin-yy.shyfai.cn"),
    ) == 4


async def test_admin_public_config_matches_cn_alias_to_com_site_config():
    row = await current_site_config_row(
        _SiteConfigSession(),
        _request("magic-admin-yy.shyfai.cn"),
    )
    assert row == {"id": 4, "site_key": "sqcm"}
