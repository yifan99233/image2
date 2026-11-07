from datetime import UTC, datetime

from app.models.benefit_package import BenefitPackage, BenefitPackageItem
from app.services.benefit_packages import _aggregate_entitlement_rows, grant_schedule, package_expires_at
from decimal import Decimal


def test_daily_grants_are_bounded_by_package_expiry():
    package = BenefitPackage(validity_mode="fixed_days", validity_value=3)
    item = BenefitPackageItem(resource_type="credits", amount=1000, grant_mode="daily", grant_count=10, expiry_policy="grant_period")
    starts_at = datetime(2026, 12, 1, 10, tzinfo=UTC)
    expires_at = package_expires_at(package, starts_at)

    windows = grant_schedule(package, item, starts_at=starts_at, package_expires=expires_at)

    assert len(windows) == 3
    assert windows[0].expires_at == windows[1].grant_at
    assert windows[-1].expires_at == expires_at


def test_month_end_subscription_period_does_not_overflow():
    package = BenefitPackage(validity_mode="billing_period", billing_interval="month")
    starts_at = datetime(2026, 1, 31, 10, tzinfo=UTC)

    assert package_expires_at(package, starts_at) == datetime(2026, 2, 28, 10, tzinfo=UTC)


def test_entitlement_aggregation_supports_sum_max_and_latest_replace():
    starts_at = datetime(2026, 12, 1, 10, tzinfo=UTC)
    assert _aggregate_entitlement_rows(
        [
            (Decimal("2"), "sum", starts_at, 1),
            (Decimal("5"), "max", starts_at, 2),
            (Decimal("3"), "replace", starts_at, 3),
        ]
    ) == Decimal("10")
