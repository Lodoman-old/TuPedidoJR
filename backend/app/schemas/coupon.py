from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class CouponCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=50)
    description: str | None = None
    discount_type: str = Field(..., pattern=r"^(percentage|fixed)$")
    discount_value: Decimal = Field(..., gt=0)
    min_order_amount: Decimal = Field(default=Decimal("0"), ge=0)
    max_discount: Decimal | None = None
    max_uses: int = Field(default=0, ge=0)
    is_active: bool = True
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    restaurant_id: str | None = None


class CouponUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=3, max_length=50)
    description: str | None = Field(default=None, max_length=255)
    discount_type: str | None = Field(default=None, pattern=r"^(percentage|fixed)$")
    discount_value: Decimal | None = Field(default=None, gt=0)
    min_order_amount: Decimal | None = Field(default=None, ge=0)
    max_discount: Decimal | None = None
    max_uses: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class CouponOut(BaseModel):
    id: UUID
    code: str
    description: str | None
    discount_type: str
    discount_value: Decimal
    min_order_amount: Decimal
    max_discount: Decimal | None
    max_uses: int
    current_uses: int
    is_active: bool
    valid_from: datetime | None
    valid_until: datetime | None
    restaurant_id: UUID | None

    class Config:
        from_attributes = True


class ValidateCouponRequest(BaseModel):
    code: str
    subtotal: Decimal = Field(..., ge=0)
    restaurant_id: str | None = None


class ValidateCouponResponse(BaseModel):
    valid: bool
    message: str = ""
    discount_amount: Decimal = Decimal("0.00")
    discount_type: str = ""
    discount_value: Decimal = Decimal("0.00")
    coupon_id: str | None = None


class ApplyCouponRequest(BaseModel):
    coupon_code: str
