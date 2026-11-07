import asyncio
import json
from copy import deepcopy
from time import monotonic

from fastapi import APIRouter, Depends, Request
from sqlalchemy import BigInteger, Boolean, Column, DateTime, MetaData, String, Table, Text, desc, or_, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.services.site_scope import request_host, site_host_aliases

router = APIRouter(prefix="/site", tags=["site"])

# Site configuration is read by every browser boot.  Keep this cache local to
# one user-server process so the hot path does not hold a database connection
# for every request.  The short TTL gives admin-server updates a bounded
# propagation delay without requiring cross-process cache invalidation.
SITE_CONFIG_CACHE_TTL_SECONDS = 30.0
SITE_CONFIG_CACHE_MAX_ENTRIES = 256
_site_config_cache: dict[str, tuple[float, dict]] = {}
_site_config_cache_lock = asyncio.Lock()

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


def default_site_config() -> dict:
    return {
        "id": 1,
        "site_key": "main",
        "site_name": "艺源",
        "site_icon_url": "/image2ai-icon.svg",
        "frontend_url": "",
        "admin_url": "",
        "is_default": True,
        "is_enabled": True,
        "enabled_modules": default_site_modules(),
        "support_qq": "1223362085",
        "support_wechat": "YiTiao1024L",
        "support_wechat_qrcode_url": "/wechat-qrcode.png",
        "support_email": "support@example.com",
        "homepage_case_carousels": [
            [
                {"title": "电商套图", "subtitle": "主图、场景图、详情页素材统一生成", "image_url": "", "file_url": "", "link_url": "", "tone": "blue"},
                {"title": "产品效果图", "subtitle": "上传商品图后快速延展应用场景", "image_url": "", "file_url": "", "link_url": "", "tone": "orange"},
            ],
            [
                {"title": "图片二次优化", "subtitle": "改背景、换氛围、补细节", "image_url": "", "file_url": "", "link_url": "", "tone": "cyan"},
                {"title": "案例展示", "subtitle": "生成前后效果直接对比", "image_url": "", "file_url": "", "link_url": "", "tone": "green"},
            ],
        ],
        "homepage_batch_banners": [],
        "lead_case_materials": default_lead_case_materials(),
        "opencode_install_video": default_opencode_install_video(),
        "system_announcement": default_system_announcement(),
        "updated_at": None,
    }


def default_lead_case_materials() -> list[dict]:
    return [
        {"title": "家具", "subtitle": "家居门店获客案例", "file_url": "", "cover_url": "", "link_url": "", "tags": [], "tone": "blue"},
        {"title": "大健康", "subtitle": "养生门店转化案例", "file_url": "", "cover_url": "", "link_url": "", "tags": [], "tone": "green"},
        {"title": "珠宝", "subtitle": "高客单私域案例", "file_url": "", "cover_url": "", "link_url": "", "tags": [], "tone": "orange"},
        {"title": "考公", "subtitle": "课程线索转化案例", "file_url": "", "cover_url": "", "link_url": "", "tags": [], "tone": "cyan"},
    ]


def default_opencode_install_video() -> dict:
    return {
        "title": "从需求到交付的自动化流程",
        "subtitle": "演示 Codex定制版如何读取需求、修改文件、运行验证并输出结果。",
        "file_url": "",
        "cover_url": "",
        "link_url": "",
        "tags": ["写代码", "做文件", "查资料"],
        "tone": "blue",
    }


def default_system_announcement() -> dict:
    return {"is_enabled": False, "title": "", "content": "", "image_url": ""}


def default_site_modules() -> list[str]:
    return [
        "dashboard",
        "gallery",
        "image_edit",
        "text_to_image",
        "text_to_video",
        "image_to_video",
        "batch_generate",
        "batch_edit",
        "works",
        "leads",
        "opencode",
        "feedback",
        "support",
        "signin",
        "invite",
        "recharge",
    ]


def normalize_site_modules(value) -> list[str]:
    allowed = set(default_site_modules())
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else default_site_modules()
        except json.JSONDecodeError:
            return default_site_modules()
    if not isinstance(value, list):
        return default_site_modules()
    modules = [str(module).strip() for module in value if str(module).strip() in allowed]
    return modules or default_site_modules()


def normalize_homepage_case_carousels(value) -> list[list[dict]]:
    defaults = default_site_config()["homepage_case_carousels"]
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else defaults
        except json.JSONDecodeError:
            return defaults
    if not isinstance(value, list):
        return defaults
    normalized_groups: list[list[dict]] = []
    for group in value[:2]:
        if not isinstance(group, list):
            normalized_groups.append([])
            continue
        normalized_items: list[dict] = []
        for item in group[:4]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            tone = str(item.get("tone") or "blue").strip()
            normalized_items.append(
                {
                    "title": title[:80],
                    "subtitle": str(item.get("subtitle") or "").strip()[:160],
                    "image_url": str(item.get("image_url") or "").strip()[:2048],
                    "file_url": str(item.get("file_url") or "").strip()[:2048],
                    "link_url": str(item.get("link_url") or "").strip()[:2048],
                    "tone": tone if tone in {"blue", "orange", "cyan", "green"} else "blue",
                }
            )
        normalized_groups.append(normalized_items)
    while len(normalized_groups) < 2:
        normalized_groups.append([])
    return [group or defaults[index] for index, group in enumerate(normalized_groups[:2])]


