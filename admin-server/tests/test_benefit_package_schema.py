import pytest
from pydantic import ValidationError

from app.schemas.benefit_package import BenefitPackageCreate


def package_payload(**overrides):
    payload = {
        "code": "team-30d",
        "name": "团队 30 天",
        "amount_cents": 29900,
        "validity_mode": "fixed_days",
        "validity_value": 30,
        "items": [
            {"resource_type": "credits", "amount": 1000, "grant_mode": "daily", "grant_count": 30},
            {"resource_type": "team_seats", "amount": 5, "grant_mode": "one_time", "scope": "team"},
        ],
    }
    payload.update(overrides)
    return payload


def test_package_schema_accepts_configured_daily_credits_and_team_seats():
    package = BenefitPackageCreate.model_validate(package_payload())

    assert package.items[0].grant_mode == "daily"
    assert package.items[1].amount == 5


def test_subscription_requires_billing_period_validity():
    package = BenefitPackageCreate.model_validate(
        package_payload(
            purchase_mode="subscription",
            billing_interval="month",
            validity_mode="billing_period",
            validity_value=None,
        )
    )
    assert package.validity_mode == "billing_period"


@pytest.mark.parametrize(
    "override",
    [
        {"purchase_mode": "one_time", "validity_mode": "billing_period", "validity_value": None},
        {"purchase_mode": "subscription", "billing_interval": "month", "validity_mode": "fixed_days", "validity_value": 30},
        {"items": [{"resource_type": "api_quota", "amount": 100, "scope": "api_key"}]},
    ],
)
def test_package_schema_rejects_unimplemented_activation_or_scope_modes(override):
    with pytest.raises(ValidationError):
        BenefitPackageCreate.model_validate(package_payload(**override))


@pytest.mark.parametrize(
    "override",
    [
        {"items": [{"resource_type": "model_access", "amount": 1}]},
        {"items": [{"resource_type": "team_seats", "amount": 1}]},
        {"items": [{"resource_type": "credits", "amount": 100, "grant_mode": "daily"}]},
        {"validity_mode": "fixed_days", "validity_value": None},
    ],
)
def test_package_schema_rejects_unsupported_or_incomplete_entitlements(override):
    with pytest.raises(ValidationError):
        BenefitPackageCreate.model_validate(package_payload(**override))
