import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.core.exceptions import BusinessError
from app.services import image_generation as generation, image_uploads, model_cdn
from test_banana_images import config_for
from test_uploads import MINIMAL_PNG

CONFIG = dict(site_id=1, model_ids=[215,216,217,266,267], cdn_key='private-test-key',
              public_base_url='https://cdn.example.com', key_prefix='magic/images',
              endpoint='https://s3.example.com', region='la', bucket='test',
              access_key='test-ak', secret_key='test-sk')


def test_cdn_scope_is_explicit_and_credentials_not_in_repr(monkeypatch):
    monkeypatch.setattr(model_cdn.settings, 'model_cdn_config_json', json.dumps(CONFIG))
    assert model_cdn.for_model(1,215).cdn_key == CONFIG['cdn_key']
    assert model_cdn.for_model(2,215) is None
    assert model_cdn.for_model(1,999) is None
    assert 'private-test-key' not in repr(model_cdn.for_model(1,215))
    assert 'cdn_key' not in generation._safe_request_value({'cdn_key':'secret'})


@pytest.mark.parametrize('model', ['gpt-image-2-adx1','gpt-image-2.5-flare-adx1','gpt-image-2.5-sunburst-adx1','nano-banana-2-adx1','nano-banana-2.1-adx1','gpt-image-2-adx2','gpt-image-2.5-flare-adx2','nano-banana-2-adx2','nano-banana-2.1-adx2'])
@pytest.mark.parametrize('edit', [False, True])
def test_all_models_send_key_and_keep_final_url_without_download(monkeypatch, model, edit):
    config=replace(config_for(model),cdn_key='private-test-key',native_image_base_url='https://cdn.example.com/magic/images/')
    url=config.native_image_base_url+'output.png'
    monkeypatch.setattr(generation,'_input_images_from_values',lambda *_: [generation.GeneratedImage(MINIMAL_PNG,'image/png')] if edit else [])
    def post(_url,body,*_):
        assert body['cdn_key']=='private-test-key'
        assert body['response_format']=='url'
        return {'data':[{'url':url}]}
    monkeypatch.setattr(generation,'_post_json',post)
    monkeypatch.setattr(generation,'_post_multipart',post)
    monkeypatch.setattr(generation,'_download_image',lambda *_a,**_k: pytest.fail('result must not be downloaded'))
    image=generation.generate_image(config,'test',['reference'] if edit else None,'4k','1:1')
    assert image.source_url==url and image.content==b'' and image.hot_url is None


@pytest.mark.parametrize('url',['https://other.example.com/a.png','https://cdn.example.com.evil/magic/images/a.png','https://cdn.example.com/magic/images/../other/a.png','https://cdn.example.com/magic/images/%2e%2e/other/a.png',''])
def test_unexpected_native_results_fail_without_reupload(url):
    with pytest.raises(BusinessError):
        generation._extract_openai_images_result({'data':[{'url':url,'b64_json':'aW1hZ2U='}]},10,native_base_url='https://cdn.example.com/magic/images/')


async def test_reference_upload_only_writes_dedicated_cdn(monkeypatch):
    config=model_cdn.ModelCdnConfig(**CONFIG)
    writes=[]
    def store(**kw):
        writes.append(kw)
        return config.public_base_url+'/'+kw['storage_key']
    monkeypatch.setattr(model_cdn,'store_reference',store)
    monkeypatch.setattr(image_uploads,'_store_local_image',lambda **_: pytest.fail('no local copy'))
    monkeypatch.setattr(image_uploads,'_store_image',lambda **_: pytest.fail('no generic storage'))
    db=SimpleNamespace(add=lambda _:None,commit=AsyncMock(),refresh=AsyncMock())
    asset=await image_uploads._save_uploaded_content(db=db,current_user=SimpleNamespace(id=7,site_id=1),content=MINIMAL_PNG,original_filename='test.png',submitted_mime_type='image/png',model_cdn=config)
    assert len(writes)==1 and writes[0]['storage_key'].startswith('magic/images/inputs/7/')
    assert asset.local_url is None and asset.r2_url is None
    assert asset.url.startswith(config.result_base_url) and asset.width==1


async def test_generated_native_url_storage_does_not_store_bytes(monkeypatch):
    from app.api.routes import catalog
    monkeypatch.setattr(catalog,'store_generated_image_object',lambda **_:pytest.fail('no reupload'))
    result=await catalog.run_generated_image_storage_in_executor(user_id=7,content=b'',mime_type='image/png',storage_mode='native',source_url='https://cdn.example.com/magic/images/result.png')
    assert result['url']=='https://cdn.example.com/magic/images/result.png'
    assert result['local_url'] is None and result['r2_url'] is None


def test_multiple_sites_select_only_their_explicit_model_scope(monkeypatch):
    second = {**CONFIG, "site_id": 2, "model_ids": [283, 284], "cdn_key": "second-private-key"}
    monkeypatch.setattr(model_cdn.settings, "model_cdn_config_json", json.dumps([CONFIG, second]))
    assert model_cdn.for_model(1, 215).cdn_key == CONFIG["cdn_key"]
    assert model_cdn.for_model(2, 283).cdn_key == second["cdn_key"]
    assert model_cdn.for_model(2, 215) is None
    assert model_cdn.for_model(1, 283) is None
    assert model_cdn.for_model(3, 283) is None
    assert "second-private-key" not in repr(model_cdn.for_model(2, 283))


@pytest.mark.parametrize("value", [[CONFIG, CONFIG], [CONFIG, {**CONFIG, "public_base_url": "invalid"}]])
def test_invalid_multisite_configuration_is_rejected_without_exposing_secrets(monkeypatch, value):
    monkeypatch.setattr(model_cdn.settings, "model_cdn_config_json", json.dumps(value))
    with pytest.raises(RuntimeError) as error:
        model_cdn.for_model(1, 215)
    assert str(error.value) == "Invalid model CDN configuration"
