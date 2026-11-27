import json
import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import get_db
from app.models.restaurant import Restaurant
from app.services import email_verification_service, phone_verification_service, push_service
from app.services.order_service import get_setting_value
from app.services.schedule_service import restaurant_open_state

router = APIRouter(prefix="/web")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates" / "web"))

_APK_INFO_CACHE: dict[str, tuple[float, int, str]] = {}


def _apk_info(apk: Path) -> dict:
    """Tamaño y SHA-256 de la APK, calculados una sola vez por versión."""
    stat = apk.stat()
    key = str(apk)
    cached = _APK_INFO_CACHE.get(key)
    if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
        digest = cached[2]
    else:
        hasher = hashlib.sha256()
        with apk.open("rb") as handle:
            for chunk in iter(lambda: handle.read(2 * 1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        _APK_INFO_CACHE[key] = (stat.st_mtime, stat.st_size, digest)
    return {
        "available": True,
        "size_mb": round(stat.st_size / (1024 * 1024), 1),
        "sha256": digest,
    }


@router.get("")
async def web_index():
    return RedirectResponse(url="/web/restaurants")


@router.get("/inicio")
async def web_landing(request: Request, db: AsyncSession = Depends(get_db)):
    async def setting_float(key: str, default: str) -> float:
        raw = await get_setting_value(db, key, default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(default)

    raw_whatsapp = (await get_setting_value(db, "WHATSAPP_SUPPORT", "")).strip()
    whatsapp = "".join(ch for ch in raw_whatsapp if ch.isdigit())
    raw_fee = await get_setting_value(db, "AFFILIATION_ANNUAL_FEE", "500.0")
    try:
        affiliation_fee = float(raw_fee)
    except (TypeError, ValueError):
        affiliation_fee = 500.0
    delivery_base = await setting_float("DELIVERY_BASE_FEE", "25.0")
    plan_1 = await setting_float("AFFILIATION_PRICE_1", "60.0")
    plan_3 = await setting_float("AFFILIATION_PRICE_3", "160.0")
    plan_6 = await setting_float("AFFILIATION_PRICE_6", "290.0")
    free_radius = await setting_float("DELIVERY_FREE_RADIUS_KM", "6.0")
    extra_km = await setting_float("DELIVERY_EXTRA_FEE_PER_KM", "5.0")
    flat_fee = await setting_float("APP_FLAT_USAGE_FEE", "5.0")
    business_fee = await setting_float("APP_FIXED_RESTAURANT_FEE", "5.0")
    contact_email = (
        await get_setting_value(db, "CONTACT_EMAIL", "tupedidojr@gmail.com")
    ).strip()
    return templates.TemplateResponse(
        request,
        "landing.html",
        {
            "whatsapp": whatsapp,
            "affiliation_fee": affiliation_fee,
            "affiliation_daily": affiliation_fee / 365,
            "affiliation_plan_1": plan_1,
            "affiliation_plan_3": plan_3,
            "affiliation_plan_6": plan_6,
            "contact_email": contact_email,
            "delivery_base": delivery_base,
            "free_radius": free_radius,
            "extra_km": extra_km,
            "flat_fee": flat_fee,
            "business_fee": business_fee,
            "client_example_total": 200 + delivery_base + flat_fee,
        },
    )


@router.get("/login")
async def web_login(request: Request):
    return templates.TemplateResponse(request, "login.html")


@router.get("/verify-email")
async def web_verify_email(
    request: Request,
    token: str = "",
    db: AsyncSession = Depends(get_db),
):
    user = await email_verification_service.verify(db, token) if token else None
    return templates.TemplateResponse(
        request,
        "verify_email.html",
        {"ok": bool(user), "email": user.email if user else None},
        status_code=200 if user else 400,
    )


@router.get("/verify-phone")
async def web_verify_phone(
    request: Request,
    token: str = "",
    db: AsyncSession = Depends(get_db),
):
    user = await phone_verification_service.verify(db, token) if token else None
    return templates.TemplateResponse(
        request,
        "verify_phone.html",
        {"ok": bool(user), "phone": user.phone if user else None},
        status_code=200 if user else 400,
    )


@router.get("/unlock")
async def web_unlock(request: Request):
    return templates.TemplateResponse(request, "unlock.html")


@router.get("/register")
async def web_register(request: Request):
    return templates.TemplateResponse(request, "register.html")


@router.get("/register-restaurant")
async def web_register_restaurant(request: Request, db: AsyncSession = Depends(get_db)):
    raw_fee = await get_setting_value(db, "AFFILIATION_ANNUAL_FEE", "500.0")
    try:
        affiliation_fee = float(raw_fee)
    except (TypeError, ValueError):
        affiliation_fee = 500.0
    contact_email = (
        await get_setting_value(db, "CONTACT_EMAIL", "tupedidojr@gmail.com")
    ).strip()
    return templates.TemplateResponse(
        request,
        "register_restaurant.html",
        {
            "affiliation_fee": affiliation_fee,
            "affiliation_daily": affiliation_fee / 365,
            "contact_email": contact_email,
        },
    )


@router.get("/forgot-password")
async def web_forgot_password(request: Request):
    return templates.TemplateResponse(request, "forgot_password.html")


@router.get("/reset-password")
async def web_reset_password(request: Request):
    return templates.TemplateResponse(request, "reset_password.html")


@router.get("/restaurants")
async def web_restaurants(request: Request):
    return templates.TemplateResponse(request, "restaurants.html")


@router.get("/r/{slug}")
async def web_public_restaurant(
    request: Request,
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    return RedirectResponse(url=f"/r/{slug}")


@router.get("/restaurants/{restaurant_id}")
async def web_restaurant_detail(request: Request, restaurant_id: str):
    return templates.TemplateResponse(request, "restaurant_detail.html", {"restaurant_id": restaurant_id})


@router.get("/restaurants/{restaurant_id}/orders")
async def web_restaurant_orders(request: Request, restaurant_id: str):
    return templates.TemplateResponse(request, "restaurant_orders.html", {"restaurant_id": restaurant_id})


@router.get("/restaurants/{restaurant_id}/earnings")
async def web_restaurant_earnings(request: Request, restaurant_id: str):
    return templates.TemplateResponse(request, "restaurant_earnings.html", {"restaurant_id": restaurant_id})


@router.get("/restaurants/{restaurant_id}/team")
async def web_restaurant_team(request: Request, restaurant_id: str):
    return templates.TemplateResponse(request, "restaurant_team.html", {"restaurant_id": restaurant_id})


@router.get("/restaurants/{restaurant_id}/location")
async def web_restaurant_location(restaurant_id: str):
    return RedirectResponse(url=f"/web/restaurants/{restaurant_id}/profile")


@router.get("/restaurants/{restaurant_id}/profile")
async def web_restaurant_profile(request: Request, restaurant_id: str):
    return templates.TemplateResponse(request, "restaurant_profile.html", {"restaurant_id": restaurant_id})


@router.get("/restaurants/{restaurant_id}/coupons")
async def web_restaurant_coupons(request: Request, restaurant_id: str):
    return templates.TemplateResponse(request, "coupons_manage.html", {"restaurant_id": restaurant_id})


@router.get("/restaurants/{restaurant_id}/qr")
async def web_restaurant_qr(
    request: Request,
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = result.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    slug = restaurant.slug or str(restaurant.id)
    public_url = f"{settings.APP_URL.rstrip('/')}/r/{slug}"
    return templates.TemplateResponse(
        request,
        "restaurant_qr.html",
        {
            "restaurant": restaurant,
            "public_url": public_url,
        },
    )


@router.get("/restaurants/{restaurant_id}/reserve")
async def web_reserve_restaurant(request: Request, restaurant_id: str):
    return templates.TemplateResponse(request, "reserve.html", {"restaurant_id": restaurant_id})


@router.get("/restaurants/{restaurant_id}/reservations")
async def web_restaurant_reservations(request: Request, restaurant_id: str):
    return templates.TemplateResponse(
        request, "restaurant_reservations.html", {"restaurant_id": restaurant_id}
    )


@router.get("/restaurants/{restaurant_id}/agenda")
async def web_restaurant_agenda(request: Request, restaurant_id: str):
    return templates.TemplateResponse(request, "agenda_manage.html", {"restaurant_id": restaurant_id})


@router.get("/restaurants/{restaurant_id}/agenda/book")
async def web_restaurant_agenda_book(request: Request, restaurant_id: str):
    return templates.TemplateResponse(request, "agenda_book.html", {"restaurant_id": restaurant_id})


@router.get("/restaurants/{restaurant_id}/rentals")
async def web_restaurant_rentals(request: Request, restaurant_id: str):
    return templates.TemplateResponse(request, "rentals_manage.html", {"restaurant_id": restaurant_id})


@router.get("/restaurants/{restaurant_id}/rentals/book")
async def web_restaurant_rentals_book(request: Request, restaurant_id: str):
    return templates.TemplateResponse(request, "rental_book.html", {"restaurant_id": restaurant_id})


@router.get("/my-rentals")
async def web_my_rentals(request: Request):
    return templates.TemplateResponse(request, "my_rentals.html")


@router.get("/reservations")
async def web_my_reservations(request: Request):
    return templates.TemplateResponse(request, "reservations.html")


@router.get("/my-appointments")
async def web_my_appointments(request: Request):
    return templates.TemplateResponse(request, "my_appointments.html")


@router.get("/reservations/{reservation_id}")
async def web_reservation_detail(request: Request, reservation_id: str):
    return templates.TemplateResponse(
        request, "reservation_detail.html", {"reservation_id": reservation_id}
    )


@router.get("/store-requests")
async def web_store_requests(request: Request):
    return templates.TemplateResponse(request, "store_requests.html")


@router.get("/store-requests/{request_id}")
async def web_store_request_detail(request: Request, request_id: str):
    return templates.TemplateResponse(
        request, "store_request_detail.html", {"request_id": request_id}
    )


@router.get("/restaurants/{restaurant_id}/requests")
async def web_restaurant_requests(request: Request, restaurant_id: str):
    return templates.TemplateResponse(
        request, "restaurant_requests.html", {"restaurant_id": restaurant_id}
    )


@router.get("/restaurants/{restaurant_id}/shipments")
async def web_restaurant_shipments(request: Request, restaurant_id: str):
    return templates.TemplateResponse(
        request, "restaurant_shipments.html", {"restaurant_id": restaurant_id}
    )


@router.get("/shipments/{token}")
async def web_public_shipment(request: Request, token: str):
    return templates.TemplateResponse(
        request, "shipment_tracking.html", {"token": token}
    )


@router.get("/cart")
async def web_cart(request: Request):
    return templates.TemplateResponse(request, "cart.html")


@router.get("/orders")
async def web_orders(request: Request):
    return templates.TemplateResponse(request, "orders.html")


@router.get("/orders/{order_id}")
async def web_order_detail(request: Request, order_id: str):
    return templates.TemplateResponse(request, "order_detail.html", {"order_id": order_id})


@router.get("/balance")
async def web_balance(request: Request):
    return templates.TemplateResponse(request, "balance.html")


@router.get("/profile")
async def web_profile(request: Request):
    return templates.TemplateResponse(request, "profile.html")


@router.get("/delivery")
async def web_delivery(request: Request):
    return templates.TemplateResponse(request, "delivery.html")


@router.get("/geocode")
async def web_geocode(request: Request):
    return templates.TemplateResponse(request, "geocode.html")


@router.get("/mandados")
async def web_mandados(request: Request):
    return templates.TemplateResponse(request, "mandados.html")


@router.get("/mandados/new")
async def web_mandado_new(request: Request):
    return templates.TemplateResponse(request, "mandado_new.html")


@router.get("/mandados/list")
async def web_mandado_list(request: Request):
    return templates.TemplateResponse(request, "mandado_list.html")


@router.get("/mandados/{mandado_id}")
async def web_mandado_detail(request: Request, mandado_id: str):
    return templates.TemplateResponse(request, "mandado_detail.html", {"mandado_id": mandado_id})


@router.get("/recargas")
async def web_recharges(request: Request, db: AsyncSession = Depends(get_db)):
    enabled = (
        await get_setting_value(db, "RECHARGES_ENABLED", "false")
    ).strip().lower() == "true"
    return templates.TemplateResponse(
        request, "recargas.html", {"recharges_enabled": enabled}
    )


@router.get("/recargas/{recarga_id}/ticket")
async def web_recarga_ticket(request: Request, recarga_id: str):
    return templates.TemplateResponse(
        request, "recarga_ticket.html", {"recarga_id": recarga_id}
    )


@router.get("/app")
async def web_app_download(request: Request, db: AsyncSession = Depends(get_db)):
    public_url = (
        await get_setting_value(db, "APP_PUBLIC_URL", settings.APP_URL)
    ).rstrip("/")
    apk = Path(__file__).parent.parent.parent / "static" / "downloads" / "TuPedidoJR.apk"
    apk_info = (
        _apk_info(apk) if apk.is_file() else {"available": False, "size_mb": 0, "sha256": ""}
    )
    return templates.TemplateResponse(
        request, "app_download.html", {"public_url": public_url, "apk": apk_info}
    )


@router.get("/app/apk")
async def web_app_apk():
    apk = Path(__file__).parent.parent.parent / "static" / "downloads" / "TuPedidoJR.apk"
    if not apk.is_file():
        raise HTTPException(status_code=404, detail="La APK todavía no está disponible")
    version = int(apk.stat().st_mtime)
    return FileResponse(
        apk,
        media_type="application/vnd.android.package-archive",
        filename=f"TuPedidoJR-v{version}.apk",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.get("/admin/push")
async def web_admin_push(request: Request):
    return templates.TemplateResponse(request, "push_admin.html")


@router.get("/admin/settings")
async def web_admin_settings(request: Request):
    return templates.TemplateResponse(request, "settings_admin.html")


@router.get("/admin/reports")
async def web_admin_reports(request: Request):
    return templates.TemplateResponse(request, "reports_admin.html")


@router.get("/admin/payouts")
async def web_admin_payouts(request: Request):
    return templates.TemplateResponse(request, "payouts_admin.html")


@router.get("/admin/recargas")
async def web_admin_recargas(request: Request):
    return templates.TemplateResponse(request, "recargas_admin.html")


@router.get("/admin/receipts")
async def web_admin_receipts(request: Request):
    return templates.TemplateResponse(request, "receipts_admin.html")


@router.get("/admin/transfers")
async def web_admin_transfers(request: Request):
    return templates.TemplateResponse(request, "transfers_admin.html")


@router.get("/admin/agenda")
async def web_admin_agenda(request: Request):
    return templates.TemplateResponse(request, "agenda_admin.html")


@router.get("/admin/incidents")
async def web_admin_incidents(request: Request):
    return templates.TemplateResponse(request, "incidents_admin.html")


@router.get("/admin/dashboard")
async def web_admin_dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard_admin.html")


@router.get("/admin/audit")
async def web_admin_audit(request: Request):
    return templates.TemplateResponse(request, "audit_admin.html")


@router.get("/admin/security")
async def web_admin_security(request: Request):
    return templates.TemplateResponse(request, "security_admin.html")


@router.get("/admin/restaurants")
async def web_admin_restaurants(request: Request):
    return templates.TemplateResponse(request, "restaurant_registrations_admin.html")


@router.get("/admin/couriers")
async def web_admin_couriers(request: Request):
    return templates.TemplateResponse(request, "couriers_admin.html")


@router.get("/admin/couriers/list")
async def web_admin_couriers_list(request: Request):
    return templates.TemplateResponse(request, "couriers_list_admin.html")


@router.get("/admin/users")
async def web_admin_users(request: Request):
    return templates.TemplateResponse(request, "users_admin.html")


@router.get("/admin/online")
async def web_admin_online(request: Request):
    return templates.TemplateResponse(request, "online_admin.html")


@router.get("/manifest.json")
async def web_manifest():
    return JSONResponse({
        "name": "TuPedidoJR",
        "short_name": "TuPedidoJR",
        "description": "Pedidos y entregas a domicilio en tu ciudad.",
        "start_url": "/web/restaurants",
        "scope": "/web/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#f0f4ff",
        "theme_color": "#0d1b2a",
        "icons": [
            {"src": "/static/web/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/web/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    })


@router.get("/firebase-messaging-sw.js")
async def firebase_messaging_sw(db: AsyncSession = Depends(get_db)):
    config = await push_service.get_public_config(db)
    web_config = config.get("web_config")
    if config.get("enabled") and web_config:
        body = f"""
importScripts('https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.12.2/firebase-messaging-compat.js');
firebase.initializeApp({json.dumps(web_config)});
const messaging = firebase.messaging();
messaging.onBackgroundMessage((payload) => {{
  const n = payload.notification || {{}};
  self.registration.showNotification(n.title || 'TuPedidoJR', {{
    body: n.body || '',
    icon: '/static/logo_notification_circle.png',
    badge: '/static/logo_notification_circle.png',
    data: payload.data || {{}},
  }});
}});
self.addEventListener('notificationclick', (event) => {{
  event.notification.close();
  const data = event.notification.data || {{}};
  let target = '/web/orders';
  if (data.type === 'courier_sos') target = '/web/admin/security';
  else if (data.type === 'available_order' || data.type === 'assigned_order') target = '/web/delivery';
  else if (data.type === 'new_order') target = '/web/orders';
  else if (data.order_id) target = '/web/orders/' + data.order_id;
  else if (data.type === 'payout_request') target = '/web/admin/payouts';
  else if (data.type === 'affiliation' && data.restaurant_id) target = '/web/restaurants/' + data.restaurant_id + '/profile';
  else if (data.type === 'coupon' && data.url) target = data.url;
  event.waitUntil((async () => {{
    const all = await self.clients.matchAll({{ type: 'window', includeUncontrolled: true }});
    for (const client of all) {{
      if (client.url.includes(target)) {{ await client.focus(); return; }}
    }}
    await self.clients.openWindow(target);
  }})());
}});
"""
    else:
        body = "self.addEventListener('install', () => self.skipWaiting());\n"
    return Response(
        content=body,
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/web/",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )
