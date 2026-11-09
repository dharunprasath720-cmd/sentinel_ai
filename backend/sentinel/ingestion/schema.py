from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Source = Literal["synthetic", "paysim", "paypal_sandbox"]
Status = Literal["completed", "failed", "pending"]


class TransactionIn(BaseModel):
    external_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    merchant_id: str | None = None
    device_id: str | None = None
    instrument_id: str | None = None
    amount: float = Field(gt=0, allow_inf_nan=False)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    ts: datetime
    type: str = Field(min_length=1)
    payment_method: str | None = None
    status: Status
    geo: str | None = None
    label: int | None = Field(default=None, ge=0, le=1)
    source: Source
    business_id: str = Field(min_length=1)

    @field_validator("ts")
    @classmethod
    def _require_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return v
