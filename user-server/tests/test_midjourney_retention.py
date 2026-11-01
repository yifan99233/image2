import json

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import pytest

from test_image_retention import sessions, seed, run, Store


async def four_outputs(sessions):
    images = [await seed(sessions) for _ in range(4)]
    task_id = images[0][1]
    async with sessions() as db:
        await db.execute(text('DELETE FROM image_tasks WHERE id=ANY(:ids)'), {'ids': [item[1] for item in images[1:]]})
        await db.execute(text('UPDATE image_tasks SET output_image_assets=cast(:assets AS jsonb) WHERE id=:id'),
                         {'id': task_id, 'assets': json.dumps([{'url': item[2]} for item in images])})
        await db.commit()
    return images


async def test_collected_mj_group_protects_every_output(sessions):
    images = await four_outputs(sessions)
    async with sessions() as db:
        await db.execute(text('UPDATE image_tasks SET is_collected=true WHERE id=:id'), {'id': images[0][1]})
        await db.commit()
    assert (await run(sessions, apply=True, client=Store()))['eligible'] == 0


async def test_uncollected_mj_group_expires_all_four_outputs(sessions):
    images = await four_outputs(sessions)
    store = Store()
    report = await run(sessions, apply=True, client=store)
    assert report['deleted'] == 4 and len(store.deleted) == 4
    async with sessions() as db:
        assert await db.scalar(text('SELECT output_expired_at FROM image_tasks WHERE id=:id'), {'id': images[0][1]})


async def test_secondary_mj_output_tombstone_blocks_collecting_the_group(sessions):
    images = await four_outputs(sessions)
    async with sessions() as db:
        await db.execute(text('UPDATE image_assets SET retention_pending_at=now() WHERE id=:id'), {'id': images[3][0]})
        await db.commit()
        with pytest.raises(IntegrityError, match='expired'):
            await db.execute(text('UPDATE image_tasks SET is_collected=true WHERE id=:id'), {'id': images[0][1]})
        await db.rollback()
