import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, browser_exports, canvas, catalog, credits, feedback, gateway, health, invite, leads, materials, opencode, prompt, recharge, rewards, site, team, team_console, uploads, ux
from app.api.routes import redemption
from app.core.config import settings
from app.core.exceptions import install_exception_handlers
from app.core.redis import redis_client
from app.db.session import engine
from app.services.gateway_proxy import close_gateway_http_client
from app.services.image_batch_uploads import batch_upload_worker_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.image_retention import retention_loop
    retention_task = asyncio.create_task(retention_loop()) if settings.image_retention_enabled else None
    reaper_task: asyncio.Task | None = None
    dispatcher_task: asyncio.Task | None = None
    upload_worker_task: asyncio.Task | None = None
    if settings.image_task_reaper_enabled:
        reaper_task = asyncio.create_task(catalog.image_task_reaper_loop())
    if settings.image_task_dispatcher_enabled:
        dispatcher_task = asyncio.create_task(catalog.image_task_dispatcher_loop())
        upload_worker_task = asyncio.create_task(batch_upload_worker_loop())
    try:
        yield
    finally:
        if retention_task is not None:
            retention_task.cancel()
            await asyncio.gather(retention_task, return_exceptions=True)
        if upload_worker_task is not None:
            upload_worker_task.cancel()
            await asyncio.gather(upload_worker_task, return_exceptions=True)
        if dispatcher_task is not None:
            dispatcher_task.cancel()
            try:
                await dispatcher_task
            except asyncio.CancelledError:
                pass
        if reaper_task is not None:
            reaper_task.cancel()
            try:
                await reaper_task
            except asyncio.CancelledError:
                pass
        # A claimed task is tracked separately from the dispatcher loop. Stop
        # those child coroutines as well so shutdown does not leave DB/Redis
        # work running against pools that are about to be disposed.
        async with catalog.image_task_dispatcher_tasks_lock:
            worker_tasks = list(catalog.image_task_dispatcher_tasks)
            for worker_task in worker_tasks:
                worker_task.cancel()
        if worker_tasks:
            await asyncio.gather(*worker_tasks, return_exceptions=True)
        async with catalog.image_task_dispatcher_tasks_lock:
            catalog.image_task_dispatcher_tasks.clear()
        await close_gateway_http_client()
        await redis_client.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(credits.router)
    app.include_router(redemption.router)
    app.include_router(uploads.router)
    app.include_router(materials.router)
    app.include_router(team.router)
    app.include_router(invite.router)
    app.include_router(leads.router)
    app.include_router(opencode.router)
    app.include_router(team_console.router)
    app.include_router(rewards.router)
    app.include_router(site.router)
    app.include_router(ux.router)
    app.include_router(feedback.router)
    app.include_router(recharge.router)
    app.include_router(catalog.router)
    app.include_router(browser_exports.router)
    app.include_router(canvas.router)
    app.include_router(prompt.router)
    app.include_router(gateway.router)
    return app


app = create_app()
