import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.config import settings
from app.services import image_retention as retention
from app.api.routes.catalog_serializers import serialize_task, serialize_task_status

TARGET = SimpleNamespace(provider='minio', public_base_url='https://magic.shyfai.cn/image2-assets',
                         endpoint='127.0.0.1:9000', bucket='image2-assets')


class Store:
    def __init__(self, fail=False, versioning=None):
        self.deleted = []
        self.fail = fail
        self.versioning = versioning

    def get_bucket_versioning(self, bucket):
        return SimpleNamespace(status=self.versioning)

    def remove_object(self, bucket, key):
        if self.fail:
            raise TimeoutError('private URL must never be persisted')
        self.deleted.append((bucket, key))


@pytest.fixture
async def sessions():
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        # conftest refuses non-test databases. This suite owns its isolated DB.
        await db.execute(text('TRUNCATE users, image_assets, image_tasks, canvas_projects CASCADE'))
        await db.execute(text("INSERT INTO users(id,username,email,password_hash) VALUES(90001,'retention','retention@example.test','unused')"))
        await db.commit()
    yield factory
    await engine.dispose()


async def seed(sessions, *, age=8, finished_age=None, source='generated', collected=False,
               featured=False, external=False, mime='image/png'):
    filename = uuid4().hex + '.png'
    key = f'generated/90001/{filename}'
    url = ('https://external.example/' if external else TARGET.public_base_url + '/') + key
    created = datetime.now(UTC) - timedelta(days=age)
    finished = datetime.now(UTC) - timedelta(days=age if finished_age is None else finished_age)
    async with sessions() as db:
        asset = (await db.execute(text('''INSERT INTO image_assets(user_id,site_id,storage_key,url,local_url,mime_type,size_bytes,sha256,source,created_at)
            VALUES(90001,1,:key,:url,:url,:mime,1024,:hash,:source,:created) RETURNING id'''),
            {'key': key, 'url': url, 'mime': mime, 'hash': uuid4().hex*2, 'source': source, 'created': created})).scalar_one()
        task = (await db.execute(text('''INSERT INTO image_tasks(task_no,user_id,model_id,prompt,status,output_image_url,created_at,finished_at,timeout_seconds,is_collected,is_gallery_featured)
            VALUES(:number,90001,1,'test','succeeded',:url,:created,:finished,600,:collected,:featured) RETURNING id'''),
            {'number': uuid4().hex, 'url': url, 'created': created, 'finished': finished,
             'collected': collected, 'featured': featured})).scalar_one()
        await db.commit()
    return asset, task, url


async def run(sessions, **kwargs):
    return await retention.run_batch(sessions=sessions, target=TARGET, **kwargs)


async def test_dry_run_is_read_only_and_completion_clock(sessions):
    await seed(sessions)
    await seed(sessions, age=10, finished_age=6)
    await seed(sessions, age=6)
    await seed(sessions, source='upload')
    await seed(sessions, external=True)
    await seed(sessions, mime='video/mp4')
    report = await run(sessions)
    assert report['eligible'] == 1
    assert report['deleted'] == 0
    async with sessions() as db:
        assert (await db.scalar(text('SELECT count(*) FROM image_assets WHERE retention_pending_at IS NOT NULL'))) == 0


async def test_failed_delete_retry_and_task_history(sessions):
    asset, task, _ = await seed(sessions)
    failed = await run(sessions, apply=True, client=Store(fail=True))
    assert failed['errors'] == 1 and failed['deleted'] == 0
    async with sessions() as db:
        row = (await db.execute(text('SELECT * FROM image_assets WHERE id=:id'), {'id':asset})).mappings().one()
        assert row['retention_pending_at'] and row['storage_deleted_at'] is None
        assert row['retention_error'] == 'TimeoutError'
        taskrow = (await db.execute(text('SELECT * FROM image_tasks WHERE id=:id'), {'id':task})).mappings().one()
        assert taskrow['status'] == 'succeeded' and taskrow['output_image_url']
        for serialize in (serialize_task, serialize_task_status):
            result = serialize(taskrow)
            assert result['output_images'] == [] and result['output_expired_at']
    store = Store()
    assert (await run(sessions, apply=True, client=store))['deleted'] == 1
    assert len(store.deleted) == 1
    assert (await run(sessions, apply=True, client=store))['scanned'] == 0


