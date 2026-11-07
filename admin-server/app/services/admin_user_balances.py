from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Literal

from app.services.sub2_balance import Sub2BalanceError, Sub2BalanceTarget, get_sub2_balance


logger = logging.getLogger(__name__)

REMOTE_BALANCE_CONCURRENCY = 8
REMOTE_BALANCE_REQUEST_TIMEOUT_SECONDS = 3.0
REMOTE_BALANCE_PAGE_BUDGET_SECONDS = 4.0

BalanceSource = Literal["authoritative", "local", "local_fallback"]
WalletKey = tuple[str, int, Decimal]


@dataclass(frozen=True)
class UserBalanceLookup:
    user_id: int
    local_balance: Decimal
    target: Sub2BalanceTarget | None = None


@dataclass(frozen=True)
class ResolvedUserBalance:
    balance: Decimal
    source: BalanceSource


def display_credit_balance(remote_balance: Decimal, rate: Decimal) -> Decimal:
    if rate <= 0:
        raise ValueError("credit_to_agent_rate must be greater than zero")
    return (remote_balance * rate).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)


def _wallet_key(target: Sub2BalanceTarget) -> WalletKey:
    return (target.base_url.rstrip("/"), target.agent_user_id, target.credit_to_agent_rate)


async def resolve_user_credit_balances(
    lookups: list[UserBalanceLookup],
    *,
    max_concurrency: int = REMOTE_BALANCE_CONCURRENCY,
    page_budget_seconds: float = REMOTE_BALANCE_PAGE_BUDGET_SECONDS,
) -> dict[int, ResolvedUserBalance]:
    """Resolve one live balance per unique upstream wallet within a page-level time budget."""
    if max_concurrency <= 0:
        raise ValueError("max_concurrency must be greater than zero")
    if page_budget_seconds <= 0:
        raise ValueError("page_budget_seconds must be greater than zero")

    targets_by_wallet: dict[WalletKey, Sub2BalanceTarget] = {}
    for lookup in lookups:
        if lookup.target is not None:
            targets_by_wallet.setdefault(_wallet_key(lookup.target), lookup.target)

    semaphore = asyncio.Semaphore(max_concurrency)

    async def fetch(target: Sub2BalanceTarget) -> Decimal:
        async with semaphore:
            remote_balance = await asyncio.to_thread(
                get_sub2_balance,
                target,
                timeout_seconds=REMOTE_BALANCE_REQUEST_TIMEOUT_SECONDS,
            )
        return display_credit_balance(remote_balance, target.credit_to_agent_rate)

    tasks = {wallet: asyncio.create_task(fetch(target)) for wallet, target in targets_by_wallet.items()}
    if tasks:
        done, pending = await asyncio.wait(tasks.values(), timeout=page_budget_seconds)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            logger.warning("admin_balance_sync_budget_exceeded pending_wallets=%s", len(pending))
    else:
        done = set()

    live_balances: dict[WalletKey, Decimal] = {}
    for wallet, task in tasks.items():
        if task not in done or task.cancelled():
            continue
        try:
            live_balances[wallet] = task.result()
        except (Sub2BalanceError, ValueError) as error:
            logger.warning(
                "admin_balance_sync_failed agent_user_id=%s error=%s",
                wallet[1],
                str(error)[:240],
            )
        except Exception:
            logger.exception("admin_balance_sync_unexpected_failure agent_user_id=%s", wallet[1])

    resolved: dict[int, ResolvedUserBalance] = {}
    for lookup in lookups:
        if lookup.target is None:
            resolved[lookup.user_id] = ResolvedUserBalance(lookup.local_balance, "local")
            continue
        live_balance = live_balances.get(_wallet_key(lookup.target))
        resolved[lookup.user_id] = ResolvedUserBalance(
            lookup.local_balance if live_balance is None else live_balance,
            "local_fallback" if live_balance is None else "authoritative",
        )
    return resolved
