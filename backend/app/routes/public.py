from datetime import date
from pathlib import Path
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.core.security import decode_access_token
from app.models.restaurant import Restaurant
from app.models.business_service import BusinessService
from app.models.user import User
from app.services.schedule_service import local_today, restaurant_open_state
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
    affiliation_fee = await number("AFFILIATION_ANNUAL_FEE", "500.0")
    affiliation_daily = (affiliation_fee / Decimal("365")).quantize(Decimal("0.01"))
    plan_1 = await number("AFFILIATION_PRICE_1", "60.0")
    plan_3 = await number("AFFILIATION_PRICE_3", "160.0")
    plan_6 = await number("AFFILIATION_PRICE_6", "290.0")
    contact_email = (await get_setting_value(db, "CONTACT_EMAIL", "tupedidojr@gmail.com")).strip()
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
        "affiliation_fee": affiliation_fee,
        "affiliation_daily": affiliation_daily,
        "affiliation_plan_1": plan_1,
        "affiliation_plan_3": plan_3,
        "affiliation_plan_6": plan_6,
        "contact_email": contact_email,
        "peak_enabled": peak_enabled,
        "peak_amount": peak_amount,
        "example_base": example_base,
        "example_customer": example_customer,
    }


@router.get("/politica-no-entrega")
async def public_no_delivery_policy(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    raw = (await get_setting_value(db, "WHATSAPP_SUPPORT", "")).strip()
    whatsapp = "".join(ch for ch in raw if ch.isdigit())
    return templates.TemplateResponse(
        request, "policy_no_delivery.html", {"whatsapp": whatsapp}
    )


@router.get("/manuales")
async def public_manuals_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    values = await _manual_values(db)
    return templates.TemplateResponse(
        request, "manuals/manual_index.html", {"page": "index", **values}
    )


@router.get("/manuales/{name}")
async def public_manual(
    request: Request,
    name: str,
    db: AsyncSession = Depends(get_db),
):
    mapping = {
        "restaurante": "manuals/manual_restaurante.html",
        "negocio": "manuals/manual_restaurante.html",
        "menu": "manuals/manual_menu.html",
        "pedidos": "manuals/manual_pedidos.html",
        "envios": "manuals/manual_envios.html",
        "cliente": "manuals/manual_cliente.html",
        "repartidor": "manuals/manual_repartidor.html",
        "admin": "manuals/manual_admin.html",
    }
    template = mapping.get(name)
    values = await _manual_values(db)
    if not template:
        return templates.TemplateResponse(
            request, "manuals/manual_index.html",
            {"page": "index", **values}, status_code=404,
        )
    if name == "admin" and not await _is_superuser_token(
        db, request.query_params.get("token")
    ):
        # El manual del administrador no queda abierto al público: solo se
        # sirve con el token de un superusuario.
        return templates.TemplateResponse(
            request, "manuals/manual_denied.html",
            {"page": "admin", **values}, status_code=403,
        )
    return templates.TemplateResponse(request, template, {"page": name, **values})


async def _is_superuser_token(db: AsyncSession, token: str | None) -> bool:
    if not token:
        return False
    payload = decode_access_token(token)
    if not payload:
        return False
    user_id = payload.get("sub")
    if not user_id:
        return False
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    return bool(user and user.is_active and user.is_superuser)


@router.get("/r/{slug}")
async def public_restaurant(
    request: Request,
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    today_local = await local_today(db)
    result = await db.execute(
        select(Restaurant)
        .where(
            Restaurant.slug == slug,
            Restaurant.public_page_enabled.is_(True),
            Restaurant.status == "active",
            Restaurant.affiliation_expires_at.is_not(None),
            Restaurant.affiliation_expires_at >= today_local,
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
    services = []
    if restaurant.appointments_enabled:
        result = await db.execute(
            select(BusinessService)
            .where(
                BusinessService.restaurant_id == restaurant.id,
                BusinessService.is_active.is_(True),
            )
            .order_by(BusinessService.sort_order, BusinessService.name)
        )
        services = list(result.scalars().all())
    return templates.TemplateResponse(
        request,
        "public_restaurant.html",
        {"restaurant": restaurant, "open_state": state, "services": services},
    )
