from datetime import date, datetime, timezone
from decimal import Decimal
import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_optional_user, require_superuser
from app.db.session import get_db
from app.models.menu_category import MenuCategory
from app.models.menu_item import MenuItem
from app.models.menu_option import MenuOption, MenuOptionGroup
from app.models.restaurant import Restaurant
from app.models.restaurant_payout import RestaurantPayout
from app.models.user import User
from app.models.order import Order
from app.schemas.common import GeoPoint, PaginationParams
from app.schemas.restaurant import (CategoryCreate, EarningsOrderItem, EarningsOut, MenuCategoryOut,
                                    MenuItemCreate, MenuItemOut, MenuItemAvailabilityUpdate,
                                    MenuItemOptionsUpdate, MenuOptionGroupOut,
                                    RestaurantListItem, RestaurantOut,
                                    RestaurantPayoutOut, RestaurantLocationUpdate,
                                    RestaurantOpenStatus, RestaurantProfileUpdate,
                                    RestaurantCommissionUpdate,
                                    RestaurantScheduleUpdate, ScheduleEntry)
from app.services.geocode_service import geocode_structured
from app.schemas.order import CancelOrderRequest, OrderOut, OrderStatusUpdate
from app.services.cancellation_service import apply_cancellation
from app.services.file_service import delete_upload, save_upload
from app.services.geo_service import get_nearby_restaurants
from app.services.loyalty_service import award_on_delivery
from app.services.push_service import schedule_order_status
from app.services.schedule_service import (
    get_schedules,
    get_timezone,
    open_state_map,
    restaurant_open_state,
)
from app.services.settlement_service import is_order_settleable
from app.services.order_service import get_commission_rate
from app.services.restaurant_access import (
    FINANCE_ROLES, MANAGE_ROLES, ORDER_ROLES, OWNER_ROLES,
    have_role, my_restaurants, restaurant_role,
)
from app.services.audit_service import log_action
from app.api.v1.orders import _get_ws_manager


router = APIRouter()


async def _set_effective_commission(db: AsyncSession, restaurant: Restaurant) -> Restaurant:
    restaurant.effective_commission_percentage = await get_commission_rate(db, restaurant)
    return restaurant


def _slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:120] or "restaurante"


async def _unique_slug(db: AsyncSession, base: str, restaurant_id=None) -> str:
    candidate = base
    counter = 2
    while True:
        stmt = select(Restaurant.id).where(Restaurant.slug == candidate)
        if restaurant_id:
            stmt = stmt.where(Restaurant.id != restaurant_id)
        exists = (await db.execute(stmt)).scalar_one_or_none()
        if not exists:
            return candidate
        candidate = f"{base[:110]}-{counter}"
        counter += 1


@router.get("", response_model=list[RestaurantListItem])
async def list_restaurants(
    lat: float | None = None,
    lng: float | None = None,
    q: str | None = None,
    open_now: bool | None = None,
    max_fee: float | None = None,
    min_rating: float | None = None,
    free_delivery: bool | None = None,
    sort: str | None = None,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    if lat is not None and lng is not None:
        items = await get_nearby_restaurants(db, lat=lat, lng=lng, q=q, skip=pagination.skip, limit=pagination.limit)
        states = await open_state_map(db, [item.id for item in items])
        for item in items:
            state = states.get(item.id)
            if state and state["has_schedule"] and item.is_open:
                item.is_open_now = state["is_open_now"]
                item.open_message = state["message"]
            else:
                item.is_open_now = item.is_open
                item.open_message = "Abierto" if item.is_open else "Cerrado"
        return _filter_restaurants(items, open_now, max_fee, min_rating, free_delivery, sort)

    stmt = select(Restaurant).where(Restaurant.status == "active")
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Restaurant.name.ilike(like),
                Restaurant.cuisine.ilike(like),
                Restaurant.description.ilike(like),
                Restaurant.id.in_(
                    select(MenuItem.restaurant_id).where(MenuItem.name.ilike(like))
                ),
                Restaurant.id.in_(
                    select(MenuCategory.restaurant_id).where(MenuCategory.name.ilike(like))
                ),
            )
        )
    stmt = stmt.offset(pagination.skip).limit(pagination.limit)
    result = await db.execute(stmt)
    restaurants = list(result.scalars().all())
    states = await open_state_map(db, [r.id for r in restaurants])
    for restaurant in restaurants:
        state = states.get(restaurant.id)
        if state and state["has_schedule"] and restaurant.is_open:
            restaurant.is_open_now = state["is_open_now"]
            restaurant.open_message = state["message"]
        else:
            restaurant.is_open_now = restaurant.is_open
            restaurant.open_message = "Abierto" if restaurant.is_open else "Cerrado"
    items = [RestaurantListItem.model_validate(r) for r in restaurants]
    return _filter_restaurants(items, open_now, max_fee, min_rating, free_delivery, sort)


