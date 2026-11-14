from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.restaurant import Restaurant
from app.models.store_request import StoreRequest
from app.models.user import User
from app.schemas.store_request import (
    StoreRequestCreate,
    StoreRequestOut,
    StoreRequestRespond,
)
from app.services.order_service import calculate_order_totals, get_setting_value
from app.services.push_service import (
    schedule_new_order,
    schedule_new_store_request,
    schedule_store_request_status,
)
from app.services.restaurant_access import MANAGE_ROLES, ORDER_ROLES, have_role

router = APIRouter()
store_router = APIRouter()


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Identificador inválido") from exc


def _out(request: StoreRequest, store: Restaurant | None = None, user: User | None = None) -> StoreRequestOut:
    data = StoreRequestOut.model_validate(request)
    if store:
        data.store_name = store.name
        data.store_logo_url = store.logo_url
    if user:
        data.customer_name = user.name
        data.customer_phone = user.phone
    return data


async def _load(db: AsyncSession, request_id: str):
    result = await db.execute(
        select(StoreRequest, Restaurant, User)
        .join(Restaurant, Restaurant.id == StoreRequest.store_id)
        .join(User, User.id == StoreRequest.user_id)
        .where(StoreRequest.id == _uuid(request_id))
    )
    return result.first()


async def _validate_payment_method(db: AsyncSession, method: str) -> None:
    if method == "mp":
        enabled = (await get_setting_value(db, "MP_ENABLED", "false")).lower() == "true"
        if not enabled:
            raise HTTPException(
                status_code=400,
                detail="Mercado Pago está deshabilitado. Elige efectivo o transferencia.",
            )
    elif method == "transfer":
        enabled = (await get_setting_value(db, "TRANSFER_ENABLED", "true")).lower() == "true"
        if not enabled:
            raise HTTPException(
                status_code=400,
                detail="La transferencia está deshabilitada. Elige efectivo.",
            )
    elif method != "cash":
        raise HTTPException(status_code=400, detail="Método de pago no válido")


