from decimal import Decimal

from app.services.zpay import ZPayClient, ZPayConfig, verify_zpay_sign, zpay_sign


def test_zpay_sign_excludes_sign_type_and_empty_values():
    base = {"pid": "1001", "type": "alipay", "out_trade_no": "R001", "money": "10.00"}
    with_extra = {**base, "sign": "ignored", "sign_type": "MD5", "clientip": ""}

    assert zpay_sign(base, "secret") == zpay_sign(with_extra, "secret")


def test_zpay_verify_notification_parses_signed_payload():
    params = {
        "pid": "1001",
        "out_trade_no": "R001",
        "trade_no": "T001",
        "money": "10.00",
        "trade_status": "TRADE_SUCCESS",
    }
    params["sign"] = zpay_sign(params, "secret")
    params["sign_type"] = "MD5"

    assert verify_zpay_sign(params, "secret")

    client = ZPayClient(
        ZPayConfig(
            pid="1001",
            pkey="secret",
            api_base="https://z-pay.cn/mapi.php",
            notify_url="https://example.com/recharge/zpay/notify",
            return_url="https://example.com/billing/recharge",
        )
    )
    notification = client.parse_notification("&".join(f"{key}={value}" for key, value in params.items()))

    assert notification.out_trade_no == "R001"
    assert notification.trade_no == "T001"
    assert notification.money == Decimal("10.00")
    assert notification.trade_status == "TRADE_SUCCESS"