def _filter_restaurants(
    items: list[RestaurantListItem],
    open_now: bool | None,
    max_fee: float | None,
    min_rating: float | None,
    free_delivery: bool | None,
    sort: str | None,
) -> list[RestaurantListItem]:
    result = list(items)
    if open_now is not None:
        result = [r for r in result if bool(r.is_open_now) == open_now]
    if max_fee is not None:
        result = [r for r in result if float(r.delivery_fee or 0) <= max_fee]
    if min_rating is not None:
        result = [r for r in result if float(r.rating or 0) >= min_rating]
    if free_delivery:
        result = [r for r in result if float(r.delivery_fee or 0) == 0]

    if sort == "rating":
        result.sort(key=lambda r: float(r.rating or 0), reverse=True)
    elif sort == "fee":
        result.sort(key=lambda r: float(r.delivery_fee or 0))
    elif sort == "distance":
        result.sort(key=lambda r: r.distance_m if r.distance_m is not None else 10**9)
    return result


@router.get("/my", response_model=list[RestaurantListItem])
async def list_my_restaurants(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(Restaurant)
        .where(Restaurant.owner_id == current_user.id)
        .offset(0).limit(100)
    )
    result = await db.execute(stmt)
    restaurants = list(result.scalars().all())
    if not restaurants:
        restaurants = await my_restaurants(db, current_user)
    states = await open_state_map(db, [r.id for r in restaurants])
    for restaurant in restaurants:
        state = states.get(restaurant.id)
        if state and state["has_schedule"] and restaurant.is_open:
            restaurant.is_open_now = state["is_open_now"]
            restaurant.open_message = state["message"]
        else:
            restaurant.is_open_now = restaurant.is_open
            restaurant.open_message = "Abierto" if restaurant.is_open else "Cerrado"
    return [RestaurantListItem.model_validate(r) for r in restaurants]


@router.get("/my-restaurant", response_model=RestaurantOut)
async def get_my_restaurant(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Restaurant).where(Restaurant.owner_id == current_user.id).limit(1)
    result = await db.execute(stmt)
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        owned = await my_restaurants(db, current_user)
        restaurant = owned[0] if owned else None
    if not restaurant:
        raise HTTPException(status_code=404, detail="No tienes un restaurante registrado")
    state = await restaurant_open_state(db, restaurant)
    restaurant.is_open_now = state["is_open_now"]
    restaurant.open_message = state["message"]
    restaurant.today_hours = state["today_hours"]
    restaurant.viewer_role = await restaurant_role(db, restaurant.id, current_user)
    return await _set_effective_commission(db, restaurant)


@router.get("/public/{slug}", response_model=RestaurantOut)
async def get_public_restaurant(slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Restaurant)
        .where(
            Restaurant.slug == slug,
            Restaurant.public_page_enabled.is_(True),
            Restaurant.status == "active",
        )
        .options(selectinload(Restaurant.categories), selectinload(Restaurant.menu))
    )
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    state = await restaurant_open_state(db, restaurant)
    restaurant.is_open_now = state["is_open_now"]
    restaurant.open_message = state["message"]
    restaurant.today_hours = state["today_hours"]
    return await _set_effective_commission(db, restaurant)


