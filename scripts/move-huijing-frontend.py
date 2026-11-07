"""Atomically move the Huijing frontend and payment URLs; dry-run by default."""
import argparse
import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy import select, text, update

from app.api.endpoints.admin_data import add_audit, payment_configs_table, site_configs_table
from app.db.session import AsyncSessionLocal
from app.models.admin_user import AdminUser

OLD = "https://hzhjai.com"
NEW = "https://art.hzhjai.com"


async def main(apply: bool) -> None:
    async with AsyncSessionLocal() as db:
        if not apply:
            await db.execute(text("SET TRANSACTION READ ONLY"))
        await db.execute(text("SET LOCAL lock_timeout = '10s'"))
        await db.execute(text("SET LOCAL statement_timeout = '30s'"))
        admin = await db.scalar(select(AdminUser).where(
            AdminUser.id == 4, AdminUser.username == "yifan",
            AdminUser.system_super_admin.is_(True), AdminUser.is_active.is_(True),
        ))
        if admin is None:
            raise RuntimeError("Expected system administrator missing")
        query = select(site_configs_table).where(site_configs_table.c.id == 12)
        site = (await db.execute(query.with_for_update() if apply else query)).mappings().one()
        if (site["site_key"] != "huijing" or site["is_default"]
                or site["admin_url"] != "https://admin.hzhjai.com"
                or site["frontend_url"] not in (OLD, NEW)):
            raise RuntimeError("Unexpected tenant configuration")
        conflict = await db.scalar(select(site_configs_table.c.id).where(
            site_configs_table.c.id != 12,
            (site_configs_table.c.frontend_url == NEW) | (site_configs_table.c.admin_url == NEW),
        ))
        if conflict is not None:
            raise RuntimeError("Target domain belongs to another tenant")
        query = select(payment_configs_table.c.id, payment_configs_table.c.notify_url,
                       payment_configs_table.c.return_url).where(payment_configs_table.c.site_id == 12)
        payment = (await db.execute(query.with_for_update() if apply else query)).mappings().one()
        urls = {"notify_url": "/api/recharge/zpay/notify", "return_url": "/billing/recharge"}
        for key, path in urls.items():
            if payment[key] not in (OLD + path, NEW + path):
                raise RuntimeError("Unexpected payment URL: " + key)
        print(json.dumps({"apply": apply, "site_id": 12, "before": site["frontend_url"],
                          "after": NEW, "payment_urls": {k: NEW + v for k, v in urls.items()}}))
        if not apply:
            return
        now = datetime.now(timezone.utc)
        await db.execute(update(site_configs_table).where(site_configs_table.c.id == 12).values(
            frontend_url=NEW, updated_by=admin.id, updated_at=now))
        await db.execute(update(payment_configs_table).where(
            payment_configs_table.c.id == payment["id"], payment_configs_table.c.site_id == 12,
        ).values(**{k: NEW + v for k, v in urls.items()}, updated_by=admin.id, updated_at=now))
        add_audit(db, admin, "update_site_frontend_domain", "site_configs", 12,
                  f"Frontend {site['frontend_url']} -> {NEW}; payment URLs synchronized")
        await db.commit()
        print(json.dumps({"applied": True, "site_id": 12}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
