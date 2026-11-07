from fastapi import APIRouter, Depends
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, MetaData, Table, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.responses import StandardResponse, ok
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/ux", tags=["ux"])

DEFAULT_MAX_BATCH_TASKS = 20000
DEFAULT_QINIU_STORAGE_ENABLED = False

shared_metadata = MetaData()
user_experience_configs_table = Table(
    "user_experience_configs",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("max_batch_tasks", Integer),
    Column("qiniu_storage_enabled", Boolean),
    Column("updated_at", DateTime(timezone=True)),
)


def default_ux_config() -> dict:
    return {
        "max_batch_tasks": DEFAULT_MAX_BATCH_TASKS,
        "batch_upload_max_bytes": settings.batch_upload_max_bytes,
        "batch_upload_max_prompt_chars": settings.batch_upload_max_prompt_chars,
        "qiniu_storage_enabled": DEFAULT_QINIU_STORAGE_ENABLED,
        "updated_at": None,
    }


def ux_config_out(row) -> dict:
    if row is None:
        return default_ux_config()
    get_value = row.get if hasattr(row, "get") else lambda key, default=None: getattr(row, key, default)
    max_batch_tasks = int(get_value("max_batch_tasks") or DEFAULT_MAX_BATCH_TASKS)
    if max_batch_tasks < 1:
        max_batch_tasks = DEFAULT_MAX_BATCH_TASKS
    updated_at = get_value("updated_at")
    return {
        "max_batch_tasks": max_batch_tasks,
        "batch_upload_max_bytes": settings.batch_upload_max_bytes,
        "batch_upload_max_prompt_chars": settings.batch_upload_max_prompt_chars,
        "qiniu_storage_enabled": bool(get_value("qiniu_storage_enabled") or False),
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


async def get_max_batch_tasks(db: AsyncSession, site_id: int | None) -> int:
    if not site_id:
        return DEFAULT_MAX_BATCH_TASKS
    try:
        result = await db.execute(
            select(user_experience_configs_table.c.max_batch_tasks).where(
                user_experience_configs_table.c.site_id == site_id
            )
        )
        value = result.scalar_one_or_none()
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if "user_experience_configs" in str(error).lower():
            return DEFAULT_MAX_BATCH_TASKS
        raise
    max_batch_tasks = int(value or DEFAULT_MAX_BATCH_TASKS)
    return max_batch_tasks if max_batch_tasks >= 1 else DEFAULT_MAX_BATCH_TASKS


async def get_qiniu_storage_enabled(db: AsyncSession, site_id: int | None) -> bool:
    """Return whether this site writes new images to Qiniu.

    Admin UX config is the source of truth. When the table/column is missing or
    site_id is empty, fall back to the env upload_storage_provider for
    backward compatibility.
    """
    if not site_id:
        from app.core.config import settings

        return settings.upload_storage_provider.strip().lower() == "qiniu"
    try:
        result = await db.execute(
            select(user_experience_configs_table.c.qiniu_storage_enabled).where(
                user_experience_configs_table.c.site_id == site_id
            )
        )
        value = result.scalar_one_or_none()
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        message = str(error).lower()
        if "user_experience_configs" in message or "qiniu_storage_enabled" in message:
            from app.core.config import settings

            return settings.upload_storage_provider.strip().lower() == "qiniu"
        raise
    if value is None:
        from app.core.config import settings

        return settings.upload_storage_provider.strip().lower() == "qiniu"
    return bool(value)


@router.get("/config", response_model=StandardResponse[dict])
async def user_experience_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    try:
        result = await db.execute(
            select(user_experience_configs_table).where(user_experience_configs_table.c.site_id == current_user.site_id)
        )
        return ok(ux_config_out(result.mappings().first()))
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if "user_experience_configs" in str(error).lower():
            return ok(default_ux_config())
        raise
