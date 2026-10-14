from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine

from app.api.routes.catalog import image_assets_table, resolve_input_image_urls
from app.core.exceptions import BusinessError
from app.services.asset_urls import asset_url_variants


@contextmanager
def asset_session(rows):
    """Execute the actual ownership query against an isolated in-memory DB."""
    engine = create_engine("sqlite:///:memory:")
    image_assets_table.create(engine)
    try:
        with engine.begin() as connection:
            connection.execute(image_assets_table.insert(), rows)

            class Session:
                async def execute(self, statement):
                    return connection.execute(statement)

            yield Session()
    finally:
        engine.dispose()


async def test_com_reference_urls_resolve_existing_three_uploaded_images_in_order():
    names = [
        "3185a2ca9ca440f78547c531d5314ba9.png",
        "8920a2f8fe0246a78e01c75bc6abf7be.png",
        "910cc7c4ad58422fb0f0311d03468a5f.png",
    ]
    origin_urls = [f"https://magic.shyfai.cn/image2-assets/images/19/{name}" for name in names]
    edge_urls = [url.replace("magic.shyfai.cn", "magic.shyfai.com") for url in origin_urls]
    rows = [
        {"id": image_id, "site_id": 1, "user_id": 19, "url": url, "local_url": url, "r2_url": None}
        for image_id, url in zip([65076, 65077, 65081], origin_urls, strict=True)
    ]
    with asset_session(list(reversed(rows))) as db:
        resolved = await resolve_input_image_urls(
            db, site_id=1, user_id=19, max_input_images=4,
            payload={"input_image_ids": [65076, 65077, 65081], "input_image_url": edge_urls[0], "input_image_urls": edge_urls},
        )
    assert resolved == origin_urls


@pytest.mark.parametrize("site_id,user_id", [(1, 20), (2, 19)])
async def test_edge_alias_cannot_reference_another_owner_or_site(site_id, user_id):
    origin = "https://magic.shyfai.cn/image2-assets/images/19/private.png"
    with asset_session([{"id": 1, "site_id": 1, "user_id": 19, "url": origin}]) as db:
        with pytest.raises(BusinessError) as error:
            await resolve_input_image_urls(
                db, site_id=site_id, user_id=user_id, max_input_images=4,
                payload={"input_image_urls": [origin.replace("magic.shyfai.cn", "magic.shyfai.com")]},
            )
    assert error.value.code == 40420


async def test_edge_alias_for_local_mirror_keeps_existing_cdn_preference():
    cdn = "https://openagent-cdn.shyfai.cn/image2-assets/images/19/input.png"
    origin = "https://magic.shyfai.cn/image2-assets/images/19/input.png"
    with asset_session([{"id": 1, "site_id": 1, "user_id": 19, "url": cdn, "local_url": origin}]) as db:
        resolved = await resolve_input_image_urls(
            db, site_id=1, user_id=19, max_input_images=4,
            payload={"input_image_url": origin.replace("magic.shyfai.cn", "magic.shyfai.com")},
        )
    assert resolved == [cdn]


async def test_origin_alias_accepts_historic_com_record_without_changing_stored_url():
    edge = "https://magic.shyfai.com/image2-assets/generated/19/input.png"
    with asset_session([{"id": 1, "site_id": 1, "user_id": 19, "url": edge}]) as db:
        resolved = await resolve_input_image_urls(
            db, site_id=1, user_id=19, max_input_images=4,
            payload={"input_image_url": edge.replace("magic.shyfai.com", "magic.shyfai.cn")},
        )
    assert resolved == [edge]


async def test_missing_image_still_rejected_even_with_valid_input_id():
    origin = "https://magic.shyfai.cn/image2-assets/images/19/owned.png"
    with asset_session([{"id": 1, "site_id": 1, "user_id": 19, "url": origin}]) as db:
        with pytest.raises(BusinessError) as error:
            await resolve_input_image_urls(
                db, site_id=1, user_id=19, max_input_images=4,
                payload={"input_image_ids": [1], "input_image_urls": ["https://magic.shyfai.com/image2-assets/images/19/missing.png"]},
            )
    assert error.value.code == 40420


@pytest.mark.parametrize("url", [
    "https://magic.shyfai.com.evil.test/image2-assets/images/private.png",
    "https://magic.shyfai.com@evil.test/image2-assets/images/private.png",
    "https://magic.shyfai.com:444/image2-assets/images/private.png",
    "http://magic.shyfai.com/image2-assets/images/private.png",
    "https://magic.shyfai.com/api/private.png",
    "https://other.test/file.png?next=https://magic.shyfai.com/image2-assets/images/private.png",
])
def test_alias_is_limited_to_exact_magic_https_asset_prefix(url):
    assert asset_url_variants(url) == (url,)


async def test_image_limit_is_checked_before_alias_expansion():
    class NoQuerySession:
        async def execute(self, statement):
            pytest.fail("over-limit payload must not query the database")

    with pytest.raises(BusinessError) as error:
        await resolve_input_image_urls(
            NoQuerySession(), site_id=1, user_id=19, max_input_images=1,
            payload={"input_image_urls": ["https://magic.shyfai.com/image2-assets/images/19/one.png", "https://magic.shyfai.com/image2-assets/images/19/two.png"]},
        )
    assert error.value.code == 40001
