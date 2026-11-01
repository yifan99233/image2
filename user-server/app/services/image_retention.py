"""Bounded, resumable local-MinIO retention. CLI is read-only unless --apply."""
import argparse
import asyncio
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from collections import defaultdict
from urllib.parse import unquote, urlsplit

from minio import Minio
from sqlalchemy import text
import urllib3

from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.services.asset_urls import asset_url_variants, canonicalize_asset_url
from app.services.image_uploads import _legacy_storage_target

logger = logging.getLogger(__name__)
RETENTION = timedelta(days=7)  # No count limit. Never shorten for a large batch.
LOCK_ID = 71420261019


def local_key(asset, target) -> str | None:
    """Only objects unambiguously owned by the configured local MinIO target."""
    root = canonicalize_asset_url(target.public_base_url).rstrip('/') + '/'
    value = canonicalize_asset_url(asset.get('local_url') or asset['url'])
    if not value.startswith(root):
        return None
    key = unquote(urlsplit(value[len(root):]).path)
    if not re.fullmatch(r'generated/' + str(asset['user_id']) + r'/[a-f0-9]{32}\.[a-zA-Z0-9]+', key):
        return None
    return key


def urls_for(asset):
    return list({variant for name in ('url', 'local_url', 'r2_url')
                 if asset.get(name) for variant in asset_url_variants(asset[name])})


async def protected_names(db, filenames):
    """Return only matching UUID filenames, never prompts or user data.

    All referenced tables are fenced by the migration's row triggers. Candidate
    asset rows must already be locked before this final READ COMMITTED scan.
    """
    names = set()
    queries = [
        "SELECT concat_ws(' ',input_image_url,input_image_urls) FROM image_tasks WHERE input_image_url IS NOT NULL OR input_image_urls IS NOT NULL",
        "SELECT document::text FROM canvas_projects WHERE deleted_at IS NULL",
        "SELECT a.storage_key FROM user_material_assets m JOIN image_assets a ON a.id=m.image_asset_id",
    ]
    # These are admin-owned tables and may not exist on a fresh user-only install.
    for table in ('material_assets', 'site_configs'):
        if (await db.execute(text('SELECT to_regclass(:name)'), {'name': table})).scalar():
            queries.append(f'SELECT to_jsonb(t)::text FROM {table} t')
    for query in queries:
        # Extract/filter on the DB server: return at most this batch's filenames,
        # not every customer's canvas document and historical reference URL.
        result = await db.execute(text("""SELECT DISTINCT m[1] FROM (""" + query + """) refs(payload)
            CROSS JOIN LATERAL regexp_matches(refs.payload, '([a-f0-9]{32}[.][a-zA-Z0-9]+)', 'g') m
            WHERE m[1]=ANY(:names)"""), {'names': filenames})
        names.update(result.scalars())
    return names


async def plan_batch(db, target, *, after_id=0, limit=100, apply=False, now=None):
    now = now or datetime.now(UTC)
    cutoff = now - RETENTION
    # Keyset scanning prevents protected old assets from starving later rows.
    undeleted = 'storage_deleted_at IS NULL' if apply else "(to_jsonb(image_assets)->>'storage_deleted_at') IS NULL"
    rows = (await db.execute(text('''
        SELECT * FROM image_assets WHERE id>:after_id AND source='generated'
          AND mime_type LIKE 'image/%' AND size_bytes>0
          AND created_at<=:cutoff AND ''' + undeleted + '''
        ORDER BY id LIMIT :limit
    ''' + (' FOR UPDATE SKIP LOCKED' if apply else '')),
        {'after_id': after_id, 'cutoff': cutoff, 'limit': limit})).mappings().all()
    # One indexed lookup for the whole batch, including aliases. Lock task rows
    # before checking collection flags; do not issue a query for every image.
    tasks_by_url = defaultdict(list)
    all_urls = list({url for row in rows for url in urls_for(row)})
    if all_urls:
        task_rows = (await db.execute(text('''SELECT id,output_image_url,output_image_assets,status,finished_at,is_collected,is_gallery_featured
            FROM image_tasks WHERE id IN (
                SELECT id FROM image_tasks WHERE output_image_url=ANY(:urls)
                UNION
                SELECT task.id FROM unnest(cast(:urls AS text[])) matched(url)
                JOIN image_tasks task
                  ON task.output_image_assets @> jsonb_build_array(jsonb_build_object('url', matched.url))
                  OR task.output_image_assets @> jsonb_build_array(jsonb_build_object('r2_url', matched.url)))
            ORDER BY id
        ''' + (' FOR UPDATE' if apply else '')), {'urls': all_urls})).mappings().all()
        for task in task_rows:
            task_urls = {task['output_image_url']}
            for output in task['output_image_assets'] or []:
                task_urls.update(url for url in (output.get('url'), output.get('r2_url')) if url)
            for url in task_urls:
                tasks_by_url[url].append(task)
    protected = await protected_names(db, list({row['storage_key'].rsplit('/',1)[-1] for row in rows})) if rows else set()
    report = {'scanned': len(rows), 'eligible': 0, 'logical_bytes': 0,
              'skipped': {}, 'next_id': rows[-1]['id'] if rows else after_id}
    planned = []
    task_ids = set()
    for asset in rows:
        reason = None
        key = local_key(asset, target)
        tasks = [task for url in urls_for(asset) for task in tasks_by_url[url]]
        if not key:
            reason = 'not_local_generated_object'
        elif key.rsplit('/', 1)[-1] in protected:
            reason = 'referenced'
        elif not tasks:
            reason = 'no_completed_task'  # Orphans require separate reconciliation.
        elif any(t['is_collected'] or t['is_gallery_featured'] for t in tasks):
            reason = 'collected_or_featured'
        elif any(t['status'] != 'succeeded' or not t['finished_at'] or t['finished_at'] > cutoff for t in tasks):
            reason = 'not_seven_days_since_completion'
        if reason:
            report['skipped'][reason] = report['skipped'].get(reason, 0) + 1
            continue
        task_ids.update(t['id'] for t in tasks)
        planned.append((asset['id'], key))
        report['eligible'] += 1
        report['logical_bytes'] += asset['size_bytes']
    if apply and planned:
        await db.execute(text("""UPDATE image_assets SET retention_pending_at=coalesce(retention_pending_at,:now)
            WHERE id=ANY(:ids)"""), {'now': now, 'ids': [asset_id for asset_id, _ in planned]})
        await db.execute(text("""UPDATE image_tasks SET output_expired_at=coalesce(output_expired_at,:now)
            WHERE id=ANY(:ids)"""), {'now': now, 'ids': list(task_ids)})
    return report, planned


