from decimal import Decimal

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select, text, update

from app.api.routes import catalog
from app.models.credit import UserCreditAccount
from app.models.image_batch_upload import ImageBatchUpload
from app.models.user import User
from app.services import image_batch_uploads as uploads
from test_batch_groups import sessions
from test_batch_progress import batch_client
from test_batch_uploads import manifest, prepare_model, accept


async def prices(db):
    # Generic price is newer: a quality-specific price must still win.
    for resolution in ('1k', '2k', '4k'):
        for quality, cost in [('low', 3), ('medium', 5), ('high', 6)]:
            await db.execute(text("""INSERT INTO image_model_prices
                (site_id,model_id,work_type,resolution,aspect_ratio,output_count,credit_cost,quality,version,change_reason,effective_at)
                VALUES(1,5,'text_to_image',:resolution,'1:1',1,:cost,:quality,1,'quality test',now()-interval '1 day')"""),
                dict(resolution=resolution, quality=quality, cost=cost))
    await db.commit()


async def test_quote_matrix_quality_precedence_and_legacy_fallback(sessions, batch_client):
    # Existing models retain their generic price at every quality.
    for quality in ('low', 'medium', 'high', 'auto'):
        response = await batch_client.post('/models/5/quote', json={**manifest(1), 'quality': quality})
        assert response.json()['data']['credit_cost'] == 7
    async with sessions() as db:
        await prices(db)
    for resolution in ('1k', '2k', '4k'):
        for quality, cost in [('low', 3), ('medium', 5), ('high', 6), ('auto', 5)]:
            response = await batch_client.post('/models/5/quote', json={**manifest(1), 'resolution': resolution, 'quality': quality})
            assert response.status_code == 200
            value = response.json()['data']
            assert value['credit_cost'] == cost
            assert value['pricing']['requested_quality'] == quality
            assert value['pricing']['price_quality'] == ('medium' if quality == 'auto' else quality)


@pytest.mark.parametrize('quality,cost', [('low', 3), ('medium', 5), ('high', 6), ('auto', 5)])
async def test_single_debit_and_original_refund_use_requested_quality(sessions, quality, cost):
    async with sessions() as db:
        await prices(db)
        user = await db.get(User, 1)
        result = await catalog.create_image_task({**manifest(1), 'work_type': 'text_to_image', 'prompt': 'test', 'quality': quality}, BackgroundTasks(), user, db)
        task = (await db.execute(select(catalog.image_tasks_table).where(catalog.image_tasks_table.c.id == result.data['id']))).mappings().one()
        account = await db.scalar(select(UserCreditAccount).where(UserCreditAccount.user_id == 1))
        assert task['credit_cost'] == cost
        assert task['pricing_snapshot']['requested_quality'] == quality
        assert account.balance == 20000 - cost
        await db.execute(text("UPDATE image_model_prices SET credit_cost=99 WHERE quality!='any'"))
        await catalog.refund_image_task_credits(db, 1, task['task_no'], task['credit_cost'])
        await db.commit()
        await db.refresh(account)
        assert account.balance == 20000
        assert account.total_consumed == 0


async def test_batch_freezes_high_price_and_retry_requotes_same_quality(sessions):
    async with sessions() as db:
        await prices(db)
    value = {**manifest(3), 'quality': 'high'}
    await accept(sessions, value)
    async with sessions() as db:
        job = await db.scalar(select(ImageBatchUpload).where(ImageBatchUpload.batch_id == value['batch_id']))
        assert Decimal(job.payload['credit_cost']) == 6
        await db.execute(text("UPDATE image_model_prices SET credit_cost=9 WHERE quality='high'"))
        await uploads.materialize_tasks(db, job, None)
        account = await db.scalar(select(UserCreditAccount).where(UserCreditAccount.user_id == 1))
        assert account.balance == 20000 - 18
        tasks = (await db.execute(select(catalog.image_tasks_table))).mappings().all()
        assert len(tasks) == 3
        assert all(t['credit_cost'] == 6 and t['pricing_snapshot']['requested_quality'] == 'high' for t in tasks)
        await db.execute(update(catalog.image_tasks_table).values(status='failed'))
        user = await db.get(User, 1)
        sources = await catalog.retry_source_tasks(db, user, value['batch_id'])
        repriced, _ = await catalog.price_retry_sources(db, user, sources)
        assert len(repriced) == 3
        assert all(t['credit_cost'] == 9 for t in repriced)
