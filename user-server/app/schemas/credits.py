from decimal import Decimal
from pydantic import BaseModel


class CreditBalanceOut(BaseModel):
    balance: Decimal
    gift_balance: Decimal = Decimal("0")
    total_gifted: Decimal = Decimal("0")
    total_recharged: Decimal
    total_consumed: Decimal


class CreditLedgerOut(BaseModel):
    id: int
    gift_amount: Decimal = Decimal("0")
    direction: str
    amount: Decimal
    balance_after: Decimal
    biz_type: str
    description: str
    payment_amount_cents: int | None = None
    created_at: str
