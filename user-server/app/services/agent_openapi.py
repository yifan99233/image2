from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal

from app.models.agent import AgentConfig


class AgentAPIError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, reason: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason


@dataclass(frozen=True)
class AgentUser:
    id: int
    balance: Decimal
    email: str
    password: str


@dataclass(frozen=True)
class AgentAPIKey:
    id: int | None
    key: str
    name: str = ""
    group_id: int | None = None
    quota: Decimal = Decimal("0")
    quota_used: Decimal = Decimal("0")
    rate_limit_5h: Decimal = Decimal("0")
    rate_limit_5h_used: Decimal = Decimal("0")
    rate_limit_1d: Decimal = Decimal("0")
    rate_limit_1d_used: Decimal = Decimal("0")
    rate_limit_7d: Decimal = Decimal("0")
    rate_limit_7d_used: Decimal = Decimal("0")
    status: str = ""
    group_name: str = ""
    group_platform: str = ""
    expires_at: str | None = None
    created_at: str | None = None
    last_used_at: str | None = None
    last_used_ip: str = ""
    current_concurrency: int = 0
    max_concurrency: int = 0
    usage_5h: Decimal = Decimal("0")
    usage_1d: Decimal = Decimal("0")
    usage_7d: Decimal = Decimal("0")
    reset_5h_at: str | None = None
    reset_1d_at: str | None = None
    reset_7d_at: str | None = None
    today_actual_cost: Decimal = Decimal("0")
    total_actual_cost: Decimal = Decimal("0")
    ip_whitelist: tuple[str, ...] = ()
    ip_blacklist: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentAPIKeyUsage:
    api_key_id: int
    today_actual_cost: Decimal = Decimal("0")
    total_actual_cost: Decimal = Decimal("0")


@dataclass(frozen=True)
class AgentAPIGroup:
    id: int
    name: str
    platform: str = ""


def _extract_data(payload: object) -> object:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _extract_id(payload: object) -> int | None:
    data = _extract_data(payload)
    if isinstance(data, dict):
        value = data.get("id") or data.get("user_id")
        if value is not None:
            return int(value)
    return None


def _extract_balance(payload: object) -> Decimal:
    data = _extract_data(payload)
    if isinstance(data, dict):
        value = data.get("balance")
        if value is not None:
            return Decimal(str(value))
    return Decimal("0")


def _extract_key(payload: object) -> AgentAPIKey | None:
    data = _extract_data(payload)
    if not isinstance(data, dict):
        return None
    nested_key = data.get("api_key")
    if isinstance(nested_key, dict):
        data = nested_key
    key = str(data.get("key") or "")
    key_id = data.get("id")
    if key_id is None and not key:
        return None
    group_id = data.get("group_id")
    group = data.get("group") if isinstance(data.get("group"), dict) else {}

    def decimal_field(name: str) -> Decimal:
        return Decimal(str(data.get(name) or 0))

    return AgentAPIKey(
        id=int(key_id) if key_id is not None else None,
        key=key,
        name=str(data.get("name") or ""),
        group_id=int(group_id) if group_id is not None else None,
        quota=Decimal(str(data.get("quota") or 0)),
        quota_used=Decimal(str(data.get("quota_used") or 0)),
        rate_limit_5h=Decimal(str(data.get("rate_limit_5h") or 0)),
        rate_limit_5h_used=Decimal(str(data.get("rate_limit_5h_used") or 0)),
        rate_limit_1d=Decimal(str(data.get("rate_limit_1d") or 0)),
        rate_limit_1d_used=Decimal(str(data.get("rate_limit_1d_used") or 0)),
        rate_limit_7d=Decimal(str(data.get("rate_limit_7d") or 0)),
        rate_limit_7d_used=Decimal(str(data.get("rate_limit_7d_used") or 0)),
        status=str(data.get("status") or ""),
        group_name=str(group.get("name") or data.get("group_name") or ""),
        group_platform=str(group.get("platform") or data.get("platform") or ""),
        expires_at=str(data.get("expires_at")) if data.get("expires_at") else None,
        created_at=str(data.get("created_at")) if data.get("created_at") else None,
        last_used_at=str(data.get("last_used_at")) if data.get("last_used_at") else None,
        last_used_ip=str(data.get("last_used_ip") or ""),
        current_concurrency=int(data.get("current_concurrency") or 0),
        max_concurrency=int(data.get("max_concurrency") or data.get("concurrency") or 0),
        usage_5h=decimal_field("usage_5h"),
        usage_1d=decimal_field("usage_1d"),
        usage_7d=decimal_field("usage_7d"),
        reset_5h_at=str(data.get("reset_5h_at")) if data.get("reset_5h_at") else None,
        reset_1d_at=str(data.get("reset_1d_at")) if data.get("reset_1d_at") else None,
        reset_7d_at=str(data.get("reset_7d_at")) if data.get("reset_7d_at") else None,
        today_actual_cost=decimal_field("today_actual_cost"),
        total_actual_cost=decimal_field("total_actual_cost"),
        ip_whitelist=tuple(str(value) for value in (data.get("ip_whitelist") or []) if value),
        ip_blacklist=tuple(str(value) for value in (data.get("ip_blacklist") or []) if value),
    )


