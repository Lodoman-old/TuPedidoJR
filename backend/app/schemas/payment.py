from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class BankAccountOut(BaseModel):
    bank_name: str = ""
    bank_code: str = ""
    account_holder: str = ""
    clabe: str = ""
    card: str = ""


class BankDetailsOut(BaseModel):
    bank_name: str = ""
    account_holder: str = ""
    clabe: str = ""
    card: str = ""
    recipient: str = "TuPedidoJR"
    accounts: list[BankAccountOut] = []


class BalancePaymentOut(BaseModel):
    id: str
    amount: Decimal
    status: str
    reference: str
    transfer_tracking_key: str | None = None
    cep_status: str | None = None
    created_at: datetime | None = None
    paid_at: datetime | None = None


class BalanceSummaryOut(BaseModel):
    pending_balance: Decimal
    payment: BalancePaymentOut | None = None


class CreatePreferenceRequest(BaseModel):
    order_id: str


class CreatePreferenceResponse(BaseModel):
    preference_id: str
    checkout_url: str
    sandbox_init_point: str | None = None


class PaymentStatusOut(BaseModel):
    order_id: UUID
    payment_status: str
    payment_id: str | None


class WebhookNotification(BaseModel):
    action: str | None = None
    api_version: str | None = None
    data: dict | None = None
    date_created: str | None = None
    id: int | None = None
    live_mode: bool | None = None
    type: str | None = None
    user_id: str | None = None