def storage_client(target):
    return Minio(target.endpoint, access_key=target.access_key, secret_key=target.secret_key,
                 secure=target.secure, http_client=urllib3.PoolManager(
                     timeout=urllib3.Timeout(connect=3, read=10), retries=False))


def check_storage(client, bucket):
    # remove_object on versioned buckets merely writes a delete marker and does
    # not free storage. Refuse rather than falsely report reclaimed space.
    versioning = client.get_bucket_versioning(bucket)
    if versioning.status in ('Enabled', 'Suspended'):
        raise RuntimeError('Versioned buckets require a separate version-aware cleanup')


async def run_batch(*, after_id=0, limit=100, apply=False, target=None, client=None, sessions=AsyncSessionLocal):
    if not 1 <= limit <= 500:
        raise ValueError('limit must be between 1 and 500')
    target = target or _legacy_storage_target(qiniu_storage_enabled=False)
    if target.provider != 'minio':
        raise RuntimeError('Retention supports only local MinIO')
    if apply:
        client = client or storage_client(target)
        await asyncio.to_thread(check_storage, client, target.bucket)
    async with sessions() as db:
        if not apply:
            await db.execute(text('SET TRANSACTION READ ONLY'))
        await db.execute(text("SET LOCAL statement_timeout='60s'"))
        await db.execute(text("SET LOCAL lock_timeout='2s'"))
        report, planned = await plan_batch(db, target, after_id=after_id, limit=limit, apply=apply)
        if apply:
            await db.commit()  # Fence new references BEFORE any irreversible I/O.
        else:
            await db.rollback()
    report.update(deleted=0, errors=0, dry_run=not apply)
    if apply:
        for asset_id, key in planned:
            try:
                # S3 DELETE is idempotent. After a crash following DELETE, retry
                # the pending row and finish its DB marker without charging again.
                await asyncio.to_thread(client.remove_object, target.bucket, key)
            except Exception as exc:
                report['errors'] += 1
                error = type(exc).__name__[:128]  # No URLs, credentials or payloads.
                async with sessions() as db:
                    await db.execute(text('UPDATE image_assets SET retention_error=:error WHERE id=:id'),
                                     {'error': error, 'id': asset_id})
                    await db.commit()
                continue
            async with sessions() as db:
                await db.execute(text('''UPDATE image_assets SET storage_deleted_at=now(),retention_error=NULL
                    WHERE id=:id AND retention_pending_at IS NOT NULL'''), {'id': asset_id})
                await db.commit()
            report['deleted'] += 1
    return report


async def locked_batch(**kwargs):
    # Session lock spans tombstone commit + S3 deletion without a long DB tx.
    async with engine.connect() as conn:
        locked = (await conn.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': LOCK_ID})).scalar()
        await conn.commit()
        if not locked:
            return {'busy': True}
        try:
            return await run_batch(**kwargs)
        finally:
            await conn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': LOCK_ID})
            await conn.commit()


async def retention_loop():
    cursor = 0
    while True:
        try:
            report = await locked_batch(after_id=cursor, limit=settings.image_retention_batch_size, apply=True)
            if not report.get('busy'):
                cursor = report['next_id'] if report['scanned'] else 0
                logger.info('image_retention %s', json.dumps(report))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error('image_retention error_type=%s', type(exc).__name__)
        await asyncio.sleep(settings.image_retention_interval_seconds)


async def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--after-id', type=int, default=0)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--max-batches', type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.max_batches <= 10000:
        parser.error('--max-batches must be 1..10000')
    try:
        for _ in range(args.max_batches):
            report = await locked_batch(after_id=args.after_id, limit=args.limit, apply=args.apply)
            print(json.dumps(report), flush=True)
            if report.get('busy') or not report['scanned']:
                break
            args.after_id = report['next_id']
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(cli())
