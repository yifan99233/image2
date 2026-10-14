from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal


class ZPayError(Exception):
    pass


@dataclass(frozen=True)
class ZPayConfig:
    pid: str
    pkey: str
    api_base: str
    notify_url: str
    return_url: str
    payment_type: str = "alipay"
    payment_mode: str = "qrcode"
    timeout_seconds: int = 10


@dataclass(frozen=True)
class ZPayCreateResult:
    trade_no: str
    pay_url: str
    qr_code: str


@dataclass(frozen=True)
class ZPayNotification:
    out_trade_no: str
    trade_no: str
    money: Decimal
    trade_status: str
    raw: str


def normalize_api_base(api_base: str) -> str:
    base = api_base.strip().rstrip("/")
    for suffix in ("/submit.php", "/mapi.php", "/api.php"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
            break
    return base


def zpay_sign(params: dict[str, str], pkey: str) -> str:
    parts = []
    for key in sorted(params):
        value = params[key]
        if key in {"sign", "sign_type"} or value == "":
            continue
        parts.append(f"{key}={value}")
    raw = "&".join(parts) + pkey
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def verify_zpay_sign(params: dict[str, str], pkey: str) -> bool:
    sign = params.get("sign", "")
    if not sign:
        return False
    return hmac.compare_digest(zpay_sign(params, pkey), sign)


class ZPayClient:
    def __init__(self, config: ZPayConfig):
        missing = [key for key, value in {
            "pid": config.pid,
            "pkey": config.pkey,
            "api_base": config.api_base,
            "notify_url": config.notify_url,
            "return_url": config.return_url,
        }.items() if not value.strip()]
        if missing:
            raise ZPayError(f"ZPay 配置缺失：{', '.join(missing)}")
        self.config = ZPayConfig(
            pid=config.pid.strip(),
            pkey=config.pkey.strip(),
            api_base=normalize_api_base(config.api_base),
            notify_url=config.notify_url.strip(),
            return_url=config.return_url.strip(),
            payment_type=(config.payment_type or "alipay").strip(),
            payment_mode=(config.payment_mode or "qrcode").strip(),
            timeout_seconds=config.timeout_seconds,
        )

    def create_payment(self, *, order_no: str, amount_yuan: str, subject: str, client_ip: str = "") -> ZPayCreateResult:
        params = {
            "pid": self.config.pid,
            "type": self.config.payment_type,
            "out_trade_no": order_no,
            "notify_url": self.config.notify_url,
            "return_url": self.config.return_url,
            "name": subject,
            "money": amount_yuan,
            "clientip": client_ip,
        }
        params["sign"] = zpay_sign(params, self.config.pkey)
        params["sign_type"] = "MD5"

        if self.config.payment_mode == "popup":
            return ZPayCreateResult(
                trade_no="",
                pay_url=f"{self.config.api_base}/submit.php?{urllib.parse.urlencode(params)}",
                qr_code="",
            )

        body = urllib.parse.urlencode(params).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.api_base}/mapi.php",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read(1024 * 1024)
        except Exception as error:  # noqa: BLE001 - surface provider transport errors.
            raise ZPayError(f"ZPay 下单请求失败：{error}") from error

        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as error:  # noqa: BLE001
            raise ZPayError("ZPay 下单返回无法解析") from error

        if int(payload.get("code") or 0) != 1:
            raise ZPayError(str(payload.get("msg") or "ZPay 下单失败"))

        pay_url = str(payload.get("payurl") or payload.get("payurl2") or "")
        qr_code = str(payload.get("qrcode") or "")
        return ZPayCreateResult(trade_no=str(payload.get("trade_no") or ""), pay_url=pay_url, qr_code=qr_code)

    def parse_notification(self, raw: str) -> ZPayNotification:
        values = urllib.parse.parse_qs(raw, keep_blank_values=True)
        params = {key: value[0] if value else "" for key, value in values.items()}
        if not verify_zpay_sign(params, self.config.pkey):
            raise ZPayError("ZPay 回调验签失败")
        try:
            money = Decimal(params.get("money", "0"))
        except Exception as error:  # noqa: BLE001
            raise ZPayError("ZPay 回调金额无效") from error
        return ZPayNotification(
            out_trade_no=params.get("out_trade_no", ""),
            trade_no=params.get("trade_no", ""),
            money=money,
            trade_status=params.get("trade_status", ""),
            raw=raw,
        )