def normalize_content_materials(value, defaults: list[dict], *, limit: int = 4) -> list[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else defaults
        except json.JSONDecodeError:
            return defaults
    if not isinstance(value, list):
        return defaults
    normalized: list[dict] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        tone = str(item.get("tone") or "blue").strip()
        tags = item.get("tags") if isinstance(item.get("tags"), list) else []
        normalized.append(
            {
                "title": title[:80],
                "subtitle": str(item.get("subtitle") or "").strip()[:200],
                "file_url": str(item.get("file_url") or "").strip()[:2048],
                "cover_url": str(item.get("cover_url") or "").strip()[:2048],
                "link_url": str(item.get("link_url") or "").strip()[:2048],
                "tags": [str(tag).strip()[:24] for tag in tags if str(tag).strip()][:6],
                "tone": tone if tone in {"blue", "orange", "cyan", "green"} else "blue",
            }
        )
    return normalized or defaults


def normalize_content_material(value, default: dict) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else default
        except json.JSONDecodeError:
            return default
    if not isinstance(value, dict):
        return default
    return normalize_content_materials([value], [default], limit=1)[0]


def normalize_system_announcement(value) -> dict:
    default = default_system_announcement()
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else default
        except json.JSONDecodeError:
            return default
    if not isinstance(value, dict):
        return default
    content = str(value.get("content") or "").strip()[:2000]
    return {
        "is_enabled": bool(value.get("is_enabled")) and bool(content),
        "title": str(value.get("title") or "").strip()[:80],
        "content": content,
        "image_url": str(value.get("image_url") or "").strip()[:2048],
    }


def site_config_out(row) -> dict:
    if not row:
        return default_site_config()
    get_value = row.get if hasattr(row, "get") else lambda key, default=None: getattr(row, key, default)
    defaults = default_site_config()
    return {
        "id": get_value("id") or defaults["id"],
        "site_key": get_value("site_key") or defaults["site_key"],
        "site_name": get_value("site_name") or defaults["site_name"],
        "site_icon_url": get_value("site_icon_url") or defaults["site_icon_url"],
        "frontend_url": get_value("frontend_url") or "",
        "admin_url": get_value("admin_url") or "",
        "is_default": bool(get_value("is_default")),
        "is_enabled": bool(get_value("is_enabled", True)),
        "enabled_modules": normalize_site_modules(get_value("enabled_modules")),
        "support_qq": get_value("support_qq") or "",
        "support_wechat": get_value("support_wechat") or "",
        "support_wechat_qrcode_url": get_value("support_wechat_qrcode_url") or "",
        "support_email": get_value("support_email") or "",
        "homepage_case_carousels": normalize_homepage_case_carousels(get_value("homepage_case_carousels")),
        "homepage_batch_banners": normalize_content_materials(get_value("homepage_batch_banners"), [], limit=8),
        "lead_case_materials": normalize_content_materials(get_value("lead_case_materials"), defaults["lead_case_materials"]),
        "opencode_install_video": normalize_content_material(get_value("opencode_install_video"), defaults["opencode_install_video"]),
        "system_announcement": normalize_system_announcement(get_value("system_announcement")),
        "updated_at": get_value("updated_at").isoformat() if get_value("updated_at") else None,
    }


def _site_config_cache_key(request: Request) -> str:
    """Return a stable host key while keeping alias lookups together."""

    host = request_host(request)
    aliases = site_host_aliases(host)
    return f"host:{aliases[0]}" if aliases else "default"


def _cached_site_config(cache_key: str) -> dict | None:
    cached = _site_config_cache.get(cache_key)
    if cached is None:
        return None
    cached_at, value = cached
    if monotonic() - cached_at >= SITE_CONFIG_CACHE_TTL_SECONDS:
        _site_config_cache.pop(cache_key, None)
        return None
    # The response serializer should not be able to mutate the shared value.
    return deepcopy(value)


def _store_site_config(cache_key: str, value: dict) -> None:
    if len(_site_config_cache) >= SITE_CONFIG_CACHE_MAX_ENTRIES and cache_key not in _site_config_cache:
        _site_config_cache.pop(next(iter(_site_config_cache)), None)
    _site_config_cache[cache_key] = (monotonic(), deepcopy(value))


async def _load_site_config(request: Request, db: AsyncSession) -> dict:
    host = request_host(request)
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
            return site_config_out(row)
    row = await db.execute(select(site_configs_table).where(site_configs_table.c.is_default.is_(True)).limit(1))
    default_row = row.mappings().first()
    if default_row:
        return site_config_out(default_row)
    row = await db.execute(select(site_configs_table).where(site_configs_table.c.id == 1))
    return site_config_out(row.mappings().first())


@router.get("/config", response_model=StandardResponse[dict])
async def site_config(request: Request, db: AsyncSession = Depends(get_db)) -> StandardResponse[dict]:
    cache_key = _site_config_cache_key(request)
    cached = _cached_site_config(cache_key)
    if cached is not None:
        return ok(cached)
    # Serialize misses per process to avoid a cold-start stampede.  The lock
    # is held only while loading one small config row and is bypassed entirely
    # on the normal cache-hit path.
    async with _site_config_cache_lock:
        cached = _cached_site_config(cache_key)
        if cached is not None:
            return ok(cached)
        try:
            value = await _load_site_config(request, db)
        except (OperationalError, ProgrammingError) as error:
            if "site_configs" not in str(error).lower():
                raise
            value = default_site_config()
        _store_site_config(cache_key, value)
        return ok(deepcopy(value))
