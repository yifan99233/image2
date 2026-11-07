import urllib.parse

from fastapi import Request
from sqlalchemy import BigInteger, Boolean, Column, DateTime, MetaData, String, Table, Text, desc, or_, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessError

shared_metadata = MetaData()
site_configs_table = Table(
    "site_configs",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_key", String),
    Column("site_name", String),
    Column("site_icon_url", Text),
    Column("frontend_url", Text),
    Column("admin_url", Text),
    Column("is_default", Boolean),
    Column("is_enabled", Boolean),
    Column("enabled_modules", Text),
    Column("support_qq", String),
    Column("support_wechat", String),
    Column("support_wechat_qrcode_url", Text),
    Column("support_email", String),
    Column("homepage_case_carousels", Text),
    Column("homepage_batch_banners", Text),
    Column("lead_case_materials", Text),
    Column("opencode_install_video", Text),
    Column("system_announcement", Text),
    Column("updated_at", DateTime(timezone=True)),
)


def normalized_host(value: str | None) -> str:
    if not value:
        return ""
    parsed = urllib.parse.urlparse(value if "://" in value else f"//{value}")
    return (parsed.hostname or "").strip().rstrip(".").lower()


def site_host_aliases(value: str | None) -> tuple[str, ...]:
    host = normalized_host(value)
    if not host:
        return ()
    for root_domain in settings.site_host_root_domain_alias_list:
        if host == root_domain:
            prefix = ""
        elif host.endswith(f".{root_domain}"):
            prefix = host[: -len(root_domain)]
        else:
            continue
        return tuple(
            dict.fromkeys(
                f"{prefix}{alias_root}"
                for alias_root in settings.site_host_root_domain_alias_list
            )
        )
    return (host,)


def request_host(request: Request) -> str:
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    return normalized_host(origin) or normalized_host(request.headers.get("host"))


async def current_site_config_row(db: AsyncSession, request: Request):
    host = request_host(request)
    try:
        if host:
            host_conditions = [
                condition
                for alias_host in site_host_aliases(host)
                for condition in (
                    site_configs_table.c.frontend_url.ilike(f"%{alias_host}%"),
                    site_configs_table.c.admin_url.ilike(f"%{alias_host}%"),
                )
            ]
            matched = await db.execute(
                select(site_configs_table)
                .where(
                    site_configs_table.c.is_enabled.is_(True),
                    or_(*host_conditions),
                )
                .order_by(desc(site_configs_table.c.is_default), site_configs_table.c.id)
                .limit(1)
            )
            row = matched.mappings().first()
            if row:
                return row
        row = await db.execute(select(site_configs_table).where(site_configs_table.c.is_default.is_(True)).limit(1))
        default_row = row.mappings().first()
        if default_row:
            return default_row
        row = await db.execute(select(site_configs_table).where(site_configs_table.c.id == 1))
        return row.mappings().first()
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if "site_configs" in str(error).lower():
            return None
        raise


async def current_site_id(db: AsyncSession, request: Request) -> int:
    # team.shyfai.com/<site_key> is a shared team-console domain. Its internal
    # Nginx proxy extracts the path segment and sets this header. User-facing
    # proxies explicitly strip the header, so it cannot be used to switch a
    # normal user request into another tenant.
    requested_site_key = (request.headers.get("x-image2-site-key") or "").strip()
    if requested_site_key:
        row = (
            await db.execute(
                select(site_configs_table.c.id).where(
                    site_configs_table.c.site_key == requested_site_key,
                    site_configs_table.c.is_enabled.is_(True),
                ).limit(1)
            )
        ).first()
        if row is None:
            raise BusinessError("团队子站不存在或已停用", code=40472, status_code=404)
        return int(row.id)
    row = await current_site_config_row(db, request)
    if row and row.get("id"):
        return int(row["id"])
    return 1
