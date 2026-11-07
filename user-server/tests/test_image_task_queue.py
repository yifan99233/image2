from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, update

from app.api.routes import catalog
from app.core.exceptions import BusinessError
from app.models.user import User
from test_batch_groups import sessions
from test_batch_progress import seed


async def test_reaper_preserves_old_durable_queue_and_still_reaps_running_tasks(sessions, monkeypatch):
    now = datetime.now(UTC)
    old = now - timedelta(hours=2)
    await seed(sessions, "unclaimed", ["queued"], created_at=old)
    await seed(sessions, "legacy-queued", ["queued"], created_at=old,
               worker_started_at=old, worker_heartbeat_at=old)
    await seed(sessions, "stale-running", ["running"], created_at=old,
               worker_started_at=old, worker_heartbeat_at=old)
    await seed(sessions, "expired-running", ["running"], created_at=old,
               worker_started_at=old, worker_heartbeat_at=now, deadline_at=now - timedelta(seconds=1))
    await seed(sessions, "live-running", ["running"], created_at=old,
               worker_started_at=old, worker_heartbeat_at=now, deadline_at=now + timedelta(seconds=180))
    refund = AsyncMock()
    monkeypatch.setattr(catalog, "refund_image_task_credits", refund)
    async with sessions() as db:
        assert await catalog.reap_stale_image_tasks(db, now=now) == 2
        rows = (await db.execute(select(catalog.image_tasks_table.c.batch_id,
                                        catalog.image_tasks_table.c.status))).all()
    assert dict(rows) == {"unclaimed": "queued", "legacy-queued": "queued",
                          "stale-running": "failed", "expired-running": "failed",
                          "live-running": "running"}
    assert refund.await_count == 2


async def test_old_5000_task_batch_counts_toward_queue_capacity(sessions, monkeypatch):
    await seed(sessions, "large-old-batch", ["queued"] * 5000,
               created_at=datetime.now(UTC) - timedelta(hours=2))
    monkeypatch.setattr(catalog.settings, "image_task_queue_limit_per_user", 5000)
    async with sessions() as db:
        with pytest.raises(BusinessError) as caught:
            await catalog.ensure_user_image_task_capacity(db, 1, 1)
    assert caught.value.code == 42911


@pytest.mark.parametrize("free_slots", [1, 64, 500])
async def test_old_batch_dispatch_claims_only_free_slots_and_continues_after_completion(sessions, free_slots):
    await seed(sessions, "large-old-batch", ["queued"] * 5000,
               created_at=datetime.now(UTC) - timedelta(hours=2))
    async with sessions() as db:
        await db.execute(update(User).where(User.id == 1).values(image_concurrency_limit=5000))
        await db.execute(update(catalog.image_models_table).where(catalog.image_models_table.c.id == 5)
                         .values(concurrency_limit=1000))
        await db.commit()
        claimed = await catalog.queued_image_task_payloads_for_dispatch(db, limit=free_slots)
        assert len(claimed) == free_slots
        ids = [row["task_id"] for row in claimed]
        statuses = dict((await db.execute(select(catalog.image_tasks_table.c.status, func.count())
                                         .group_by(catalog.image_tasks_table.c.status))).all())
        assert statuses == {"queued": 5000 - free_slots, "running": free_slots}
        rows = (await db.execute(select(catalog.image_tasks_table)
                                .where(catalog.image_tasks_table.c.id.in_(ids)))).mappings().all()
        assert all(row["worker_started_at"] and row["worker_heartbeat_at"]
                   and row["deadline_at"] is None for row in rows)
        await db.execute(update(catalog.image_tasks_table).where(catalog.image_tasks_table.c.id.in_(ids))
                         .values(status="succeeded"))
        await db.commit()
        next_claim = await catalog.queued_image_task_payloads_for_dispatch(db, limit=free_slots)
        assert len(next_claim) == free_slots
        assert not set(ids).intersection(row["task_id"] for row in next_claim)


@pytest.mark.parametrize("already_running", [False, True])
@pytest.mark.parametrize("blocked_by", ["user", "model"])
async def test_large_saturated_batch_does_not_hide_later_eligible_tasks(sessions, already_running, blocked_by):
    """Cross the old 2,000-row window without bypassing either budget."""
    now = datetime.now(UTC)
    async with sessions() as db:
        await db.execute(update(User).where(User.id == 1).values(
            image_concurrency_limit=1 if blocked_by == "user" else 1000))
        await db.execute(update(User).where(User.id == 2).values(image_concurrency_limit=1000))
        await db.execute(update(catalog.image_models_table).where(catalog.image_models_table.c.id == 5)
                         .values(concurrency_limit=1 if blocked_by == "model" else 1000))
        await db.execute(catalog.image_models_table.insert().values(
            id=6, site_id=1, provider_id=1, name="other model", code="other-model",
            vendor_model="other", work_type="image_edit", concurrency_limit=3,
            is_active=True, is_public=True))
        await db.commit()
    if already_running:
        await seed(sessions, "in-flight", ["running"], worker_started_at=now, worker_heartbeat_at=now)
    await seed(sessions, "blocked", ["queued"] * 5000, created_at=now - timedelta(hours=2))
    # Same model / different user tests user isolation; same user / different
    # model tests model isolation and retains the shared user budget.
    eligible_user = 2 if blocked_by == "user" else 1
    eligible_model = 5 if blocked_by == "user" else 6
    await seed(sessions, "eligible", ["queued"] * 4, user_id=eligible_user,
               model_id=eligible_model, created_at=now)
    async with sessions() as db:
        claimed = await catalog.queued_image_task_payloads_for_dispatch(db, limit=500)
        eligible = [row for row in claimed if row["task_no"].startswith("eligible-")]
        expected = 4 if blocked_by == "user" else 3
        assert len(eligible) == expected
        assert [row["prompt"] for row in eligible] == [f"prompt-{i}" for i in range(expected)]
        assert len(claimed) == expected + (0 if already_running else 1)
        assert await db.scalar(select(func.count()).select_from(catalog.image_tasks_table).where(
            catalog.image_tasks_table.c.batch_id == "blocked", catalog.image_tasks_table.c.status == "running")) == (0 if already_running else 1)
        # A second claim must count the previous transaction's work and never
        # duplicate tasks or exceed model 6's limit of three.
        following = await catalog.queued_image_task_payloads_for_dispatch(db, limit=500)
        assert following == []


async def test_dispatch_respects_other_dispatcher_advisory_lock(sessions):
    await seed(sessions, "queued", ["queued"])
    async with sessions() as owner, sessions() as contender:
        await owner.execute(catalog.text("SELECT pg_advisory_xact_lock(:key)"),
                            {"key": catalog.IMAGE_TASK_DISPATCHER_ADVISORY_LOCK_KEY})
        assert await catalog.queued_image_task_payloads_for_dispatch(contender, limit=500) == []
        await owner.rollback()
        assert len(await catalog.queued_image_task_payloads_for_dispatch(contender, limit=500)) == 1
