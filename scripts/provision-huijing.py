"""Run inside admin-server after a database backup; dry-run unless --apply."""
import argparse
import asyncio
import json

from sqlalchemy import func, select, text

from app.api.endpoints.admin_data import SiteConfigRequest, create_site_config, site_configs_table
from app.db.session import AsyncSessionLocal
from app.models.admin_user import AdminUser
from app.services.customer_vip import tiers


async def main(apply: bool) -> None:
    async with AsyncSessionLocal() as db:
        if not apply:
            await db.execute(text("SET TRANSACTION READ ONLY"))
        await db.execute(text("SET LOCAL lock_timeout = '10s'"))
        await db.execute(text("SET LOCAL statement_timeout = '60s'"))
        admin = await db.scalar(select(AdminUser).where(
            AdminUser.id == 4, AdminUser.username == "yifan",
            AdminUser.system_super_admin.is_(True), AdminUser.is_active.is_(True),
        ))
        if admin is None:
            raise RuntimeError("Expected active system administrator not found")
        source = (await db.execute(select(site_configs_table).where(
            site_configs_table.c.id == 1, site_configs_table.c.site_key == "main",
            site_configs_table.c.is_default.is_(True), site_configs_table.c.is_enabled.is_(True),
        ))).mappings().one()
        existing = (await db.execute(select(site_configs_table).where(
            (site_configs_table.c.site_key == "huijing")
            | (site_configs_table.c.frontend_url == "https://art.hzhjai.com")
            | (site_configs_table.c.admin_url == "https://admin.hzhjai.com")
        ))).mappings().all()
        if existing:
            if len(existing) != 1 or any(existing[0][key] != value for key, value in {
                "site_key": "huijing", "site_name": "绘境 AI",
                "frontend_url": "https://art.hzhjai.com", "admin_url": "https://admin.hzhjai.com",
            }.items()):
                raise RuntimeError("Conflicting site exists; review before proceeding")
            print(json.dumps({"already_exists": True, "site_id": existing[0]["id"]}))
            return
        # This deployed bootstrap does not clone VIP tiers. Stop if the template
        # has acquired any since the operation was prepared, rather than omit them.
        if await db.scalar(select(func.count()).select_from(tiers).where(tiers.c.site_id == 1)):
            raise RuntimeError("Template VIP tiers changed; review bootstrap coverage")
        modules = source["enabled_modules"]
        payload = SiteConfigRequest(
            site_key="huijing", site_name="绘境 AI", template_site_id=1,
            frontend_url="https://art.hzhjai.com", admin_url="https://admin.hzhjai.com",
            is_default=False, is_enabled=True,
            enabled_modules=json.loads(modules) if isinstance(modules, str) else modules,
            site_icon_url=source["site_icon_url"],
        )
        print(json.dumps({"apply": apply, "site_key": payload.site_key,
            "site_name": payload.site_name, "frontend_url": payload.frontend_url,
            "admin_url": payload.admin_url, "template_site_id": 1}, ensure_ascii=False))
        if apply:
            response = await create_site_config(payload=payload, db=db, current_admin=admin)
            print(json.dumps({"created": True, "site_id": response.data["id"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
