from datetime import date
from pathlib import Path
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.restaurant import Restaurant
from app.services.schedule_service import restaurant_open_state
from app.services.order_service import get_commission_rate, get_setting_value
from app.services.rounding import round_half_down

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates" / "web"))
templates.env.filters["round0"] = lambda value: int(round_half_down(value))


async def _manual_values(db: AsyncSession) -> dict:
    async def number(key: str, default: str) -> Decimal:
        raw = await get_setting_value(db, key, default)
        try:
            return Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal(default)

    commission = await number("APP_COMMISSION_PERCENTAGE", "15.0")
    business_fee = await number("APP_FIXED_RESTAURANT_FEE", "5.0")
    flat_fee = await number("APP_FLAT_USAGE_FEE", "5.0")
    delivery_base = await number("DELIVERY_BASE_FEE", "25.0")
    free_radius = await number("DELIVERY_FREE_RADIUS_KM", "6.0")
    extra_km = await number("DELIVERY_EXTRA_FEE_PER_KM", "5.0")
    shipment_fee = await number("SHIPMENT_PLATFORM_FEE", "10.0")
    shipment_cod_max = await number("SHIPMENT_COD_MAX", "1500.0")
    shipment_return_percent = await number("SHIPMENT_RETURN_PERCENT", "50")
    peak_enabled = (await get_setting_value(db, "PEAK_BONUS_ENABLED", "false")).lower() == "true"
    peak_amount = await number("PEAK_BONUS_AMOUNT", "5.0")
    example_base = Decimal("100.00")
    example_customer = (example_base * (Decimal("1") + commission / Decimal("100"))).quantize(Decimal("0.01"))
    return {
        "commission_rate": commission,
        "business_fee": business_fee,
        "flat_fee": flat_fee,
        "delivery_base": delivery_base,
        "free_radius": free_radius,
        "extra_km": extra_km,
        "shipment_fee": shipment_fee,
        "shipment_cod_max": shipment_cod_max,
        "shipment_return_percent": shipment_return_percent,
        "peak_enabled": peak_enabled,
        "peak_amount": peak_amount,
        "example_base": example_base,
        "example_customer": example_customer,
    }


@router.get("/manuales/{name}")
async def public_manual(
    request: Request,
    name: str,
    db: AsyncSession = Depends(get_db),
):
    mapping = {
        "restaurante": "manuals/manual_restaurante.html",
        "menu": "manuals/manual_menu.html",
        "pedidos": "manuals/manual_pedidos.html",
        "envios": "manuals/manual_envios.html",
    }
    template = mapping.get(name)
    values = await _manual_values(db)
    if not template:
        return templates.TemplateResponse(
            request, "manuals/manual_restaurante.html",
            {"page": "restaurante", **values}, status_code=404,
        )
    return templates.TemplateResponse(request, template, {"page": name, **values})


@router.get("/r/{slug}")
async def public_restaurant(
    request: Request,
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Restaurant)
        .where(
            Restaurant.slug == slug,
            Restaurant.public_page_enabled.is_(True),
            Restaurant.status == "active",
            Restaurant.affiliation_expires_at.is_not(None),
            Restaurant.affiliation_expires_at >= date.today(),
        )
        .options(selectinload(Restaurant.categories), selectinload(Restaurant.menu))
    )
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        return templates.TemplateResponse(
            request, "public_restaurant.html",
            {"restaurant": None}, status_code=404,
        )
    state = await restaurant_open_state(db, restaurant)
    restaurant.effective_commission_percentage = await get_commission_rate(db, restaurant)
    return templates.TemplateResponse(
        request,
        "public_restaurant.html",
        {"restaurant": restaurant, "open_state": state},
    )
