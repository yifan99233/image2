import urllib.parse

from fastapi import Request
from sqlalchemy import BigInteger, Boolean, Column, DateTime, MetaData, String, Table, Text, desc, or_, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

shared_metadata = MetaData()
site_configs_table = Table(
    "site_configs",
    shared_metadata,
    Column("id", BigInteger),
    Column("frontend_url", Text),
    Column("admin_url", Text),
    Column("is_default", Boolean),
    Column("is_enabled", Boolean),
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


async def current_site_id(db: AsyncSession, request: Request) -> int:
    host = request_host(request)
    try:
        if host:
            host_conditions = [
                condition
                for alias_host in site_host_aliases(host)
                for condition in (
                    site_configs_table.c.admin_url.ilike(f"%{alias_host}%"),
                    site_configs_table.c.frontend_url.ilike(f"%{alias_host}%"),
                )
            ]
            matched = await db.execute(
                select(site_configs_table.c.id)
                .where(
                    site_configs_table.c.is_enabled.is_(True),
                    or_(*host_conditions),
                )
                .order_by(desc(site_configs_table.c.is_default), site_configs_table.c.id)
                .limit(1)
            )
            site_id = matched.scalar_one_or_none()
            if site_id:
                return int(site_id)
        default_site_id = await db.scalar(select(site_configs_table.c.id).where(site_configs_table.c.is_default.is_(True)).limit(1))
        return int(default_site_id or 1)
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if "site_configs" in str(error).lower():
            return 1
        raise
