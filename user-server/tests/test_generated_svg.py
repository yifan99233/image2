import base64
import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import quote_from_bytes
from zipfile import ZipFile

import pytest

from app.api.routes import catalog, catalog_exports, catalog_serializers
from app.api.routes.browser_exports import DownloadResult
from app.core.exceptions import BusinessError
from app.services import image_generation, image_uploads
from app.services.svg_images import SVG_MIME, svg_dimensions

SVG = b'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1200" viewBox="0 0 1200 1200">
<defs><linearGradient id="sky"><stop stop-color="#071b3b"/><stop offset="1" stop-color="#a9dced"/></linearGradient></defs>
<rect width="1200" height="1200" fill="url(#sky)"/>
<path d="M600 200 300 900H900Z" fill="#effcff"/><text x="600" y="1100">MERRY CHRISTMAS</text>
</svg>'''


@pytest.mark.parametrize("mime", [SVG_MIME, "IMAGE/SVG+XML; charset=utf-8", "image/png", "application/octet-stream", "text/plain"])
@pytest.mark.parametrize("storage", ["local", "cdn", "hot_url"])
def test_generated_svg_preserves_vector_bytes_and_metadata(monkeypatch, mime, storage):
    saved = {}
    def store(**kwargs):
        saved.update(kwargs)
        return "https://storage.example/" + kwargs["storage_key"]
    monkeypatch.setattr(image_uploads, "_store_image", store)
    monkeypatch.setattr(image_uploads, "_store_local_image", store)
    result = image_uploads.store_generated_image_object(
        user_id=7, content=SVG, mime_type=mime, qiniu_storage_enabled=storage == "cdn",
        hot_url="https://hot.example/art.svg" if storage == "hot_url" else None,
    )
    assert saved["content"] == SVG
    assert saved["mime_type"] == result["mime_type"] == SVG_MIME
    assert result["storage_key"].endswith(".svg")
    assert (result["width"], result["height"]) == (1200, 1200)
    assert result["sha256"] == hashlib.sha256(SVG).hexdigest()
    assert result["size_bytes"] == len(SVG)
    assert SVG_MIME not in image_uploads._allowed_mime_types()


@pytest.mark.parametrize("protocol", ["images", "responses", "chat", "gemini"])
def test_compatible_protocols_decode_svg_base64(protocol):
    encoded = base64.b64encode(SVG).decode()
    if protocol == "images":
        result = image_generation._extract_openai_images_result({"data": [{"b64_json": encoded}]}, 1)
    elif protocol == "responses":
        result = image_generation._extract_responses_image_result({"output": [{"type": "image_generation_call", "result": encoded}]}, 1)
    elif protocol == "chat":
        result = image_generation._extract_chat_completions_image_result({"choices": [{"message": {"content": f"![art](data:image/svg+xml;base64,{encoded})"}}]}, 1)
    else:
        result = image_generation._extract_gemini_image_result({"candidates": [{"content": {"parts": [{"inlineData": {"data": encoded, "mimeType": SVG_MIME}}]}}]})
    assert result.content == SVG
    assert result.mime_type == SVG_MIME


def test_openai_url_result_can_be_stored_and_exported_as_svg(monkeypatch):
    class Response(BytesIO):
        headers = {"Content-Type": SVG_MIME}
    monkeypatch.setattr(image_generation.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(SVG))
    result = image_generation._extract_openai_images_result({"data": [{"url": "https://gateway.example/assets/opaque-id"}]}, 1)
    monkeypatch.setattr(image_uploads, "_store_image", lambda **kwargs: "https://cdn.example/" + kwargs["storage_key"])
    stored = image_uploads.store_generated_image_object(user_id=7, content=result.content, mime_type=result.mime_type)
    asset = catalog_serializers.output_assets_from_row({"id": 7, "output_image_url": stored["url"]})[0]
    assert asset["mime_type"] == SVG_MIME
    assert "thumbnail_url" not in asset  # Pillow cannot rasterize SVG; the browser renders it directly.
    monkeypatch.setattr(catalog_exports, "read_export_image", lambda url: (result.content, result.mime_type))
    with catalog_exports._build_export_archive([("IMG1", stored["url"])]) as archive:
        with ZipFile(archive) as zip_file:
            assert zip_file.read("001-IMG1.svg") == SVG
    assert DownloadResult(id=7, status="成功", extension=".svg").extension == ".svg"


def test_svg_native_and_url_mime_detection():
    url = "https://cdn.example/art.SVG?download=1#preview"
    assert image_uploads._guess_media_mime_from_url(url) == SVG_MIME
    assert image_generation._guess_media_mime_from_url(url) == SVG_MIME
    assert catalog_serializers.guess_asset_mime_type(url) == SVG_MIME
    assert catalog_exports.export_file_extension(url, None) == ".svg"
    result = image_generation._extract_openai_images_result({"data": [{"url": "https://cdn.example/art.svg"}]}, 1, native_base_url="https://cdn.example/")
    assert result.mime_type == SVG_MIME


@pytest.mark.parametrize("attributes,expected", [
    ('width="32px" height="24px"', (32, 24)),
    ('viewBox="0 0 640 480"', (640, 480)),
    ('width="320" viewBox="0 0 640 480"', (320, 240)),
    ('height="240" viewBox="0 0 640 480"', (320, 240)),
    ('width="100%" height="100%" viewBox="0,0,640,480"', (640, 480)),
    ('width="NaN" height="Infinity"', (None, None)),
    ('width="1in" height="72pt"', (96, 96)),
    ('width="2.54cm" height="25.4mm"', (96, 96)),
    ('width="101.6Q" height="6pc"', (96, 96)),
    ('width="2in" viewBox="-10 -20 640 480"', (192, 144)),
    ('width="1e2px" height="+2e2PX"', (100, 200)),
    ('viewBox="bogus 0 640 480"', (None, None)),
    ('viewBox="0 0 640px 480px"', (None, None)),
    ('viewBox="0 0 1e999 480"', (None, None)),
    ('', (None, None)),
])
def test_svg_dimensions(attributes, expected):
    assert svg_dimensions(f'<svg xmlns="http://www.w3.org/2000/svg" {attributes}/>'.encode()) == expected


def test_svg_xml_encodings_styles_and_local_references():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 32 24"><style>.snow { fill: url("#paint"); }</style><defs><path id="flake" d="M0 0L1 1"/></defs><use xlink:href="#flake"/></svg>'
    for content in [svg.encode(), b"\xef\xbb\xbf" + svg.encode(), svg.encode("utf-16")]:
        assert svg_dimensions(content) == (32, 24)


@pytest.mark.parametrize("body", [
    '<script>alert(1)</script>', '<g onload="alert(1)"/>',
    '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">html</div></foreignObject>',
    '<use href="https://example.com/remote.svg#x"/>', '<use href="javascript:alert(1)"/>',
    '<image href="data:image/svg+xml;base64,AAAA"/>', '<set attributeName="href" to="javascript:alert(1)"/>',
    '<style>@import "https://example.com/a.css";</style>',
    '<rect style="fill:url(https://example.com/a.svg)"/>',
    '<rect fill="url(&#x68;ttps://example.com/a.svg)"/>',
    '<rect style="fill:u\\72l(https://example.com/a.svg)"/>',
    '<rect style="fill:url(/**/https://example.com/a.svg)"/>',
    '<style>@im\\70ort "https://example.com/a.css";</style>',
    '<rect style="background:image-set(\'https://example.com/a.png\' 1x)"/>',
    '<rect style="background:-webkit-image-set(\'a.png\' 1x)"/>',
    '<rect style="background:src(\'a.png\')"/>',
    '<rect style="behav\\69or: url(#x)"/>',
    '<rect style="-moz-binding: url(#x)"/>',
    '<g xml:base="https://example.com/"><use href="#x"/></g>',
    '</svg><svg>', '<g>',
])
def test_active_or_malformed_svg_never_reaches_storage(monkeypatch, body):
    monkeypatch.setattr(image_uploads, "_store_image", lambda **_: pytest.fail("invalid SVG was stored"))
    content = f'<svg xmlns="http://www.w3.org/2000/svg">{body}</svg>'.encode()
    with pytest.raises(BusinessError, match="SVG"):
        image_uploads.store_generated_image_object(user_id=7, content=content, mime_type="image/png")


@pytest.mark.parametrize("content", [
    b'<!DOCTYPE svg [<!ENTITY x "expanded">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
    b'<?xml-stylesheet href="https://example.com/a.css"?><svg xmlns="http://www.w3.org/2000/svg"/>',
    b'<html>upstream error</html>', b'<svg xmlns="https://wrong.example"/>', b'not an image',
])
def test_declared_svg_does_not_bypass_validation(content):
    with pytest.raises(BusinessError, match="SVG"):
        image_uploads._extract_image_metadata(content, SVG_MIME)


@pytest.mark.parametrize("body", [
    '<g aria-label="art@example.com" data-note="Use @ or /* in a label"/>',
    '<path id="123"/><use href="#123"/>',
    '<path id="雪花"/><use href="#雪花"/>',
    '<rect style="/* snow */ fill: url(\'#123\'); font-family: \'A@B\'"/>',
    '<rect fill="u\\72l(#雪花)"/>',
    '<style>/* snow */ @media (min-width: 1px) { .snow { fill: url("#雪花"); } }</style>',
    '<rect style="--paint:url(#123);fill:var(--paint)"/>',
])
def test_common_passive_svg_styles_are_preserved(monkeypatch, body):
    content = f'<svg xmlns="http://www.w3.org/2000/svg">{body}</svg>'.encode()
    saved = {}
    def store(**kwargs):
        saved.update(kwargs)
        return "https://cdn.example/" + kwargs["storage_key"]
    monkeypatch.setattr(image_uploads, "_store_image", store)
    image_uploads.store_generated_image_object(user_id=7, content=content, mime_type=SVG_MIME)
    assert saved["content"] == content


@pytest.mark.parametrize("encoding", ["base64", "base64_percent", "percent", "utf8"])
def test_svg_data_urls_round_trip_through_chat_protocol(encoding):
    content = SVG.replace(b"MERRY CHRISTMAS", "冰雪圣诞 + SVG".encode()) + b"\n\n"
    if encoding == "base64":
        value = "data:image/svg+xml;charset=utf-8;base64," + base64.encodebytes(content).decode()
    elif encoding == "base64_percent":
        value = "data:image/svg+xml;base64," + quote_from_bytes(base64.b64encode(content), safe="")
    elif encoding == "percent":
        value = "data:image/svg+xml," + quote_from_bytes(content, safe="")
    else:
        value = "data:image/svg+xml;utf8," + content.decode()
    result = image_generation._extract_chat_completions_image_result({"choices": [{"message": {"content": value}}]}, 1)
    assert result.mime_type == SVG_MIME
    assert result.content == content


@pytest.mark.parametrize("protocol", ["images", "responses"])
def test_inline_svg_url_is_decoded_without_network_or_payload_logging(monkeypatch, caplog, protocol):
    value = "data:image/svg+xml," + quote_from_bytes(SVG, safe="")
    monkeypatch.setattr(image_generation.urllib.request, "urlopen", lambda *_args, **_kwargs: pytest.fail("data URL must be decoded locally"))
    if protocol == "images":
        result = image_generation._extract_openai_images_result({"data": [{"url": value}]}, 1)
    else:
        result = image_generation._extract_responses_image_result({"output": [{"type": "image_generation_call", "url": value}]}, 1)
    assert result.content == SVG
    assert result.mime_type == SVG_MIME
    assert value not in caplog.text


@pytest.mark.parametrize("value", ["data:image/svg+xml;base64", "data:image/svg+xml;base64,", "data:image/svg+xml;base64,@@@", "%%%bad%%%"])
def test_invalid_data_url_or_base64_is_not_silently_accepted(value):
    with pytest.raises(BusinessError) as error:
        image_generation._decode_base64_image(value)
    assert error.value.code == 50213


@pytest.mark.parametrize("encoded", [False, True])
def test_inline_svg_respects_download_limit_before_xml_validation(monkeypatch, encoded):
    monkeypatch.setattr(image_generation.settings, "image_result_download_max_bytes", len(SVG) - 1)
    monkeypatch.setattr(image_generation, "svg_dimensions", lambda *_args, **_kwargs: pytest.fail("oversized payload must not be parsed"))
    value = "data:image/svg+xml;base64," + base64.b64encode(SVG).decode() if encoded else "data:image/svg+xml," + quote_from_bytes(SVG)
    with pytest.raises(BusinessError) as error:
        image_generation._download_image(value, 1)
    assert error.value.code == 50234


@pytest.mark.parametrize("suffix", ["opaque-id", "wrong.png"])
@pytest.mark.parametrize("with_metadata", [False, True])
def test_svg_hot_url_keeps_actual_type_and_does_not_use_pillow_thumbnail(suffix, with_metadata):
    item = {"url": "https://storage.example/art.svg", "r2_url": f"https://hot.example/{suffix}",
            "r2_expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}
    if with_metadata:
        item.update(mime_type=SVG_MIME, width=1200, height=1200, size_bytes=len(SVG), sha256=hashlib.sha256(SVG).hexdigest())
    result = catalog_serializers.output_assets_from_row({"id": 7, "output_image_assets": [item]})[0]
    assert result["mime_type"] == SVG_MIME
    assert result["url"] == item["r2_url"]
    assert "thumbnail_url" not in result
    if with_metadata:
        assert (result["width"], result["height"], result["size_bytes"]) == (1200, 1200, len(SVG))


async def test_result_collection_persists_metadata_for_each_output(monkeypatch):
    writes = []
    async def store(**kwargs):
        writes.append(kwargs)
        return {"url": f"https://storage.example/{len(writes)}", "r2_url": None, "r2_expires_at": None,
                "mime_type": kwargs["mime_type"], "width": 1200, "height": 1200,
                "size_bytes": len(kwargs["content"]), "sha256": hashlib.sha256(kwargs["content"]).hexdigest()}
    async def create(**kwargs):
        return SimpleNamespace(**kwargs["stored_image"])
    class DB:
        async def commit(self):
            pass
    monkeypatch.setattr(catalog, "run_generated_image_storage_in_executor", store)
    monkeypatch.setattr(catalog, "create_generated_image_asset", create)
    generated = image_generation.GeneratedImage(SVG, SVG_MIME, additional_images=(image_generation.GeneratedImage(b"png", "image/png"),))
    _, manifest = await catalog.store_generated_image_collection(DB(), generated=generated, user_id=7, site_id=1,
                                                               qiniu_storage_enabled=False, storage_mode="local")
    assets = catalog_serializers.output_assets_from_row({"id": 7, "output_image_assets": manifest})
    assert [asset["mime_type"] for asset in assets] == [SVG_MIME, "image/png"]
    assert assets[0]["sha256"] == hashlib.sha256(SVG).hexdigest()
    assert len(writes) == 2


def test_excessively_nested_svg_and_css_are_rejected():
    for body in ['<g>' * 130 + '</g>' * 130, '<style>' + '(' * 130 + ')' * 130 + '</style>']:
        with pytest.raises(BusinessError, match="SVG"):
            svg_dimensions(f'<svg xmlns="http://www.w3.org/2000/svg">{body}</svg>'.encode())
