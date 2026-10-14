import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.admin_user import AdminRole, AdminUser
from app.services.security import hash_password


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        existing = await session.scalar(select(AdminUser).where(AdminUser.username == settings.super_admin_username))
        if existing:
            print(f"super admin already exists: {existing.username}")
            return

        admin = AdminUser(
            username=settings.super_admin_username,
            email=settings.super_admin_email,
            password_hash=hash_password(settings.super_admin_password),
            role=AdminRole.super_admin,
            is_active=True,
        )
        session.add(admin)
        await session.commit()
        print(f"created super admin: {admin.username}")


if __name__ == "__main__":
    asyncio.run(seed())

