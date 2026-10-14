from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.endpoints.admin_data import create_model_price_version, explicit_model_price_entries
from app.core.exceptions import AppException
from app.models.model_price import ModelPrice


def test_explicit_price_entries_keep_each_exact_specification():
    entries = explicit_model_price_entries(
        {
            "price_entries": [
                {
                    "work_type": "text_to_image",
                    "resolution": "4k",
                    "aspect_ratio": "16:9",
                    "credit_cost": 24,
                },
                {
                    "work_type": "image_to_image",
                    "resolution": "4k",
                    "aspect_ratio": "16:9",
                    "credit_cost": 30,
                },
            ]
        },
        output_count=1,
    )

    assert entries == [
        {
            "work_type": "text_to_image",
            "resolution": "4k",
            "aspect_ratio": "16:9",
            "output_count": 1,
            "credit_cost": 24,
        },
        {
            "work_type": "image_to_image",
            "resolution": "4k",
            "aspect_ratio": "16:9",
            "output_count": 1,
            "credit_cost": 30,
        },
    ]


def test_explicit_price_entries_reject_duplicate_cells():
    duplicate = {
        "work_type": "text_to_image",
        "resolution": "4k",
        "aspect_ratio": "16:9",
        "credit_cost": 24,
    }

    with pytest.raises(AppException) as exc_info:
        explicit_model_price_entries({"price_entries": [duplicate, duplicate]}, output_count=1)
    assert "重复规格" in exc_info.value.message


def test_explicit_price_entries_reject_fractional_credits():
    with pytest.raises(AppException) as exc_info:
        explicit_model_price_entries(
            {
                "price_entries": [
                    {
                        "work_type": "text_to_image",
                        "resolution": "4k",
                        "aspect_ratio": "16:9",
                        "credit_cost": 24.5,
                    }
                ]
            },
            output_count=1,
        )
    assert "正整数" in exc_info.value.message


@pytest.mark.asyncio
async def test_price_change_creates_a_new_version_and_deactivates_the_old_one():
    active_price = ModelPrice(
        id=10,
        site_id=2,
        model_id=132,
        work_type="text_to_image",
        resolution="4k",
        aspect_ratio="16:9",
        output_count=1,
        credit_cost=24,
        version=1,
        is_active=True,
        change_reason="old",
    )
    db = MagicMock()
    scalar_result = MagicMock()
    scalar_result.all.return_value = [active_price]
    db.scalars = AsyncMock(return_value=scalar_result)
    db.scalar = AsyncMock(return_value=1)
    db.flush = AsyncMock()

    new_price, replaced_ids, created = await create_model_price_version(
        db,
        site_id=2,
        model_id=132,
        work_type="text_to_image",
        resolution="4k",
        aspect_ratio="16:9",
        output_count=1,
        credit_cost=30,
        reason="raise 4k price",
    )

    assert created is True
    assert replaced_ids == [10]
    assert active_price.is_active is False
    assert new_price.version == 2
    assert new_price.credit_cost == 30
    assert new_price.is_active is True
    db.add.assert_called_once_with(new_price)
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_unchanged_price_does_not_create_another_version():
    active_price = ModelPrice(
        id=10,
        site_id=2,
        model_id=132,
        work_type="text_to_image",
        resolution="4k",
        aspect_ratio="16:9",
        output_count=1,
        credit_cost=24,
        version=1,
        is_active=True,
        change_reason="current",
    )
    db = MagicMock()
    scalar_result = MagicMock()
    scalar_result.all.return_value = [active_price]
    db.scalars = AsyncMock(return_value=scalar_result)
    db.scalar = AsyncMock()
    db.flush = AsyncMock()

    price, replaced_ids, created = await create_model_price_version(
        db,
        site_id=2,
        model_id=132,
        work_type="text_to_image",
        resolution="4k",
        aspect_ratio="16:9",
        output_count=1,
        credit_cost=24,
        reason="same price",
    )

    assert price is active_price
    assert replaced_ids == []
    assert created is False
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
