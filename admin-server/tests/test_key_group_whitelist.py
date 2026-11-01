import os
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker

from app.api.endpoints import admin_data
from app.core.exceptions import AppException


@pytest.mark.parametrize('value',[None,'1,2',{},[True],[-1],[0],[1.2],['42'],list(range(1,202))])
def test_invalid_whitelist_is_rejected(value):
    with pytest.raises(AppException): admin_data.normalize_key_group_whitelist(value)


def test_normalized_defaults_and_serialization():
    assert admin_data.normalize_key_group_whitelist([42,37,42])==[37,42]
    assert admin_data.default_agent_config()['key_group_whitelist']==[]
    assert admin_data.agent_config_out({'key_group_whitelist':[42]})['key_group_whitelist']==[42]


@pytest.fixture
async def db(monkeypatch):
    url=os.environ['TEST_DATABASE_URL']
    assert urlparse(url).hostname in ('localhost','127.0.0.1') and 'test' in urlparse(url).path
    engine=create_async_engine(url)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    async def site(db,request,admin): return request.site_id
    monkeypatch.setattr(admin_data,'current_admin_config_site_id',site)
    monkeypatch.setattr(admin_data,'fetch_agent_groups',lambda base,key:[{'id':i,'is_active':i!=99} for i in (36,37,42,43,99)])
    async with sessions() as session:
        await session.execute(text('DELETE FROM agent_configs WHERE site_id IN (901,902)'))
        await session.commit()
        yield session
    await engine.dispose()


def payload(**changes):
    return dict(is_enabled=True,image_billing_enabled=False,base_url='https://agent.example.test',admin_api_key='test-admin',
                credit_to_agent_rate=100,text_group_id=37,image_group_id=36,**changes)


async def save(db,site=901,**changes):
    return await admin_data.update_agent_config(payload(**changes),SimpleNamespace(site_id=site),db,
                                               SimpleNamespace(id=1,username='test-admin'))


async def test_persist_reload_default_union_and_site_isolation(db):
    result=await save(db,key_group_whitelist=[37,42,42,36])
    assert result.data['key_group_whitelist']==[42]
    await save(db,site=902,key_group_whitelist=[43])
    assert (await save(db)).data['key_group_whitelist']==[42] # older client preserves extras
    assert (await save(db,key_group_whitelist=[])).data['key_group_whitelist']==[]
    assert await db.scalar(text('SELECT key_group_whitelist FROM agent_configs WHERE site_id=902'))==[43]


@pytest.mark.parametrize('group_id',[999,99])
async def test_missing_or_inactive_group_rejected_without_write(db,group_id):
    await save(db,key_group_whitelist=[42])
    with pytest.raises(AppException) as error:
        await save(db,key_group_whitelist=[group_id])
    assert error.value.message == '白名单包含不可用分组，请重新查询分组'
    await db.rollback()
    assert await db.scalar(text('SELECT key_group_whitelist FROM agent_configs WHERE site_id=901'))==[42]


async def test_changed_service_revalidates_preserved_whitelist(db,monkeypatch):
    await save(db,key_group_whitelist=[42])
    checked=[]
    def groups(base,key):
        checked.append(base)
        return [{'id':36,'is_active':True},{'id':37,'is_active':True}]
    monkeypatch.setattr(admin_data,'fetch_agent_groups',groups)
    changed=payload()
    changed['base_url']='https://different-agent.example.test'
    with pytest.raises(AppException) as error:
        await admin_data.update_agent_config(changed,SimpleNamespace(site_id=901),db,SimpleNamespace(id=1,username='admin'))
    assert error.value.message=='白名单包含不可用分组，请重新查询分组'
    assert checked==['https://different-agent.example.test']
    await db.rollback()
    assert await db.scalar(text('SELECT base_url FROM agent_configs WHERE site_id=901'))=='https://agent.example.test'