def _extract_groups(payload: object) -> list[AgentAPIGroup]:
    data = _extract_data(payload)
    rows = data.get("items") if isinstance(data, dict) and isinstance(data.get("items"), list) else data
    if not isinstance(rows, list):
        return []
    return [
        AgentAPIGroup(id=int(row["id"]), name=str(row.get("name") or ""), platform=str(row.get("platform") or ""))
        for row in rows
        if isinstance(row, dict) and row.get("id") is not None
    ]


def _extract_items(payload: object) -> list[object]:
    data = _extract_data(payload)
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(data, list):
        return data
    return []


def _extract_page(payload: object, page: int, page_size: int) -> dict:
    data = _extract_data(payload)
    if not isinstance(data, dict):
        return {"items": [], "total": 0, "page": page, "page_size": page_size}
    return {
        "items": data.get("items") if isinstance(data.get("items"), list) else [],
        "total": int(data.get("total") or 0),
        "page": int(data.get("page") or page),
        "page_size": int(data.get("page_size") or page_size),
    }


class AgentOpenAPIClient:
    API_KEY_LIST_PAGE_SIZE = 100
    API_KEY_LIST_MAX_PAGES = 100
    API_KEY_USAGE_BATCH_SIZE = 100

    def __init__(self, config: AgentConfig) -> None:
        self.base_url = (config.base_url or "").rstrip("/")
        self.admin_api_key = (config.admin_api_key or "").strip()
        self.user_concurrency = int(config.user_concurrency or 5)
        self.user_rpm_limit = int(config.user_rpm_limit or 0)
        if not self.base_url or not self.admin_api_key:
            raise AgentAPIError("agent 接入未配置 Base URL 或管理员 Key")

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        idempotency_key: str | None = None,
        bearer_token: str | None = None,
    ) -> object:
        normalized_path = path if path.startswith("/") else f"/{path}"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.admin_api_key,
            **({"Idempotency-Key": idempotency_key} if idempotency_key else {}),
        }
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        request = urllib.request.Request(
            f"{self.base_url}{normalized_path}",
            method=method,
            headers=headers,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="ignore")
            reason = ""
            message = detail[:300]
            try:
                error_payload = json.loads(detail)
                if isinstance(error_payload, dict):
                    reason = str(error_payload.get("reason") or "")
                    message = str(error_payload.get("message") or detail)[:300]
            except json.JSONDecodeError:
                pass
            raise AgentAPIError(
                f"agent 接口返回 {error.code}: {message}",
                status_code=error.code,
                reason=reason,
            ) from error
        except urllib.error.URLError as error:
            raise AgentAPIError(f"agent 接口连接失败: {error.reason}") from error
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as error:
            raise AgentAPIError("agent 接口返回了非 JSON 响应") from error
        if isinstance(payload, dict) and int(payload.get("code", 0) or 0) != 0:
            code = int(payload.get("code", 0) or 0)
            raise AgentAPIError(
                str(payload.get("message") or payload.get("reason") or "agent 接口返回失败"),
                status_code=code if 100 <= code <= 599 else None,
                reason=str(payload.get("reason") or ""),
            )
        return payload

    def user_email_exists(self, email: str) -> bool:
        normalized_email = email.strip().casefold()
        query = urllib.parse.urlencode(
            {
                "page": 1,
                "page_size": 20,
                "search": email.strip(),
            }
        )
        response = self._request("GET", f"/api/v1/admin/users?{query}")
        data = _extract_data(response)
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise AgentAPIError("agent 用户查重响应格式不正确")
        return any(
            isinstance(item, dict)
            and str(item.get("email") or "").strip().casefold() == normalized_email
            for item in items
        )

    def create_user(self, *, user_id: int, username: str, email: str, password: str | None = None, allowed_groups: list[int]) -> AgentUser:
        password = password or secrets.token_urlsafe(24)
        payload = {
            "email": email,
            "username": username,
            "password": password,
            "notes": f"image2 user_id={user_id}",
            "balance": 0,
            "concurrency": self.user_concurrency,
            "rpm_limit": self.user_rpm_limit,
            "allowed_groups": allowed_groups,
        }
        response = self._request("POST", "/api/v1/admin/users", payload, f"image2-agent-user-{user_id}")
        agent_user_id = _extract_id(response)
        if agent_user_id is None:
            raise AgentAPIError("agent 创建账号响应缺少用户 ID")
        return AgentUser(id=agent_user_id, balance=_extract_balance(response), email=email, password=password)

    def login_user(self, *, email: str, password: str) -> str:
        response = self._request("POST", "/api/v1/auth/login", {"email": email, "password": password})
        data = _extract_data(response)
        if not isinstance(data, dict):
            raise AgentAPIError("agent 登录响应格式不正确")
        token = data.get("access_token")
        if not token:
            raise AgentAPIError("agent 登录响应缺少 access_token")
        return str(token)

    def reset_user_password(self, *, agent_user_id: int, password: str, allowed_groups: list[int]) -> AgentUser:
        response = self._request(
            "PUT",
            f"/api/v1/admin/users/{agent_user_id}",
            {"password": password, "allowed_groups": allowed_groups},
        )
        agent_user_id_from_response = _extract_id(response)
        if agent_user_id_from_response is None:
            raise AgentAPIError("agent 更新账号响应缺少用户 ID")
        return AgentUser(id=agent_user_id_from_response, balance=_extract_balance(response), email="", password=password)

    def update_user_allowed_groups(self, *, agent_user_id: int, allowed_groups: list[int]) -> None:
        if agent_user_id <= 0:
            raise ValueError("agent_user_id must be greater than zero")
        self._request(
            "PUT",
            f"/api/v1/admin/users/{agent_user_id}",
            {
                "allowed_groups": sorted(
                    {int(group_id) for group_id in allowed_groups if int(group_id) > 0}
                )
            },
        )

    def get_user(self, agent_user_id: int) -> AgentUser:
        response = self._request("GET", f"/api/v1/admin/users/{agent_user_id}")
        return AgentUser(id=agent_user_id, balance=_extract_balance(response), email="", password="")

    def change_balance(
        self,
        *,
        agent_user_id: int,
        amount: Decimal,
        operation: str,
        notes: str,
        idempotency_key: str,
    ) -> AgentUser:
        if operation not in {"add", "subtract"}:
            raise ValueError("operation must be add or subtract")
        if amount <= 0:
            raise ValueError("amount must be greater than zero")
        response = self._request(
            "POST",
            f"/api/v1/admin/users/{agent_user_id}/balance",
            {"balance": float(amount), "operation": operation, "notes": notes[:255]},
            idempotency_key,
        )
        return AgentUser(id=agent_user_id, balance=_extract_balance(response), email="", password="")

    def add_balance(
        self,
        *,
        agent_user_id: int,
        amount: Decimal,
        idempotency_key: str,
        notes: str = "image2 账户加款",
    ) -> AgentUser:
        return self.change_balance(
            agent_user_id=agent_user_id,
            amount=amount,
            operation="add",
            notes=notes,
            idempotency_key=idempotency_key,
        )

    def subtract_balance(self, *, agent_user_id: int, amount: Decimal, idempotency_key: str, notes: str) -> AgentUser:
        return self.change_balance(
            agent_user_id=agent_user_id,
            amount=amount,
            operation="subtract",
            notes=notes,
            idempotency_key=idempotency_key,
        )

    def list_user_api_keys(self, agent_user_id: int) -> list[AgentAPIKey]:
        keys: list[AgentAPIKey] = []
        seen_key_ids: set[int] = set()
        for page in range(1, self.API_KEY_LIST_MAX_PAGES + 1):
            response = self._request(
                "GET",
                f"/api/v1/admin/users/{agent_user_id}/api-keys"
                f"?page={page}&page_size={self.API_KEY_LIST_PAGE_SIZE}",
            )
            page_data = _extract_page(response, page, self.API_KEY_LIST_PAGE_SIZE)
            items = page_data["items"]
            if not items:
                return keys

            for item in items:
                key = _extract_key(item)
                if key is None:
                    continue
                if key.id is not None:
                    key_id = int(key.id)
                    if key_id in seen_key_ids:
                        continue
                    seen_key_ids.add(key_id)
                keys.append(key)

            total = max(0, int(page_data["total"]))
            page_size = max(1, int(page_data["page_size"]))
            if (total and len(keys) >= total) or len(items) < page_size:
                return keys

        raise AgentAPIError("agent Key 列表分页超过安全上限")

    def get_api_keys_usage(self, *, token: str, api_key_ids: list[int]) -> dict[int, AgentAPIKeyUsage]:
        normalized_ids = sorted({int(key_id) for key_id in api_key_ids if int(key_id) > 0})
        usage_by_key_id: dict[int, AgentAPIKeyUsage] = {}
        for offset in range(0, len(normalized_ids), self.API_KEY_USAGE_BATCH_SIZE):
            batch = normalized_ids[offset : offset + self.API_KEY_USAGE_BATCH_SIZE]
            response = self._request(
                "POST",
                "/api/v1/usage/dashboard/api-keys-usage",
                {"api_key_ids": batch},
                bearer_token=token,
            )
            data = _extract_data(response)
            stats = data.get("stats") if isinstance(data, dict) else None
            if not isinstance(stats, dict):
                raise AgentAPIError("agent Key 用量响应格式不正确")
            for raw_key_id, raw_usage in stats.items():
                if not isinstance(raw_usage, dict):
                    continue
                value = raw_usage.get("api_key_id", raw_key_id)
                try:
                    key_id = int(value)
                except (TypeError, ValueError):
                    continue
                usage_by_key_id[key_id] = AgentAPIKeyUsage(
                    api_key_id=key_id,
                    today_actual_cost=Decimal(str(raw_usage.get("today_actual_cost") or 0)),
                    total_actual_cost=Decimal(str(raw_usage.get("total_actual_cost") or 0)),
                )
        return usage_by_key_id

    def list_groups(self, *, include_inactive: bool = False) -> list[AgentAPIGroup]:
        query = urllib.parse.urlencode({"include_inactive": "true"}) if include_inactive else ""
        path = f"/api/v1/admin/groups/all?{query}" if query else "/api/v1/admin/groups/all"
        return _extract_groups(self._request("GET", path))

    def create_user_api_key(
        self,
        *,
        token: str,
        name: str,
        group_id: int | None,
        idempotency_key: str,
        **options: object,
    ) -> AgentAPIKey:
        payload: dict[str, object] = {"name": name, "group_id": group_id}
        payload.update({key: value for key, value in options.items() if value is not None})
        response = self._request("POST", "/api/v1/keys", payload, idempotency_key, bearer_token=token)
        key = _extract_key(response)
        if key is None:
            raise AgentAPIError("agent 创建 Key 响应缺少 key")
        return key

    def update_user_api_key(self, *, token: str, key_id: int, payload: dict[str, object]) -> AgentAPIKey:
        if key_id <= 0:
            raise ValueError("key_id must be greater than zero")
        response = self._request("PUT", f"/api/v1/keys/{key_id}", payload, bearer_token=token)
        key = _extract_key(response)
        if key is None:
            raise AgentAPIError("agent 更新 Key 响应缺少 API Key")
        return key

    def delete_user_api_key(self, *, token: str, key_id: int) -> None:
        if key_id <= 0:
            raise ValueError("key_id must be greater than zero")
        self._request("DELETE", f"/api/v1/keys/{key_id}", bearer_token=token)

    def update_api_key(self, key_id: int, *, quota: Decimal) -> AgentAPIKey:
        if key_id <= 0:
            raise ValueError("key_id must be greater than zero")
        if quota < 0:
            raise ValueError("quota must not be negative")
        response = self._request(
            "PUT",
            f"/api/v1/admin/api-keys/{key_id}",
            {"quota": float(quota)},
        )
        key = _extract_key(response)
        if key is None:
            raise AgentAPIError("agent 更新 Key 响应缺少 API Key")
        return key

    def list_user_usage(
        self,
        *,
        agent_user_id: int,
        page: int,
        page_size: int,
        api_key_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        params: dict[str, object] = {
            "user_id": agent_user_id,
            "page": page,
            "page_size": page_size,
            "sort_by": "created_at",
            "sort_order": "desc",
        }
        if api_key_id is not None:
            params["api_key_id"] = api_key_id
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        query = urllib.parse.urlencode(params)
        response = self._request("GET", f"/api/v1/admin/usage?{query}")
        return _extract_page(response, page, page_size)