@store_router.post(
    "/{store_id}/requests",
    response_model=StoreRequestOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_store_request(
    store_id: str,
    body: StoreRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    store = await db.get(Restaurant, _uuid(store_id))
    if not store or store.status != "active":
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    if not store.accepts_custom_requests:
        raise HTTPException(status_code=409, detail="Esta tienda no acepta solicitudes por ahora")
    today = datetime.now(timezone.utc).date()
    if not store.affiliation_expires_at or store.affiliation_expires_at < today:
        raise HTTPException(status_code=409, detail="La tienda no está disponible")

    await _validate_payment_method(db, body.payment_method)

    request = StoreRequest(
        store_id=store.id,
        user_id=current_user.id,
        description=body.description.strip(),
        quantity=body.quantity,
        reference_photo_url=(body.reference_photo_url or "").strip() or None,
        budget=body.budget,
        status="pending",
        delivery_address=body.delivery_address.strip(),
        delivery_location=f"SRID=4326;POINT({body.delivery_location.lng} {body.delivery_location.lat})",
        payment_method=body.payment_method,
        notes=(body.notes or "").strip() or None,
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)
    schedule_new_store_request(str(request.id))
    return _out(request, store, current_user)


@router.get("/my", response_model=list[StoreRequestOut])
async def list_my_store_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(StoreRequest, Restaurant)
        .join(Restaurant, Restaurant.id == StoreRequest.store_id)
        .where(StoreRequest.user_id == current_user.id)
        .order_by(StoreRequest.created_at.desc())
    )
    return [_out(request, store, current_user) for request, store in result.all()]


@router.get("/{request_id}", response_model=StoreRequestOut)
async def get_store_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await _load(db, request_id)
    if not row:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    request, store, user = row
    if (
        request.user_id != current_user.id
        and not current_user.is_superuser
        and not await have_role(db, request.store_id, current_user, ORDER_ROLES)
    ):
        raise HTTPException(status_code=403, detail="No tienes acceso a esta solicitud")
    return _out(request, store, user)


@store_router.get("/{store_id}/requests", response_model=list[StoreRequestOut])
async def list_store_requests(
    store_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser and not await have_role(
        db, _uuid(store_id), current_user, ORDER_ROLES
    ):
        raise HTTPException(status_code=403, detail="No puedes ver estas solicitudes")
    result = await db.execute(
        select(StoreRequest, User)
        .join(User, User.id == StoreRequest.user_id)
        .where(StoreRequest.store_id == _uuid(store_id))
        .order_by(StoreRequest.created_at.desc())
    )
    store = await db.get(Restaurant, _uuid(store_id))
    return [_out(request, store, user) for request, user in result.all()]


@store_router.patch(
    "/{store_id}/requests/{request_id}/respond",
    response_model=StoreRequestOut,
)
async def respond_store_request(
    store_id: str,
    request_id: str,
    body: StoreRequestRespond,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superuser and not await have_role(
        db, _uuid(store_id), current_user, MANAGE_ROLES
    ):
        raise HTTPException(status_code=403, detail="No puedes responder esta solicitud")
    row = await _load(db, request_id)
    if not row or str(row[0].store_id) != str(_uuid(store_id)):
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    request, store, user = row
    if request.status != "pending":
        raise HTTPException(status_code=400, detail="La solicitud ya fue atendida")

    if body.status == "quoted":
        if body.quoted_price is None or body.quoted_price <= 0:
            raise HTTPException(status_code=400, detail="Escribe el precio del producto")
        request.status = "quoted"
        request.quoted_price = body.quoted_price
    else:
        request.status = "rejected"
    request.store_notes = (body.store_notes or "").strip() or None
    request.responded_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(request)
    schedule_store_request_status(str(request.id))
    return _out(request, store, user)


@router.post("/{request_id}/confirm", response_model=StoreRequestOut)
async def confirm_store_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await _load(db, request_id)
    if not row:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    request, store, user = row
    if request.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No puedes confirmar esta solicitud")
    if request.status != "quoted":
        raise HTTPException(status_code=400, detail="La tienda todavía no ha cotizado")
    if request.quoted_price is None or request.quoted_price <= 0:
        raise HTTPException(status_code=400, detail="La cotización no es válida")

    coords = await db.execute(
        text(
            "SELECT ST_Y(delivery_location::geometry) AS lat, "
            "ST_X(delivery_location::geometry) AS lng "
            "FROM store_requests WHERE id = :id"
        ),
        {"id": request.id},
    )
    location = coords.mappings().first()
    if not location or location["lat"] is None:
        raise HTTPException(status_code=400, detail="La dirección de entrega no es válida")

    fake_item = SimpleNamespace(quantity=request.quantity)
    items_data = [{"unit_price": Decimal(request.quoted_price), "item": fake_item}]
    (
        subtotal,
        delivery_fee,
        discount,
        total,
        _coupon,
        platform_commission,
        flat_usage_fee,
        delivery_earnings,
        distance_km,
    ) = await calculate_order_totals(
        db,
        store,
        items_data,
        delivery_lat=float(location["lat"]),
        delivery_lng=float(location["lng"]),
    )

    order = Order(
        user_id=current_user.id,
        restaurant_id=store.id,
        status="pending",
        delivery_mode=store.delivery_mode,
        fulfillment_type="delivery",
        restaurant_owes_platform=(
            max(platform_commission + flat_usage_fee, Decimal("0"))
            if request.payment_method == "cash" and store.delivery_mode == "own"
            else Decimal("0")
        ),
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        total=total,
        delivery_address=request.delivery_address,
        delivery_location=request.delivery_location,
        notes=request.notes,
        payment_method=request.payment_method,
        platform_commission=platform_commission,
        flat_usage_fee=flat_usage_fee,
        delivery_earnings=delivery_earnings,
        delivery_distance_km=distance_km,
        estimated_delivery_min=30,
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderItem(
            order_id=order.id,
            menu_item_id=None,
            name=request.description,
            quantity=request.quantity,
            unit_price=Decimal(request.quoted_price),
            subtotal=Decimal(request.quoted_price) * request.quantity,
        )
    )
    request.status = "converted"
    request.order_id = order.id
    request.confirmed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(request)
    await db.refresh(order)
    schedule_new_order(str(order.id))
    schedule_store_request_status(str(request.id))
    return _out(request, store, user)


@router.post("/{request_id}/cancel", response_model=StoreRequestOut)
async def cancel_store_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await _load(db, request_id)
    if not row:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    request, store, user = row
    if request.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No puedes cancelar esta solicitud")
    if request.status not in ("pending", "quoted"):
        raise HTTPException(status_code=400, detail="La solicitud ya no se puede cancelar")
    request.status = "cancelled"
    await db.commit()
    await db.refresh(request)
    schedule_store_request_status(str(request.id))
    return _out(request, store, user)
