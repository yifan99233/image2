"""Legacy requests and user-supplied metadata must never bypass moderation."""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_current_user
from app.api.routes import catalog
from app.db.session import get_db
from app.main import app


@pytest.fixture
async def gallery_client(monkeypatch):
    schema = 'gallery_review_' + uuid4().hex
    bootstrap = create_async_engine(os.environ['TEST_DATABASE_URL'])
    async with bootstrap.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA {schema}'))
        for table in ['image_tasks', 'image_models', 'users']:
            await conn.execute(text(f'CREATE TABLE {schema}.{table} (LIKE public.{table} INCLUDING ALL)'))
    engine = create_async_engine(os.environ['TEST_DATABASE_URL'], connect_args={'server_settings': {'search_path': schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        for task_id, site, user, requested, admin in [(1,1,1,False,None),(2,1,1,True,None),(3,1,1,True,8),(4,2,2,True,8),(5,1,2,False,None),(6,1,1,True,8)]:
            await db.execute(text("INSERT INTO image_tasks(id,task_no,site_id,user_id,model_id,prompt,status,output_image_url,is_gallery_featured,gallery_featured_by,timeout_seconds) VALUES(:id,:task,:site,:user,1,'test','succeeded','https://example.invalid/result.png',:requested,:admin,180)"), {'id':task_id,'task':f'IMG-{task_id}','site':site,'user':user,'requested':requested,'admin':admin})
        await db.execute(text('UPDATE image_tasks SET deleted_at=now() WHERE id=6'))
        await db.commit()
    async def database():
        async with sessions() as db:
            yield db
    old = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, site_id=1)
    monkeypatch.setattr(catalog, 'image_history_is_shared', AsyncMock(return_value=False))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            yield client, sessions
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)
        await engine.dispose()
        async with bootstrap.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        await bootstrap.dispose()


async def test_legacy_pending_deleted_and_other_tenant_never_appear(gallery_client):
    client, _ = gallery_client
    response = await client.get('/gallery')
    assert response.status_code == 200, response.text
    assert [row['id'] for row in response.json()['data']] == [3]
    response = await client.get('/works')
    works = {row['id']:row for row in response.json()['data']}
    assert set(works) == {1,2,3}
    assert works[2]['gallery_review_status'] == 'pending' and not works[2]['is_recommended']
    assert works[3]['gallery_review_status'] == 'approved' and works[3]['is_recommended']


async def test_request_cannot_forge_review_withdrawal_clears_approval(gallery_client):
    client, sessions = gallery_client
    response = await client.patch('/works/1', json={'is_recommended':True, 'gallery_featured_by':8, 'gallery_review_status':'approved'})
    assert response.status_code == 200, response.text
    assert response.json()['data']['gallery_review_status'] == 'pending'
    assert not response.json()['data']['is_recommended']
    assert [row['id'] for row in (await client.get('/gallery')).json()['data']] == [3]
    assert (await client.patch('/works/3', json={'is_recommended':True})).json()['data']['is_recommended']
    for flag, state in [(False,'none'),(True,'pending'),(False,'none')]:
        response = await client.patch('/works/3', json={'is_recommended':flag})
        assert response.json()['data']['gallery_review_status'] == state
        assert not response.json()['data']['is_recommended']
    assert (await client.get('/gallery')).json()['data'] == []
    async with sessions() as db:
        assert await db.scalar(text('SELECT gallery_featured_by FROM image_tasks WHERE id=3')) is None


async def test_owner_status_boolean_validation_and_auth(gallery_client):
    client, sessions = gallery_client
    for task_id in [4,5,6,999]:
        assert (await client.patch(f'/works/{task_id}', json={'is_recommended':True})).status_code == 404
    for value in ['false',1,None]:
        assert (await client.patch('/works/1', json={'is_recommended':value})).status_code == 400
    async with sessions() as db:
        await db.execute(text("UPDATE image_tasks SET status='running' WHERE id=1"))
        await db.commit()
    assert (await client.patch('/works/1', json={'is_recommended':True})).status_code == 400
    app.dependency_overrides.pop(get_current_user)
    assert (await client.get('/gallery')).status_code == 401
    assert (await client.patch('/works/2', json={'is_recommended':True})).status_code == 401