@pytest.mark.parametrize('kind', ['collected', 'featured', 'canvas', 'material', 'input'])
async def test_reference_protection(sessions, kind):
    asset, task, url = await seed(sessions, collected=kind=='collected', featured=kind=='featured')
    async with sessions() as db:
        if kind == 'canvas':
            await db.execute(text('''INSERT INTO canvas_projects(site_id,user_id,id,title,node_count,connection_count,document,revision,mutation_id)
                VALUES(1,90001,'test','test',1,0,jsonb_build_object('url',cast(:url as text)),1,'test')'''), {'url': url.replace('.cn/', '.com/')})
        elif kind == 'material':
            await db.execute(text("INSERT INTO user_material_assets(site_id,user_id,image_asset_id,name) VALUES(1,90001,:id,'test')"), {'id':asset})
        elif kind == 'input':
            await db.execute(text('UPDATE image_tasks SET input_image_urls=:urls WHERE id=:id'), {'urls':'["'+url+'"]', 'id':task})
        await db.commit()
    report = await run(sessions, apply=True, client=Store())
    assert report['eligible'] == 0 and report['deleted'] == 0


@pytest.mark.parametrize('kind', ['collected', 'canvas', 'material', 'input'])
async def test_new_reference_to_tombstone_rejected(sessions, kind):
    asset, task, url = await seed(sessions)
    await run(sessions, apply=True, client=Store(fail=True))
    async with sessions() as db:
        with pytest.raises(IntegrityError, match='Image has expired'):
            if kind == 'collected':
                await db.execute(text('UPDATE image_tasks SET is_collected=true WHERE id=:id'), {'id':task})
            elif kind == 'input':
                await db.execute(text('UPDATE image_tasks SET input_image_url=:url WHERE id=:id'), {'url':url, 'id':task})
            elif kind == 'material':
                await db.execute(text("INSERT INTO user_material_assets(site_id,user_id,image_asset_id,name) VALUES(1,90001,:id,'test')"), {'id':asset})
            else:
                await db.execute(text('''INSERT INTO canvas_projects(site_id,user_id,id,title,node_count,connection_count,document,revision,mutation_id)
                    VALUES(1,90001,'new','test',1,0,jsonb_build_object('url',cast(:url as text)),1,'test')'''), {'url':url})
        await db.rollback()


async def test_reference_writer_wins_before_cleaner(sessions):
    _, task, url = await seed(sessions)
    async with sessions() as writer:
        await writer.execute(text('UPDATE image_tasks SET input_image_url=:url WHERE id=:id'), {'url':url,'id':task})
        # The asset KEY SHARE lock held by the writer makes SKIP LOCKED skip it.
        report = await run(sessions, apply=True, client=Store())
        assert report['eligible'] == 0
        await writer.commit()
    assert (await run(sessions, apply=True, client=Store()))['eligible'] == 0


async def test_cleaner_wins_and_blocks_new_reference(sessions):
    _, task, url = await seed(sessions)
    async with sessions() as cleaner:
        report, _ = await retention.plan_batch(cleaner, TARGET, apply=True)
        assert report['eligible'] == 1
        async def writer():
            async with sessions() as db:
                with pytest.raises(IntegrityError, match='Image has expired'):
                    await db.execute(text('UPDATE image_tasks SET input_image_url=:url WHERE id=:id'), {'url':url,'id':task})
                await db.rollback()
        writing = asyncio.create_task(writer())
        await asyncio.sleep(.05)
        assert not writing.done()
        await cleaner.commit()
        await asyncio.wait_for(writing, 5)


async def test_hundred_thousand_recent_images_have_no_count_cap(sessions):
    async with sessions() as db:
        await db.execute(text('''INSERT INTO image_assets(user_id,site_id,storage_key,url,mime_type,size_bytes,sha256,source,created_at)
            SELECT 90001,1,'generated/90001/'||md5(i::text)||'.png','https://example.test/'||i,'image/png',100,md5(i::text),'generated',now()-interval '1 day'
            FROM generate_series(1,100000) i'''))
        await db.commit()
    assert (await run(sessions, apply=True, client=Store()))['scanned'] == 0
    async with sessions() as db:
        assert await db.scalar(text('SELECT count(*) FROM image_assets WHERE storage_deleted_at IS NULL')) == 100000


