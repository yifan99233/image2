import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlalchemy import text
from test_customer_vip import vip_api

spec = importlib.util.spec_from_file_location("provision_subsite", Path(__file__).parents[1] / "scripts/provision_subsite.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

async def snapshot_and_args(sessions):
    async with sessions() as db:
        await db.execute(text("INSERT INTO site_configs(id,site_key,site_name,is_default) VALUES(1,'main','Template',true),(2,'agent','Agent',false)"))
        await db.execute(text("INSERT INTO admin_users(id,site_id,username,email,password_hash,role,system_super_admin,is_active) VALUES(1,1,'admin','admin@test.invalid','unused','super_admin',true,true)"))
        await db.execute(text("INSERT INTO agent_configs(id,site_id,is_enabled,image_billing_enabled,base_url,admin_api_key,text_group_id,image_group_id) VALUES(2,2,true,true,'https://agent5.example.invalid','fixture-admin-key',2,15)"))
        await db.execute(text("UPDATE image_model_providers SET base_url='https://agent5.example.invalid/v1',encrypted_api_key='fixture-provider-key' WHERE id=1"))
        await db.execute(text("INSERT INTO image_model_providers(id,site_id,name,code,base_url,encrypted_api_key) VALUES(100,1,'old','old','https://agent3.example.invalid','fixture-legacy-key')"))
        await db.execute(text("INSERT INTO recharge_plans(id,site_id,name,amount_cents,credit_amount,bonus_credit_amount) VALUES(100,1,'basic',6880,6880,680)"))
        await db.execute(text("INSERT INTO payment_configs(id,site_id,provider,pid,pkey,notify_url,return_url) VALUES(1,1,'zpay','fixture-pid','fixture-payment-key','https://old/notify','https://old/return')"))
        snapshot = {'source':'fixture','tables':{}}
        snapshot['site'] = dict((await db.execute(text('SELECT * FROM site_configs WHERE id=1'))).mappings().one())
        for name in module.TABLES:
            condition = "model_id=1" if name in ['image_model_resolutions','image_model_aspect_ratios','image_model_durations'] else "site_id=1"
            rows = (await db.execute(text(f'SELECT * FROM {name} WHERE {condition} ORDER BY id'))).mappings().all()
            snapshot['tables'][name] = [{k:v for k,v in r.items() if k not in module.SECRETS} for r in rows]
        await db.execute(text("SELECT setval(pg_get_serial_sequence('image_model_providers','id'),1,false)"))
        await db.commit()
    args = SimpleNamespace(site_key='ccai',site_name='CCAI',frontend_url='https://ccai.example.invalid',admin_url='https://admin.ccai.example.invalid',credentials_site='main',agent_site='agent',allowed_agent_host='agent5.example.invalid')
    return snapshot,args

async def test_atomic_clone_remaps_ids_and_leaves_business_data(vip_api):
    _,_,sessions = vip_api
    snapshot,args = await snapshot_and_args(sessions)
    async with sessions() as db:
        result = await module.provision(db,snapshot,args)
        await db.commit()
        site=result['site_id']
        assert site==3 and result['disabled_legacy_providers']==1
        model=(await db.execute(text('SELECT * FROM image_models WHERE site_id=:site'),{'site':site})).mappings().one()
        provider=(await db.execute(text('SELECT * FROM image_model_providers WHERE id=:id'),{'id':model['provider_id']})).mappings().one()
        assert provider['site_id']==site and provider['encrypted_api_key']=='fixture-provider-key'
        assert await db.scalar(text("SELECT count(*) FROM image_model_providers WHERE site_id=:site AND (base_url LIKE '%agent3%' OR encrypted_api_key='fixture-legacy-key')"),{'site':site})==0
        assert await db.scalar(text('SELECT count(*) FROM users'))==2
        assert await db.scalar(text("SELECT count(*) FROM site_configs WHERE is_default"))==1
        payment=(await db.execute(text('SELECT * FROM payment_configs WHERE site_id=:site'),{'site':site})).mappings().one()
        assert payment['pkey']=='fixture-payment-key' and payment['notify_url']=='https://ccai.example.invalid/api/recharge/zpay/notify'
        agent=(await db.execute(text('SELECT * FROM agent_configs WHERE site_id=:site'),{'site':site})).mappings().one()
        assert agent['base_url']=='https://agent5.example.invalid' and agent['image_group_id']==15
        assert await db.scalar(text('SELECT count(*) FROM admin_audit_logs'))==1
        with pytest.raises(ValueError,match='already exists'):
            await module.provision(db,snapshot,args)
        await db.rollback()

async def test_rejects_active_legacy_upstream_and_rolls_back(vip_api):
    _,_,sessions = vip_api
    snapshot,args = await snapshot_and_args(sessions)
    snapshot['tables']['image_models'][0]['provider_id']=100
    async with sessions() as db:
        with pytest.raises(ValueError,match='outside the allowed agent'):
            await module.provision(db,snapshot,args)
        await db.rollback()
        assert await db.scalar(text("SELECT count(*) FROM site_configs WHERE site_key='ccai'"))==0
        assert await db.scalar(text('SELECT count(*) FROM image_models'))==1
