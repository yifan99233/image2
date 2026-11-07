from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api.routes import opencode
from app.core.exceptions import BusinessError
from app.models.agent import UserAgentApiKey
from app.services.agent_openapi import AgentAPIGroup, AgentAPIKey
from app.services.agent_provisioning import _configured_group_ids, _sync_configured_allowed_groups


def config(extra=None):
    return SimpleNamespace(text_group_id=37,image_group_id=36,key_group_whitelist=extra or [])


def test_defaults_always_allowed_and_whitelist_deduplicated():
    assert _configured_group_ids(config([42,37,42,36])) == [36,37,42]
    assert _configured_group_ids(config()) == [36,37]
    assert _configured_group_ids(SimpleNamespace(text_group_id=None,image_group_id=36)) == [36]


def test_visible_choices_are_site_whitelist_intersect_live_groups():
    groups=[AgentAPIGroup(id=i,name=f'Group {i}') for i in (36,37,42,99)]
    assert [g['id'] for g in opencode._allowed_groups(config([42,77]),groups)] == [36,37,42]
    assert [g['id'] for g in opencode._allowed_groups(config(),groups)] == [36,37]


async def test_provisioning_syncs_extra_groups():
    seen=[]
    client=SimpleNamespace(update_user_allowed_groups=lambda **args: seen.append(args))
    await _sync_configured_allowed_groups(client,agent_user_id=5,config=config([42]))
    assert seen == [{'agent_user_id':5,'allowed_groups':[36,37,42]}]


class FakeDB:
    def __init__(self): self.added=[]
    async def scalar(self, *args): return None
    def add(self, value):
        value.id=9
        self.added.append(value)
    async def flush(self): pass
    async def commit(self): pass


@pytest.fixture
def key_context(monkeypatch):
    class Client:
        def __init__(self): self.created=[]; self.updated=[]; self.allowed=[]
        def update_user_allowed_groups(self, **args): self.allowed.append(args)
        def create_user_api_key(self, **args):
            self.created.append(args)
            return AgentAPIKey(id=50,key='test-key',group_id=args['group_id'],created_at='2026-10-19T00:00:00Z')
        def update_user_api_key(self, **args):
            self.updated.append(args)
            return AgentAPIKey(id=50,key='test-key',group_id=args['payload'].get('group_id',42),created_at='2026-10-19T00:00:00Z')
    client=Client()
    mapping=UserAgentApiKey(id=9,team_id=1,user_id=1,agent_user_id=5,agent_key_id=50,api_key='test-key',name='old',group_id=42,is_deleted=False)
    state={'config':config([42]),'mappings':[], 'keys':[]}
    async def context(db,user):
        return (state['config'],SimpleNamespace(team_id=1,agent_user_id=5),client,'test-token',state['keys'],
                [AgentAPIGroup(id=i,name=f'Group {i}') for i in (36,37,42,99)],None,state['mappings'])
    monkeypatch.setattr(opencode,'_key_context',context)
    return state,client,mapping


async def test_create_whitelisted_group_and_reject_other_group(key_context):
    _,client,_=key_context
    user=SimpleNamespace(id=1,site_id=1)
    db=FakeDB()
    result=await opencode.create_opencode_key(opencode.OpenCodeKeyCreateRequest(name='extra',group_id=42),user,db)
    assert result.data['group']['id']==42
    assert client.allowed[0]['allowed_groups']==[36,37,42]
    assert db.added[0].group_id==42
    with pytest.raises(BusinessError,match='该分组当前不可用'):
        await opencode.create_opencode_key(opencode.OpenCodeKeyCreateRequest(name='blocked',group_id=99),user,db)
    assert len(client.created)==1


async def test_removed_group_keeps_existing_key_editable_but_cannot_create(key_context):
    state,client,mapping=key_context
    state.update(config=config(),mappings=[mapping],keys=[AgentAPIKey(id=50,key='test-key',group_id=42)])
    user=SimpleNamespace(id=1,site_id=1)
    result=await opencode.update_opencode_key(9,opencode.OpenCodeKeyUpdateRequest(name='renamed',group_id=42),user,FakeDB())
    assert result.data['group']['id']==42
    assert 'group_id' not in client.updated[0]['payload']
    with pytest.raises(BusinessError,match='该分组当前不可用'):
        await opencode.create_opencode_key(opencode.OpenCodeKeyCreateRequest(name='new',group_id=42),user,FakeDB())
    with pytest.raises(BusinessError,match='该分组当前不可用'):
        await opencode.update_opencode_key(9,opencode.OpenCodeKeyUpdateRequest(group_id=99),user,FakeDB())


async def test_additional_groups_share_member_quota():
    class DB:
        async def scalar(self,*args): return SimpleNamespace(text_quota=100,image_quota=100)
    mapping=SimpleNamespace(id=8,group_id=36,agent_key_id=20,is_deleted=False)
    with pytest.raises(BusinessError,match='超出成员总额度'):
        await opencode._validate_member_key_quota(DB(),config=config([42]),account=SimpleNamespace(team_id=1),
            current_user=SimpleNamespace(id=1),group_id=42,requested_quota=Decimal(50),mappings=[mapping],
            live_keys=[AgentAPIKey(id=20,key='',group_id=36,quota=Decimal(60))])


async def test_team_usage_keeps_added_and_removed_group_keys_in_quota_pool():
    from app.services.team_usage import _member_key_state
    mappings=[SimpleNamespace(user_id=1,group_id=group,agent_key_id=key,is_deleted=False) for group,key in [(37,10),(36,20),(42,30),(99,40)]]
    class Result:
        def __init__(self, rows): self.rows=rows
        def scalars(self): return self
        def all(self): return self.rows
    class DB:
        def __init__(self): self.rows=iter([mappings,[],[]])
        async def execute(self,*args): return Result(next(self.rows))
    bindings,_=await _member_key_state(DB(),team_id=1,user_ids=[1],config=config([42]))
    assert bindings[1].text_key_ids==(10,)
    assert bindings[1].image_key_ids==(20,30,40)
