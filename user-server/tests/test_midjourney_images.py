import base64
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.api.routes import catalog
from app.api.routes.catalog_serializers import serialize_task, serialize_task_status, serialize_user_work
from app.core.exceptions import BusinessError
from app.services import image_generation
from app.services.image_generation import GeneratedImage, generate_image
from test_banana_images import config_for
from test_batch_groups import sessions
from test_batch_progress import seed


@pytest.mark.parametrize('model', ['mj', 'mj-adx', 'mj-cdn', 'mj-adx-cdn'])
@pytest.mark.parametrize('ratio', ['4:3', '1:1', '9:16'])
def test_mj_one_generation_returns_four_ordered_images(monkeypatch, model, ratio):
    requests = []
    completed = []
    def post(url, body, headers, timeout):
        requests.append((url, body))
        return {'data': [{'b64_json': base64.b64encode(f'image-{i}'.encode()).decode()} for i in range(4)],
                'request_id': 'mj-verified-request'}
    monkeypatch.setattr(image_generation, '_post_json', post)
    result = generate_image(config_for(model), 'four cats', None, '1k', ratio,
                            on_model_completed=completed.append)
    assert len(requests) == len(completed) == 1
    assert requests[0] == ('https://api.example.com/v1/images/generations', {
        'model': model, 'prompt': 'four cats', 'n': 4, 'aspect_ratio': ratio,
        'version': 'v7', 'mode': 'normal', 'speed': 'fast', 'response_format': 'url',
    })
    assert [image.content for image in (result, *result.additional_images)] == [f'image-{i}'.encode() for i in range(4)]
    assert result.provider_request_id == 'mj-verified-request'


def test_mj_downloads_all_four_urls_without_repeating_generation(monkeypatch):
    posts = []
    downloads = []
    def post(*args):
        posts.append(args)
        return {'data': [{'url': f'https://upstream.test/{i}.png'} for i in range(4)]}
    def download(url, timeout, fallback_url=None):
        downloads.append(url)
        return GeneratedImage(url.encode(), 'image/png'), False
    monkeypatch.setattr(image_generation, '_post_json', post)
    monkeypatch.setattr(image_generation, '_download_image_prefer_hot', download)
    result = generate_image(config_for('mj'), 'test', aspect_ratio='4:3')
    assert len(posts) == 1 and len(downloads) == 4 and len(result.additional_images) == 3


@pytest.mark.parametrize('count', [0, 1, 3, 5])
def test_mj_rejects_incomplete_or_unexpected_results(monkeypatch, count):
    monkeypatch.setattr(image_generation, '_post_json', lambda *_: {'data': [{'b64_json': 'YQ=='}] * count})
    with pytest.raises(BusinessError, match='四张'):
        generate_image(config_for('mj'), 'test')


def test_mj_unsupported_parameters_fail_before_upstream_call(monkeypatch):
    def never_call(*_):
        raise AssertionError('No charged request for unsupported parameters')
    monkeypatch.setattr(image_generation, '_post_json', never_call)
    with pytest.raises(BusinessError, match='比例'):
        generate_image(config_for('mj'), 'test', aspect_ratio='21:9')
    with pytest.raises(BusinessError, match='文生图'):
        generate_image(config_for('mj'), 'test', input_image='https://example.test/ref.png')


async def test_one_mj_task_persists_four_outputs_and_exports_all_for_one_price(sessions, monkeypatch):
    await seed(sessions, 'mj-one-call', ['running'])
    generated = GeneratedImage(b'0', 'image/png', additional_images=tuple(GeneratedImage(str(i).encode(), 'image/png') for i in range(1, 4)))
    stored_contents = []
    async def store(**kwargs):
        stored_contents.append(kwargs['content'])
        assert kwargs['storage_mode'] == 'third_party'
        index = len(stored_contents)
        return {'storage_key': f'mj/{index}.png', 'url': f'https://cdn.test/mj/{index}.png',
                'mime_type': 'image/png', 'width': 1232, 'height': 928, 'size_bytes': 1, 'sha256': str(index)*64}
    monkeypatch.setattr(catalog, 'run_generated_image_storage_in_executor', store)
    async with sessions() as db:
        task_id = await db.scalar(select(catalog.image_tasks_table.c.id).where(catalog.image_tasks_table.c.batch_id == 'mj-one-call'))
        await db.execute(update(catalog.image_tasks_table).where(catalog.image_tasks_table.c.id == task_id).values(credit_cost=Decimal('6')))
        await db.commit()
        asset, manifest = await catalog.store_generated_image_collection(db, generated=generated, user_id=1, site_id=1,
                                                                       qiniu_storage_enabled=False, storage_mode='third_party')
        assert await catalog.finish_image_task_succeeded(db, task_id, asset.url, output_image_assets=manifest)
        # Idempotent completion cannot turn one paid invocation into four tasks.
        assert not await catalog.finish_image_task_succeeded(db, task_id, asset.url, output_image_assets=manifest)
        row = (await db.execute(select(catalog.image_tasks_table).where(catalog.image_tasks_table.c.id == task_id))).mappings().one()
        assert row['credit_cost'] == Decimal('6')
        for serialize, key in [(serialize_task, 'output_images'), (serialize_task_status, 'output_images'), (serialize_user_work, 'output_assets')]:
            assert [a['url'] for a in serialize(row)[key]] == [a['url'] for a in manifest]
        user = type('User', (), {'id': 1, 'site_id': 1, 'active_team_id': 1})()
        exports = await catalog._get_export_items([task_id], '', user, db)
        assert [item.url for item in exports] == [a['url'] for a in manifest]
        assert len({item.task_no for item in exports}) == 4
        assert len((await db.execute(select(catalog.image_tasks_table))).all()) == 1
    assert stored_contents == [b'0', b'1', b'2', b'3']


def test_legacy_primary_result_and_expiry_still_work():
    row = {'id': 7, 'status': 'succeeded', 'output_image_url': 'https://cdn.test/legacy.png'}
    for serialize in (serialize_task, serialize_task_status):
        assert len(serialize(row)['output_images']) == 1
        assert serialize({**row, 'output_expired_at': datetime.now(UTC)})['output_images'] == []


async def test_catalog_exposes_fixed_batch_size(sessions):
    from types import SimpleNamespace
    async with sessions() as db:
        await db.execute(update(catalog.image_models_table).where(catalog.image_models_table.c.id == 5).values(vendor_model='mj'))
        await db.commit()
        # Model options are independent of the transport capability.
        from unittest.mock import AsyncMock
        original = catalog.model_options
        catalog.model_options = AsyncMock(return_value=([{'value': '1k'}], [{'value': '4:3'}], []))
        try:
            response = await catalog.models('image_edit', SimpleNamespace(site_id=1, is_internal=True), db)
        finally:
            catalog.model_options = original
        assert response.data[0]['images_per_generation'] == 4
