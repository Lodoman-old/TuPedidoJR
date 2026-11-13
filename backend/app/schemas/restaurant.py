from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import GeoPoint


class MenuCategoryOut(BaseModel):
    id: UUID
    name: str
    sort_order: int

    class Config:
        from_attributes = True


class MenuItemOut(BaseModel):
    id: UUID
    category_id: UUID | None
    name: str
    description: str | None
    price: Decimal
    image_url: str | None
    is_available: bool
    preparation_time_min: int | None
    option_groups: list["MenuOptionGroupOut"] = []

    class Config:
        from_attributes = True


class MenuOptionOut(BaseModel):
    id: UUID
    name: str
    price_delta: Decimal
    is_available: bool
    sort_order: int

    class Config:
        from_attributes = True


class MenuOptionGroupOut(BaseModel):
    id: UUID
    name: str
    selection_type: str
    pricing_mode: str = "delta"
    is_required: bool
    min_selections: int
    max_selections: int
    sort_order: int
    options: list[MenuOptionOut] = []

    class Config:
        from_attributes = True


class MenuOptionIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    price_delta: Decimal = Field(default=Decimal("0"), ge=0)
    is_available: bool = True
    sort_order: int = 0


class MenuOptionGroupIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    selection_type: str = Field(default="single", pattern="^(single|multiple)$")
    pricing_mode: str = Field(default="delta", pattern="^(delta|max)$")
    is_required: bool = False
    min_selections: int = Field(default=0, ge=0, le=20)
    max_selections: int = Field(default=1, ge=1, le=20)
    sort_order: int = 0
    options: list[MenuOptionIn] = []


class MenuItemOptionsUpdate(BaseModel):
    groups: list[MenuOptionGroupIn] = []


class MenuItemCreate(BaseModel):
    category_id: str | None = None
    name: str = Field(..., min_length=1, max_length=150)
    description: str | None = None
    price: Decimal = Field(..., gt=0)
    image_url: str | None = None
    preparation_time_min: int | None = None


class MenuItemAvailabilityUpdate(BaseModel):
    is_available: bool


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class RestaurantOut(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    cuisine: str | None = None
    slug: str | None = None
    public_page_enabled: bool = True
    delivery_mode: str = "platform"
    pickup_enabled: bool = False
    effective_commission_percentage: Decimal = Decimal("0")
    affiliated: bool = False
    affiliation_expires_at: date | None = None
    affiliation_days_left: int | None = None
    status: str = "active"
    viewer_role: str | None = None
    address: str
    phone: str | None
    logo_url: str | None
    is_open: bool
    rating: Decimal
    delivery_radius_m: int
    delivery_fee: Decimal
    is_open_now: bool | None = None
    open_message: str | None = None
    today_hours: list[dict] = []
    categories: list[MenuCategoryOut] = []
    menu: list[MenuItemOut] = []

    class Config:
        from_attributes = True


class RestaurantListItem(BaseModel):
    id: UUID
    name: str
    description: str | None
    cuisine: str | None = None
    slug: str | None = None
    delivery_mode: str = "platform"
    pickup_enabled: bool = False
    logo_url: str | None
    is_open: bool
    rating: Decimal
    delivery_fee: Decimal
    distance_m: float | None = None
    is_open_now: bool | None = None
    open_message: str | None = None
    estimated_delivery_fee: Decimal | None = None

    class Config:
        from_attributes = True


class ScheduleEntry(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    open_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    close_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    is_closed: bool = False


class RestaurantScheduleUpdate(BaseModel):
    entries: list[ScheduleEntry] = []


class RestaurantOpenStatus(BaseModel):
    restaurant_id: UUID
    is_open_now: bool
    message: str
    today_hours: list[dict] = []
    has_schedule: bool = False
    next_open_at: str | None = None
    timezone: str = "America/Mexico_City"


class EarningsOrderItem(BaseModel):
    id: UUID
    placed_at: datetime
    subtotal: Decimal
    delivery_fee: Decimal
    total: Decimal
    platform_commission: Decimal
    flat_usage_fee: Decimal
    payment_method: str
    status: str
    delivery_mode: str = "platform"


class EarningsOut(BaseModel):
    total_orders: int
    total_subtotal: Decimal
    total_commission: Decimal
    total_flat_fees: Decimal
    total_delivery_fees: Decimal
    total_collected_cash: Decimal
    total_collected_transfer: Decimal
    net_earned: Decimal
    total_paid: Decimal
    total_pending_payouts: Decimal
    available_for_payout: Decimal
    pending_from_platform: Decimal
    due_to_platform: Decimal
    pending_confirmation: Decimal = Decimal("0")
    restaurant_debt: Decimal = Decimal("0")
    loyalty_credit: Decimal = Decimal("0")
    orders: list[EarningsOrderItem]


class RestaurantProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    cuisine: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    is_open: bool | None = None
    public_page_enabled: bool | None = None
    delivery_mode: str | None = Field(default=None, pattern="^(platform|own)$")
    pickup_enabled: bool | None = None


class RestaurantCommissionUpdate(BaseModel):
    commission_percentage: Decimal | None = Field(default=None, ge=0, le=100)
    payout_frequency_days: int | None = Field(default=None, ge=0, le=90)


class RestaurantRegistrationCreate(BaseModel):
    owner_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    password: str = Field(..., min_length=6, max_length=128)
    restaurant_name: str = Field(..., min_length=2, max_length=150)
    cuisine: str | None = Field(default=None, max_length=100)
    address: str = Field(..., min_length=5)
    lat: float
    lng: float


class RestaurantRegistrationOut(BaseModel):
    id: UUID
    name: str
    cuisine: str | None = None
    address: str
    phone: str | None = None
    status: str
    owner_name: str
    owner_email: str
    created_at: datetime
    rejection_reason: str | None = None

    class Config:
        from_attributes = True


class RestaurantApprovalRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class TeamMemberCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field(default="staff", pattern="^(manager|staff|cashier|kitchen)$")


class TeamMemberOut(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime


class TeamMemberUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(manager|staff|cashier|kitchen)$")
    is_active: bool | None = None


class RestaurantLocationUpdate(BaseModel):
    street: str | None = None
    colonia: str | None = None
    postal_code: str | None = None
    city: str = "Santa Cruz de Juventino Rosas"
    state: str = "Guanajuato"
    address: str | None = None
    lat: float | None = None
    lng: float | None = None


class RestaurantPayoutOut(BaseModel):
    id: UUID
    restaurant_id: UUID
    period_start: date
    period_end: date
    orders_count: int
    total_subtotal: Decimal
    total_commission: Decimal
    total_flat_fees: Decimal
    net_payout: Decimal
    status: str
    paid_at: datetime | None
    confirmed_at: datetime | None
    notes: str | None

    class Config:
        from_attributes = True


MenuItemOut.model_rebuild()

