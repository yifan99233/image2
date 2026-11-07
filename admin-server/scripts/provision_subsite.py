"""Import a secret-free configuration snapshot as a new, isolated site.

Run inside the deployed admin-server environment. Credentials are reused inside
its database; they are never read from the snapshot or printed. Default: rollback.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse

from sqlalchemy import DateTime, MetaData, func, insert, select, text
from sqlalchemy.exc import SQLAlchemyError
from app.db.session import AsyncSessionLocal

TABLES = (
    "image_model_providers", "image_resolution_specs", "image_aspect_ratio_specs",
    "video_duration_specs", "image_models", "image_model_resolutions",
    "image_model_aspect_ratios", "image_model_durations", "image_model_prices",
    "recharge_plans", "openagent_releases", "invite_reward_configs",
    "signin_reward_configs", "user_experience_configs", "payment_configs",
)
LINKS = {
    "image_models": {"provider_id": "image_model_providers"},
    "image_model_resolutions": {"model_id": "image_models", "resolution_id": "image_resolution_specs"},
    "image_model_aspect_ratios": {"model_id": "image_models", "aspect_ratio_id": "image_aspect_ratio_specs"},
    "image_model_durations": {"model_id": "image_models", "duration_id": "video_duration_specs"},
    "image_model_prices": {"model_id": "image_models"},
}
SECRETS = {"encrypted_api_key", "admin_api_key", "pid", "pkey"}


def values_for(table, row):
    unknown = set(row) - set(table.c.keys())
    # The test environment may contain the new zero-default surcharge before
    # production's pricing migration. Never silently drop a nonzero surcharge.
    if unknown - {"fixed_surcharge"} or ("fixed_surcharge" in unknown and Decimal(str(row["fixed_surcharge"])) != 0):
        raise ValueError(f"Unsupported snapshot columns for {table.name}: {sorted(unknown)}")
    values = {k: v for k, v in row.items() if k in table.c and k not in {"id", "site_id", "created_at", "updated_at", "updated_by"} | SECRETS}
    for key, value in values.items():
        if isinstance(table.c[key].type, DateTime) and isinstance(value, str):
            values[key] = datetime.fromisoformat(value)
    return values


async def provision(db, snapshot, args):
    await db.execute(text("SET LOCAL lock_timeout = '10s'"))
    await db.execute(text("SET LOCAL statement_timeout = '60s'"))
    await db.execute(text("LOCK TABLE site_configs IN SHARE ROW EXCLUSIVE MODE"))
    metadata = MetaData()
    connection = await db.connection()
    await connection.run_sync(lambda conn: metadata.reflect(conn, only=["site_configs", "agent_configs", "admin_users", "admin_audit_logs", *TABLES], resolve_fks=False))
    tables = metadata.tables
    sites = tables["site_configs"]
    if await db.scalar(select(sites.c.id).where(sites.c.site_key == args.site_key)):
        raise ValueError("Site already exists; refusing to overwrite it")
    for url in (args.frontend_url, args.admin_url):
        if urlparse(url).scheme != "https" or not urlparse(url).hostname:
            raise ValueError("Both site URLs must be HTTPS")
        if await db.scalar(select(sites.c.id).where((sites.c.frontend_url == url) | (sites.c.admin_url == url))):
            raise ValueError("Domain already belongs to a site")
    source = await db.scalar(select(sites.c.id).where(sites.c.site_key == args.credentials_site))
    agent_source = await db.scalar(select(sites.c.id).where(sites.c.site_key == args.agent_site))
    if not source or not agent_source:
        raise ValueError("Credential/agent source site does not exist")
    admins = tables["admin_users"]
    admin_id = await db.scalar(select(admins.c.id).where(admins.c.system_super_admin.is_(True), admins.c.is_active.is_(True)).order_by(admins.c.id).limit(1))
    if not admin_id:
        raise ValueError("No active system administrator for audit ownership")
    agent_table = tables["agent_configs"]
    agent = (await db.execute(select(agent_table).where(agent_table.c.site_id == agent_source))).mappings().one()
    if urlparse(agent["base_url"]).hostname != args.allowed_agent_host or not agent["admin_api_key"] or not agent["is_enabled"]:
        raise ValueError("Agent source is not an enabled, configured allowed upstream")
    providers = tables["image_model_providers"]
    credentials = {r["code"]: dict(r) for r in (await db.execute(select(providers).where(providers.c.site_id == source))).mappings()}
    payments = tables["payment_configs"]
    payment_credentials = {r["provider"]: dict(r) for r in (await db.execute(select(payments).where(payments.c.site_id == source))).mappings()}
    next_site = int(await db.scalar(select(func.coalesce(func.max(sites.c.id), 0) + 1)))

    locked_tables = set()

    async def add(table, values):
        # Earlier site imports may have assigned explicit IDs without advancing
        # sequences. Lock only configuration tables and allocate above both.
        if table.name not in locked_tables:
            await db.execute(text(f'LOCK TABLE "{table.name}" IN SHARE ROW EXCLUSIVE MODE'))
            locked_tables.add(table.name)
        if "updated_by" in table.c:
            values["updated_by"] = admin_id
        if "site_id" in table.c:
            values["site_id"] = next_site
        next_id = int(await db.scalar(select(func.coalesce(func.max(table.c.id), 0) + 1)))
        sequence = await db.scalar(text("SELECT pg_get_serial_sequence(:table, 'id')"), {"table": table.name})
        if sequence:
            reserved = int(await db.scalar(text("SELECT nextval(CAST(:seq AS regclass))"), {"seq": sequence}))
            next_id = max(next_id, reserved)
            if next_id > reserved:
                await db.execute(text("SELECT setval(CAST(:seq AS regclass), :value, true)"), {"seq": sequence, "value": next_id})
        values["id"] = next_id
        return int(await db.scalar(insert(table).values(**values).returning(table.c.id)))

    site_values = values_for(sites, snapshot["site"])
    site_values.update(site_key=args.site_key, site_name=args.site_name,
                       frontend_url=args.frontend_url.rstrip("/"), admin_url=args.admin_url.rstrip("/"),
                       is_default=False, is_enabled=True)
    site_id = await add(sites, site_values)
    assert site_id == next_site
    maps, counts, disabled_providers = {}, {}, set()
    for name in TABLES:
        table = tables[name]
        maps[name] = {}
        rows = snapshot["tables"][name]
        for row in rows:
            if SECRETS & set(row):
                raise ValueError("Snapshot must not include credentials")
            values = values_for(table, row)
            for key, parent in LINKS.get(name, {}).items():
                values[key] = maps[parent][int(row[key])]
            if name == "image_model_providers":
                if urlparse(row["base_url"]).hostname == args.allowed_agent_host:
                    credential = credentials.get(row["code"])
                    if not credential or urlparse(credential["base_url"]).hostname != args.allowed_agent_host or not credential["encrypted_api_key"]:
                        raise ValueError("Matching allowed provider credential is missing: " + row["code"])
                    values["encrypted_api_key"] = credential["encrypted_api_key"]
                else:
                    disabled_providers.add(int(row["id"]))
                    values.update(base_url="", encrypted_api_key=None, is_active=False)
            if name == "image_models" and int(row["provider_id"]) in disabled_providers and row["is_active"]:
                raise ValueError("Active model uses an upstream outside the allowed agent: " + row["code"])
            if name == "payment_configs":
                credential = payment_credentials.get(row["provider"])
                if not credential:
                    raise ValueError("Payment credential source is missing")
                values.update(pid=credential["pid"], pkey=credential["pkey"],
                              notify_url=args.frontend_url.rstrip("/") + "/api/recharge/zpay/notify",
                              return_url=args.frontend_url.rstrip("/") + "/billing/recharge")
            maps[name][int(row["id"])] = await add(table, values)
        counts[name] = len(rows)
    agent_values = values_for(agent_table, agent)
    agent_values["admin_api_key"] = agent["admin_api_key"]
    await add(agent_table, agent_values)
    # Use the existing audit helper to retain the platform's audit format.
    from app.api.endpoints.admin_data import add_audit
    from app.models.admin_user import AdminUser
    admin = await db.get(AdminUser, admin_id)
    add_audit(db, admin, "create_site_config", "site_configs", site_id,
              f"Create {args.site_key}; snapshot={snapshot['source']}; agent={args.allowed_agent_host}; config only, no business data")
    return {"site_id": site_id, "site_key": args.site_key, "counts": counts,
            "disabled_legacy_providers": len(disabled_providers), "agent_host": args.allowed_agent_host,
            "text_group_id": agent["text_group_id"], "image_group_id": agent["image_group_id"]}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--site-key", required=True)
    parser.add_argument("--site-name", required=True)
    parser.add_argument("--frontend-url", required=True)
    parser.add_argument("--admin-url", required=True)
    parser.add_argument("--credentials-site", required=True)
    parser.add_argument("--agent-site", required=True)
    parser.add_argument("--allowed-agent-host", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with open(args.snapshot) as handle:
        snapshot = json.load(handle)
    async with AsyncSessionLocal() as db:
        try:
            result = await provision(db, snapshot, args)
            if args.apply:
                await db.commit()
            else:
                await db.rollback()
            print(json.dumps({"applied": args.apply, **result}, ensure_ascii=False))
        except SQLAlchemyError:
            await db.rollback()
            # SQLAlchemy tracebacks include bound parameters, which can contain keys.
            print("Configuration import failed; transaction rolled back (database error).", file=sys.stderr)
            raise SystemExit(1) from None
        except Exception:
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())