@router.get("/{restaurant_id}", response_model=RestaurantOut)
async def get_restaurant(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    stmt = (
        select(Restaurant)
        .where(Restaurant.id == restaurant_id)
        .options(selectinload(Restaurant.categories), selectinload(Restaurant.menu))
    )
    result = await db.execute(stmt)
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    role = await restaurant_role(db, restaurant.id, current_user) if current_user else None
    if restaurant.status != "active" and role is None:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    state = await restaurant_open_state(db, restaurant)
    restaurant.is_open_now = state["is_open_now"]
    restaurant.open_message = state["message"]
    restaurant.today_hours = state["today_hours"]
    restaurant.viewer_role = role
    return await _set_effective_commission(db, restaurant)


@router.get("/{restaurant_id}/open-status", response_model=RestaurantOpenStatus)
async def get_open_status(restaurant_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    state = await restaurant_open_state(db, restaurant)
    tz = await get_timezone(db)
    return RestaurantOpenStatus(
        restaurant_id=restaurant.id,
        is_open_now=state["is_open_now"],
        message=state["message"],
        today_hours=state["today_hours"],
        has_schedule=state["has_schedule"],
        next_open_at=state["next_open_at"],
        timezone=str(tz),
    )


@router.get("/{restaurant_id}/schedule", response_model=list[ScheduleEntry])
async def get_restaurant_schedule(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")

    schedules = await get_schedules(db, restaurant_id)
    return [
        ScheduleEntry(
            day_of_week=row.day_of_week,
            open_time=row.open_time.strftime("%H:%M"),
            close_time=row.close_time.strftime("%H:%M"),
            is_closed=row.is_closed,
        )
        for row in schedules
    ]


@router.put("/{restaurant_id}/schedule", response_model=list[ScheduleEntry])
async def update_restaurant_schedule(
    restaurant_id: str,
    body: RestaurantScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")

    from app.models.restaurant_schedule import RestaurantSchedule

    existing = await db.execute(
        select(RestaurantSchedule).where(RestaurantSchedule.restaurant_id == restaurant_id)
    )
    for row in existing.scalars().all():
        await db.delete(row)

    created = []
    for entry in body.entries:
        try:
            open_time = datetime.strptime(entry.open_time, "%H:%M").time()
            close_time = datetime.strptime(entry.close_time, "%H:%M").time()
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Formato de hora inválido. Usa HH:MM",
            ) from exc
        row = RestaurantSchedule(
            restaurant_id=restaurant.id,
            day_of_week=entry.day_of_week,
            open_time=open_time,
            close_time=close_time,
            is_closed=entry.is_closed,
        )
        db.add(row)
        created.append(entry)

    await db.commit()
    await db.refresh(restaurant)
    return created


@router.post("/{restaurant_id}/menu", response_model=MenuItemOut, status_code=201)
async def create_menu_item(
    restaurant_id: str,
    body: MenuItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")

    item = MenuItem(restaurant_id=restaurant.id, **body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/{restaurant_id}/categories", response_model=MenuCategoryOut, status_code=201)
async def create_menu_category(
    restaurant_id: str,
    body: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")

    cat = MenuCategory(restaurant_id=restaurant.id, name=body.name)
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat


@router.post("/{restaurant_id}/logo")
async def upload_restaurant_logo(
    restaurant_id: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")

    try:
        url = await save_upload(file, size=800)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    delete_upload(restaurant.logo_url)
    restaurant.logo_url = url
    await db.commit()
    return {"logo_url": url}


@router.post("/{restaurant_id}/menu/{item_id}/image")
async def upload_menu_item_image(
    restaurant_id: str,
    item_id: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")

    item_result = await db.execute(
        select(MenuItem).where(MenuItem.id == item_id, MenuItem.restaurant_id == restaurant_id)
    )
    item = item_result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Platillo no encontrado")

    try:
        url = await save_upload(file, size=800)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    delete_upload(item.image_url)
    item.image_url = url
    await db.commit()
    return {"image_url": url}


@router.patch("/{restaurant_id}/menu/{item_id}/availability", response_model=MenuItemOut)
async def update_menu_item_availability(
    restaurant_id: str,
    item_id: str,
    body: MenuItemAvailabilityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")

    item_result = await db.execute(
        select(MenuItem).where(MenuItem.id == item_id, MenuItem.restaurant_id == restaurant_id)
    )
    item = item_result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Platillo no encontrado")
    item.is_available = body.is_available
    await db.commit()
    await db.refresh(item)
    return item


@router.get("/{restaurant_id}/menu/{item_id}/options", response_model=list[MenuOptionGroupOut])
async def get_menu_item_options(
    restaurant_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")

    result = await db.execute(
        select(MenuOptionGroup)
        .where(MenuOptionGroup.menu_item_id == item_id)
        .order_by(MenuOptionGroup.sort_order)
    )
    return result.scalars().all()


@router.put("/{restaurant_id}/menu/{item_id}/options", response_model=list[MenuOptionGroupOut])
async def update_menu_item_options(
    restaurant_id: str,
    item_id: str,
    body: MenuItemOptionsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")

    item_result = await db.execute(
        select(MenuItem).where(MenuItem.id == item_id, MenuItem.restaurant_id == restaurant_id)
    )
    item = item_result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Platillo no encontrado")

    existing_result = await db.execute(
        select(MenuOptionGroup).where(MenuOptionGroup.menu_item_id == item.id)
    )
    for group in existing_result.scalars().all():
        await db.delete(group)

    for group_data in body.groups:
        selection_type = group_data.selection_type
        max_selections = 1 if selection_type == "single" else group_data.max_selections
        min_selections = max(group_data.min_selections, 1 if group_data.is_required else 0)
        if min_selections > max_selections:
            raise HTTPException(
                status_code=400,
                detail=f"'{group_data.name}': el mínimo no puede ser mayor al máximo",
            )
        group = MenuOptionGroup(
            menu_item_id=item.id,
            name=group_data.name,
            selection_type=selection_type,
            pricing_mode=group_data.pricing_mode,
            is_required=group_data.is_required,
            min_selections=min_selections,
            max_selections=max_selections,
            sort_order=group_data.sort_order,
        )
        db.add(group)
        await db.flush()
        for option_data in group_data.options:
            db.add(MenuOption(
                group_id=group.id,
                name=option_data.name,
                price_delta=option_data.price_delta,
                is_available=option_data.is_available,
                sort_order=option_data.sort_order,
            ))

    await db.commit()
    result = await db.execute(
        select(MenuOptionGroup)
        .where(MenuOptionGroup.menu_item_id == item.id)
        .order_by(MenuOptionGroup.sort_order)
    )
    return result.scalars().all()


@router.get("/{restaurant_id}/orders", response_model=list[OrderOut])
async def list_restaurant_orders(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, ORDER_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")
    stmt = (
        select(Order)
        .where(Order.restaurant_id == restaurant_id)
        .options(selectinload(Order.items))
        .order_by(Order.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.patch("/{restaurant_id}/orders/{order_id}/status", response_model=OrderOut)
async def update_restaurant_order_status(
    restaurant_id: str,
    order_id: str,
    body: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, ORDER_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")
    stmt = (
        select(Order)
        .where(Order.id == order_id, Order.restaurant_id == restaurant_id)
        .options(selectinload(Order.items))
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    order.status = body.status
    now = datetime.now(timezone.utc)
    if body.status == "confirmed" and order.confirmed_at is None:
        order.confirmed_at = now
    elif body.status == "picked_up" and order.picked_up_at is None:
        order.picked_up_at = now
    elif body.status == "delivered" and order.delivered_at is None:
        order.delivered_at = now
    if body.status == "delivered":
        await award_on_delivery(db, order)
    await db.commit()
    await db.refresh(order)
    ws = _get_ws_manager()
    await ws.notify_order_status(str(order.id), body.status)
    schedule_order_status(str(order.id), body.status)
    return order


@router.post("/{restaurant_id}/orders/{order_id}/cancel", response_model=OrderOut)
async def cancel_restaurant_order(
    restaurant_id: str,
    order_id: str,
    body: CancelOrderRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, ORDER_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")

    result = await db.execute(
        select(Order)
        .where(Order.id == order_id, Order.restaurant_id == restaurant_id)
        .options(selectinload(Order.items))
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    role = "admin" if current_user.is_superuser else "restaurant"
    try:
        await apply_cancellation(
            db,
            order,
            actor_id=current_user.id,
            role=role,
            reason=body.reason if body else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    result = await db.execute(
        select(Order).where(Order.id == order.id).options(selectinload(Order.items))
    )
    order = result.scalar_one()
    ws = _get_ws_manager()
    await ws.notify_order_status(str(order.id), "cancelled")
    schedule_order_status(str(order.id), "cancelled")
    return order


@router.patch("/{restaurant_id}/profile", response_model=RestaurantOut)
async def update_restaurant_profile(
    restaurant_id: str,
    body: RestaurantProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Restaurant)
        .where(Restaurant.id == restaurant_id)
        .options(selectinload(Restaurant.categories), selectinload(Restaurant.menu))
    )
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")

    data = body.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(restaurant, field, value)
    if not restaurant.slug:
        restaurant.slug = await _unique_slug(db, _slugify(restaurant.name), restaurant.id)

    await db.commit()
    await db.refresh(restaurant)
    state = await restaurant_open_state(db, restaurant)
    restaurant.is_open_now = state["is_open_now"]
    restaurant.open_message = state["message"]
    restaurant.today_hours = state["today_hours"]
    return await _set_effective_commission(db, restaurant)


@router.patch("/{restaurant_id}/commission", response_model=RestaurantOut)
async def update_restaurant_commission(
    restaurant_id: str,
    body: RestaurantCommissionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    result = await db.execute(
        select(Restaurant)
        .where(Restaurant.id == restaurant_id)
        .options(selectinload(Restaurant.categories), selectinload(Restaurant.menu))
    )
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")

    data = body.model_dump(exclude_unset=True)
    if "commission_percentage" in data:
        restaurant.commission_percentage = data["commission_percentage"]
    if "payout_frequency_days" in data:
        restaurant.payout_frequency_days = data["payout_frequency_days"]
    await log_action(
        db, current_user.id, "restaurant.commission", "restaurant", restaurant.id,
        {
            "commission_percentage": str(restaurant.commission_percentage),
            "payout_frequency_days": restaurant.payout_frequency_days,
        },
    )
    await db.commit()
    await db.refresh(restaurant)
    state = await restaurant_open_state(db, restaurant)
    restaurant.is_open_now = state["is_open_now"]
    restaurant.open_message = state["message"]
    restaurant.today_hours = state["today_hours"]
    return await _set_effective_commission(db, restaurant)


@router.get("/{restaurant_id}/location")
async def get_restaurant_location(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")
    point = await db.execute(
        text("""
            SELECT ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng
            FROM restaurants WHERE id = :rid
        """),
        {"rid": restaurant_id},
    )
    row = point.mappings().first()
    return {
        "id": str(restaurant.id),
        "address": restaurant.address,
        "lat": float(row["lat"]) if row and row["lat"] is not None else None,
        "lng": float(row["lng"]) if row and row["lng"] is not None else None,
    }


@router.patch("/{restaurant_id}/location")
async def update_restaurant_location(
    restaurant_id: str,
    body: RestaurantLocationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")

    lat, lng = body.lat, body.lng
    if lat is None or lng is None:
        if not body.street or not body.colonia or not body.postal_code:
            raise HTTPException(
                status_code=400,
                detail="Indica calle, colonia y código postal para ubicar el restaurante",
            )
        results = await geocode_structured(
            street=body.street,
            colonia=body.colonia,
            postalcode=body.postal_code,
            city=body.city,
            state=body.state,
        )
        if not results:
            raise HTTPException(
                status_code=400,
                detail="No se encontró la dirección. Revisa calle, colonia y C.P.",
            )
        lat, lng = results[0]["lat"], results[0]["lng"]

    restaurant.location = f"SRID=4326;POINT({lng} {lat})"
    if body.address:
        restaurant.address = body.address
    elif body.street and body.colonia and body.postal_code:
        restaurant.address = (
            f"{body.street}, {body.colonia}, {body.city}, {body.state}, "
            f"C.P. {body.postal_code}"
        )
    await db.commit()
    await db.refresh(restaurant)
    return {
        "id": str(restaurant.id),
        "address": restaurant.address,
        "lat": float(lat),
        "lng": float(lng),
    }


@router.get("/{restaurant_id}/earnings", response_model=EarningsOut)
async def restaurant_earnings(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, FINANCE_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")
    stmt = (
        select(Order)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.status.in_(["delivered", "in_delivery", "picked_up"]),
        )
        .order_by(Order.placed_at.desc())
    )
    result = await db.execute(stmt)
    orders = result.scalars().all()

    total_orders = len(orders)
    total_subtotal = Decimal("0")
    total_commission = Decimal("0")
    total_flat_fees = Decimal("0")
    total_delivery_fees = Decimal("0")
    total_collected_cash = Decimal("0")
    total_collected_transfer = Decimal("0")
    for o in orders:
        total_subtotal += o.subtotal
        total_commission += o.platform_commission
        total_flat_fees += o.flat_usage_fee
        total_delivery_fees += o.delivery_fee
        if o.payment_method == "cash" and o.status == "delivered":
            total_collected_cash += o.total
        elif o.payment_method in ("transfer", "mp") and o.status == "delivered" and is_order_settleable(o):
            total_collected_transfer += o.total

    # Agreed financial model: the restaurant only absorbs the platform commission.
    # The flat usage fee is charged to the customer and belongs to the platform.
    own_extra = sum(
        ((o.delivery_fee or Decimal("0")) + (o.tip_amount or Decimal("0")))
        for o in orders
        if o.status != "cancelled" and o.delivery_mode == "own"
    )
    net_earned = total_subtotal - total_commission + own_extra

    def _net(order: Order) -> Decimal:
        base = (order.subtotal or Decimal("0")) - (order.platform_commission or Decimal("0"))
        if order.delivery_mode == "own":
            base += (order.delivery_fee or Decimal("0")) + (order.tip_amount or Decimal("0"))
        return base

    # Payouts can only be requested for orders that have actually been delivered
    # and whose money is already held by the platform (cash delivered or
    # transfer confirmed).
    delivered_orders = [
        o for o in orders
        if o.status == "delivered" and not o.restaurant_paid_with_advance
    ]
    settleable_orders = [o for o in delivered_orders if is_order_settleable(o)]
    payable_orders = [
        o for o in settleable_orders
        if not (o.delivery_mode in ("own", "pickup") and o.payment_method == "cash")
    ]
    pending_confirmation = sum(
        (_net(o) for o in delivered_orders if not is_order_settleable(o)),
        Decimal("0"),
    )
    payable_net = sum((_net(o) for o in payable_orders), Decimal("0"))
    restaurant_debt = sum(
        (o.restaurant_owes_platform or Decimal("0"))
        for o in settleable_orders
        if o.delivery_mode in ("own", "pickup")
        and o.payment_method == "cash"
        and not o.restaurant_charge_settled
    )
    loyalty_credit = sum(
        (
            max(
                (o.loyalty_discount or Decimal("0"))
                - (o.platform_commission or Decimal("0"))
                - (o.flat_usage_fee or Decimal("0")),
                Decimal("0"),
            )
            for o in settleable_orders
            if o.delivery_mode in ("own", "pickup")
            and o.payment_method == "cash"
            and not o.restaurant_charge_settled
        ),
        Decimal("0"),
    )

    payouts_result = await db.execute(
        select(RestaurantPayout).where(RestaurantPayout.restaurant_id == restaurant_id)
    )
    restaurant_payouts = payouts_result.scalars().all()
    total_paid = sum(
        (p.net_payout or Decimal("0"))
        for p in restaurant_payouts
        if p.status in ("paid", "confirmed")
    )
    total_pending_payouts = sum(
        (p.net_payout or Decimal("0"))
        for p in restaurant_payouts
        if p.status == "pending"
    )
    already_requested = sum(
        (p.net_payout or Decimal("0"))
        for p in restaurant_payouts
        if p.status != "cancelled"
    )
    available_for_payout = payable_net + loyalty_credit - already_requested - restaurant_debt
    if available_for_payout < Decimal("0"):
        available_for_payout = Decimal("0")

    pending_from_platform = payable_net + loyalty_credit - total_paid
    if pending_from_platform < Decimal("0"):
        pending_from_platform = Decimal("0")
    due_to_platform = Decimal("0")

    items = [
        EarningsOrderItem(
            id=o.id,
            placed_at=o.placed_at,
            subtotal=o.subtotal,
            delivery_fee=o.delivery_fee,
            total=o.total,
            platform_commission=o.platform_commission,
            flat_usage_fee=o.flat_usage_fee,
            payment_method=o.payment_method,
            status=o.status,
        )
        for o in orders
    ]

    return EarningsOut(
        total_orders=total_orders,
        total_subtotal=total_subtotal,
        total_commission=total_commission,
        total_flat_fees=total_flat_fees,
        total_delivery_fees=total_delivery_fees,
        total_collected_cash=total_collected_cash,
        total_collected_transfer=total_collected_transfer,
        net_earned=net_earned,
        total_paid=total_paid,
        total_pending_payouts=total_pending_payouts,
        available_for_payout=available_for_payout,
        pending_from_platform=pending_from_platform,
        due_to_platform=due_to_platform,
        pending_confirmation=pending_confirmation,
        restaurant_debt=restaurant_debt,
        loyalty_credit=loyalty_credit,
        orders=items,
    )


@router.get("/{restaurant_id}/payouts", response_model=list[RestaurantPayoutOut])
async def restaurant_payouts(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, FINANCE_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")

    result = await db.execute(
        select(RestaurantPayout)
        .where(RestaurantPayout.restaurant_id == restaurant_id)
        .order_by(RestaurantPayout.created_at.desc())
    )
    return result.scalars().all()


@router.post("/{restaurant_id}/request-payout", response_model=RestaurantPayoutOut)
async def request_restaurant_payout(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante no encontrado")
    if not await have_role(db, restaurant.id, current_user, OWNER_ROLES):
        raise HTTPException(status_code=403, detail="No eres dueño de este restaurante")

    from app.services.payout_service import create_restaurant_payout

    try:
        payout = await create_restaurant_payout(db, restaurant.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return payout