async def test_versioned_bucket_fails_before_tombstones(sessions):
    await seed(sessions)
    with pytest.raises(RuntimeError, match='Versioned'):
        await run(sessions, apply=True, client=Store(versioning='Enabled'))
    async with sessions() as db:
        assert await db.scalar(text('SELECT count(*) FROM image_assets WHERE retention_pending_at IS NOT NULL')) == 0


async def test_cursor_passes_protected_rows(sessions):
    await seed(sessions, collected=True)
    await seed(sessions)
    first = await run(sessions, limit=1)
    assert first['eligible'] == 0
    assert (await run(sessions, after_id=first['next_id'], limit=1))['eligible'] == 1


def test_local_target_rejects_external_paths_and_traversal():
    base = {'user_id':90001, 'url':TARGET.public_base_url+'/generated/90001/'+ 'a'*32+'.png'}
    assert retention.local_key(base,TARGET)
    for value in ['https://evil.example/generated/90001/'+ 'a'*32+'.png',
                  TARGET.public_base_url+'/generated/90002/'+ 'a'*32+'.png',
                  TARGET.public_base_url+'/generated/90001/../'+ 'a'*32+'.png']:
        assert retention.local_key({**base,'url':value},TARGET) is None


async def test_history_filters_old_records_and_keeps_boundary(sessions, monkeypatch):
    from app.api.routes import catalog
    from app.models.user import User
    from sqlalchemy import select
    now = datetime.now(UTC)
    class Clock:
        @staticmethod
        def now(tz):
            return now
    monkeypatch.setattr(catalog, 'datetime', Clock)
    _, old, _ = await seed(sessions, age=8)
    _, boundary, _ = await seed(sessions)
    _, recent, _ = await seed(sessions, age=1)
    async with sessions() as db:
        await db.execute(text('UPDATE image_tasks SET created_at=:at WHERE id=:id'),
                         {'at':now-timedelta(days=7),'id':boundary})
        await db.commit()
        user = await db.scalar(select(User).where(User.id==90001))
        result = await catalog.image_tasks(limit=200,before_id=None,batch_id=None,status=None,current_user=user,db=db)
        assert {row['id'] for row in result.data} == {boundary,recent}
        older_page = await catalog.image_tasks(limit=200,before_id=boundary,batch_id=None,status=None,current_user=user,db=db)
        assert older_page.data == []
        assert await db.scalar(text('SELECT count(*) FROM image_tasks WHERE id=:id'),{'id':old}) == 1


async def test_exact_completion_boundary(sessions):
    now = datetime.now(UTC)
    _, eligible, _ = await seed(sessions)
    _, too_recent, _ = await seed(sessions)
    async with sessions() as db:
        await db.execute(text('UPDATE image_tasks SET finished_at=:at WHERE id=:id'),
                         {'at':now-timedelta(days=7),'id':eligible})
        await db.execute(text('UPDATE image_tasks SET finished_at=:at WHERE id=:id'),
                         {'at':now-timedelta(days=7)+timedelta(microseconds=1),'id':too_recent})
        await db.commit()
        report, planned = await retention.plan_batch(db,TARGET,now=now)
        assert report['eligible'] == 1 and len(planned) == 1


async def test_admin_material_reference_is_protected(sessions):
    _, _, url = await seed(sessions)
    async with sessions() as db:
        await db.execute(text("INSERT INTO material_assets(title,file_url) VALUES('test',:url)"),{'url':url})
        await db.commit()
    assert (await run(sessions))['eligible'] == 0


def test_real_minio_client_delete_transport():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    from minio import Minio
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            seen.append(('GET',self.path))
            body=b'<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"></VersioningConfiguration>'
            self.send_response(200)
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_DELETE(self):
            seen.append(('DELETE',self.path))
            self.send_response(204)
            self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        client=Minio(f'127.0.0.1:{server.server_port}',access_key='test-access',secret_key='test-secret',secure=False,region='us-east-1')
        retention.check_storage(client,'test-bucket')
        client.remove_object('test-bucket','generated/1/example.png')
        assert ('DELETE','/test-bucket/generated/1/example.png') in seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
