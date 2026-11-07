from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


class Sub2BalanceError(Exception):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Sub2BalanceTarget:
    base_url: str
    admin_api_key: str
    agent_user_id: int
    credit_to_agent_rate: Decimal


def to_sub2_amount(credit_amount: int, rate: Decimal) -> Decimal:
    if credit_amount <= 0:
        raise ValueError("credit_amount must be greater than zero")
    if rate <= 0:
        raise ValueError("credit_to_agent_rate must be greater than zero")
    amount = (Decimal(credit_amount) / rate).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise ValueError("converted amount is below Sub2API precision")
    return amount


def change_sub2_balance(
    target: Sub2BalanceTarget,
    *,
    amount: Decimal,
    operation: str,
    idempotency_key: str,
    notes: str,
) -> Decimal:
    if operation not in {"add", "subtract"}:
        raise ValueError("operation must be add or subtract")
    if amount <= 0:
        raise ValueError("amount must be greater than zero")
    request = urllib.request.Request(
        f"{target.base_url.rstrip('/')}/api/v1/admin/users/{target.agent_user_id}/balance",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": target.admin_api_key,
            "Idempotency-Key": idempotency_key,
        },
        data=json.dumps(
            {
                "balance": float(amount),
                "operation": operation,
                "notes": notes[:255],
            }
        ).encode("utf-8"),
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="ignore")
        status_code = 400 if 400 <= error.code < 500 else 502
        raise Sub2BalanceError(f"账户服务返回 HTTP {error.code}: {detail[:240]}", status_code=status_code) from error
    except urllib.error.URLError as error:
        raise Sub2BalanceError(f"账户服务连接失败: {error.reason}") from error
    except TimeoutError as error:
        raise Sub2BalanceError("账户服务请求超时") from error
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as error:
        raise Sub2BalanceError("账户服务返回了非 JSON 响应") from error
    if isinstance(payload, dict) and int(payload.get("code", 0) or 0) != 0:
        raise Sub2BalanceError(
            str(payload.get("message") or payload.get("reason") or "账户余额调整失败"),
            status_code=400,
        )
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    if not isinstance(data, dict) or data.get("balance") is None:
        raise Sub2BalanceError("账户服务响应缺少余额")
    return Decimal(str(data["balance"]))


def get_sub2_balance(target: Sub2BalanceTarget, *, timeout_seconds: float = 5) -> Decimal:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    request = urllib.request.Request(
        f"{target.base_url.rstrip('/')}/api/v1/admin/users/{target.agent_user_id}",
        method="GET",
        headers={"x-api-key": target.admin_api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="ignore")
        raise Sub2BalanceError(f"账户服务返回 HTTP {error.code}: {detail[:240]}") from error
    except urllib.error.URLError as error:
        raise Sub2BalanceError(f"账户服务连接失败: {error.reason}") from error
    except TimeoutError as error:
        raise Sub2BalanceError("账户服务请求超时") from error
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as error:
        raise Sub2BalanceError("账户服务返回了非 JSON 响应") from error
    if isinstance(payload, dict) and int(payload.get("code", 0) or 0) != 0:
        raise Sub2BalanceError(str(payload.get("message") or payload.get("reason") or "账户余额查询失败"))
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    if not isinstance(data, dict) or data.get("balance") is None:
        raise Sub2BalanceError("账户服务响应缺少余额")
    return Decimal(str(data["balance"]))
