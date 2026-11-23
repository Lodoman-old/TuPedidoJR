"""Checklist de activación para negocios recién aprobados."""
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_service import BusinessService
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.models.restaurant_schedule import RestaurantSchedule
from app.services.schedule_service import local_today


async def business_onboarding(db: AsyncSession, restaurant: Restaurant) -> dict:
    business_type = restaurant.business_type or "restaurant"
    is_rental = business_type == "rental"
    is_services = business_type in ("services", "other")
    base = f"/web/restaurants/{restaurant.id}"

    schedule_count = int(
        await db.scalar(
            select(func.count())
            .select_from(RestaurantSchedule)
            .where(RestaurantSchedule.restaurant_id == restaurant.id)
        )
        or 0
    )
    menu_count = int(
        await db.scalar(
            select(func.count())
            .select_from(MenuItem)
            .where(
                MenuItem.restaurant_id == restaurant.id,
                MenuItem.price > 0,
                MenuItem.is_available.is_(True),
            )
        )
        or 0
    )
    service_count = int(
        await db.scalar(
            select(func.count())
            .select_from(BusinessService)
            .where(
                BusinessService.restaurant_id == restaurant.id,
                BusinessService.is_rental.is_(False),
                BusinessService.is_active.is_(True),
                BusinessService.price > 0,
            )
        )
        or 0
    )
    rental_count = int(
        await db.scalar(
            select(func.count())
            .select_from(BusinessService)
            .where(
                BusinessService.restaurant_id == restaurant.id,
                BusinessService.is_rental.is_(True),
                BusinessService.is_active.is_(True),
                BusinessService.price > 0,
            )
        )
        or 0
    )

    profile_done = bool(
        (restaurant.name or "").strip()
        and (restaurant.description or "").strip()
        and (restaurant.phone or "").strip()
        and (restaurant.logo_url or "").strip()
    )
    schedule_done = is_rental or schedule_count > 0
    if is_rental:
        catalog_done = rental_count > 0
    elif is_services and not restaurant.catalog_enabled:
        catalog_done = service_count > 0
    elif is_services:
        catalog_done = (menu_count + service_count) > 0
    else:
        catalog_done = menu_count > 0
    if is_rental:
        delivery_done = bool(restaurant.appointments_enabled)
        delivery_label = "Activa la agenda de rentas"
        delivery_href = f"{base}/rentals"
    elif is_services:
        delivery_done = bool(restaurant.appointments_enabled or restaurant.pickup_enabled)
        delivery_label = "Activa tu agenda de citas"
        delivery_href = f"{base}/agenda"
    else:
        delivery_done = bool(restaurant.delivery_enabled or restaurant.pickup_enabled)
        delivery_label = "Define entrega o recoger en el negocio"
        delivery_href = f"{base}/profile"
    qr_done = bool(restaurant.slug and restaurant.public_page_enabled)

    items = [
        {
            "key": "profile",
            "label": "Completa tus datos y tu logo",
            "description": "Nombre, descripción, teléfono y logo.",
            "done": profile_done,
            "href": f"{base}/profile",
        },
    ]
    if not is_rental:
        items.append({
            "key": "schedule",
            "label": "Configura tu horario",
            "description": "Sin horario no apareces disponible para los clientes.",
            "done": schedule_done,
            "href": f"{base}/profile#horario",
        })
    items.append({
        "key": "catalog",
        "label": "Agrega tu menú o catálogo",
        "description": "Al menos un producto o servicio con precio.",
        "done": catalog_done,
        "href": f"{base}/rentals" if is_rental else (f"{base}/agenda" if is_services else base),
    })
    items.append({
        "key": "delivery",
        "label": delivery_label,
        "description": "Elige cómo van a comprar tus clientes.",
        "done": delivery_done,
        "href": delivery_href,
    })
    items.append({
        "key": "qr",
        "label": "Activa tu página y descarga tu QR",
        "description": "Tu página pública y el QR para compartir.",
        "done": qr_done,
        "href": f"{base}/qr",
    })

    total = len(items)
    completed = sum(1 for item in items if item["done"])
    percent = round((completed / total) * 100) if total else 0

    today: date = await local_today(db)
    affiliated = bool(
        restaurant.affiliation_expires_at
        and restaurant.affiliation_expires_at >= today
    )
    published = bool(
        restaurant.status == "active" and affiliated and restaurant.public_page_enabled
    )
    if restaurant.status == "pending":
        status_message = "Tu solicitud está en revisión por TuPedidoJR."
    elif restaurant.status == "rejected":
        status_message = "Tu solicitud fue rechazada. Revisa el motivo o contacta a soporte."
    elif not affiliated:
        status_message = (
            "Tu negocio está aprobado. Falta registrar el pago de afiliación "
            "para publicarlo."
        )
    elif not restaurant.public_page_enabled:
        status_message = "Activa tu página pública para que los clientes te encuentren."
    elif not restaurant.is_open:
        status_message = (
            "Tu negocio está publicado. Ábrelo cuando estés listo para recibir pedidos."
        )
    else:
        status_message = "Tu negocio está publicado y abierto."

    next_step = next((item for item in items if not item["done"]), None)
    return {
        "restaurant_id": str(restaurant.id),
        "business_type": business_type,
        "completed": completed,
        "total": total,
        "percent": percent,
        "items": items,
        "published": published,
        "affiliated": affiliated,
        "status": restaurant.status,
        "is_open": bool(restaurant.is_open),
        "status_message": status_message,
        "next_step": next_step,
    }
