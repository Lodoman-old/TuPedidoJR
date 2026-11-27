import asyncio
import logging
import mimetypes

from contextlib import asynccontextmanager

import os
from pathlib import Path

import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from sqladmin import Admin

from app.admin import AdminAuth, BalancePaymentAdmin, CashAdvanceAdmin, CouponAdmin, DeliveryLocationAdmin, DeliveryPayoutAdmin, DeliveryPersonAdmin, MandadoAdmin, MenuCategoryAdmin, MenuItemAdmin, OrderAdmin, OrderItemAdmin, ReceiptValidationAdmin, RestaurantAdmin, RestaurantPayoutAdmin, ReviewAdmin, SavedAddressAdmin, SettingAdmin, ShipmentAdmin, UserAdmin
from app.api.v1.router import router as api_router
from app.routes.web import router as web_router
from app.routes.public import router as public_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import async_session, engine
from app.services.file_service import ensure_upload_dir
from app.services.affiliation_service import affiliation_reminder_loop
from app.services.appointment_reminder_service import appointment_reminder_loop
from app.services.security_summary_service import security_summary_loop
from app.services.reengagement_service import customer_winback_loop
from app.services.business_summary_service import business_summary_loop
from app.services.onboarding_reminder_service import onboarding_reminder_loop
from app.services.courier_timeout_service import courier_timeout_loop
from app.services.delivery_ops_service import delivery_ops_loop
from app.services.cep_retry_service import cep_retry_loop
from app.services.transfer_timeout_service import transfer_timeout_loop
from app.services.recarga_service import recarga_processing_loop
from app.services.push_service import bootstrap_push_settings
from app.services.security_service import security_guard
from app.ws.delivery_ws import router as delivery_ws_router
from app.ws.manager import ConnectionManager
from app.ws.tracking_ws import router as tracking_ws_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ws_manager = ConnectionManager(async_session)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Iniciando %s ...", settings.APP_NAME)
    ensure_upload_dir()
    await bootstrap_push_settings()
    security_guard.configure(async_session)
    await security_guard.load_blocks()
    await security_guard.cleanup()
    task = asyncio.create_task(ws_manager.start_persist_background_task())
    affiliation_task = asyncio.create_task(affiliation_reminder_loop())
    courier_timeout_task = asyncio.create_task(courier_timeout_loop())
    delivery_ops_task = asyncio.create_task(delivery_ops_loop())
    appointment_task = asyncio.create_task(appointment_reminder_loop())
    security_task = asyncio.create_task(security_summary_loop())
    winback_task = asyncio.create_task(customer_winback_loop())
    business_summary_task = asyncio.create_task(business_summary_loop())
    onboarding_task = asyncio.create_task(onboarding_reminder_loop())
    cep_retry_task = asyncio.create_task(cep_retry_loop())
    transfer_timeout_task = asyncio.create_task(transfer_timeout_loop())
    recarga_task = asyncio.create_task(recarga_processing_loop())
    yield
    task.cancel()
    affiliation_task.cancel()
    courier_timeout_task.cancel()
    delivery_ops_task.cancel()
    appointment_task.cancel()
    security_task.cancel()
    winback_task.cancel()
    business_summary_task.cancel()
    onboarding_task.cancel()
    cep_retry_task.cancel()
    transfer_timeout_task.cancel()
    recarga_task.cancel()
    await ws_manager.stop()
    logger.info("Servidor detenido")


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
    # La documentación automática revela todos los endpoints: solo en desarrollo.
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    if settings.DEBUG:
        detail = f"Internal Server Error: {type(exc).__name__}: {exc}"
    else:
        detail = "Error interno del servidor"
    return JSONResponse(status_code=500, content={"detail": detail})


_cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.ALLOWED_HOSTS and settings.ALLOWED_HOSTS.strip() != "*":
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            host.strip() for host in settings.ALLOWED_HOSTS.split(",") if host.strip()
        ],
    )


@app.middleware("http")
async def no_cache_pages(request: Request, call_next):
    response = await call_next(request)
    if request.method == "GET" and not request.url.path.startswith(("/static", "/tiles")):
        response.headers.setdefault("Cache-Control", "no-store, max-age=0")
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(self), camera=(), microphone=(), payment=()"
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com "
        "https://www.gstatic.com https://www.google.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com "
        "https://fonts.googleapis.com; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data: https://cdn.jsdelivr.net https://fonts.gstatic.com; "
        "connect-src 'self' https: wss:; "
        "worker-src 'self' blob:; "
        "frame-src 'self' https://www.google.com https://console.firebase.google.com; "
        "frame-ancestors 'self'; base-uri 'self'; form-action 'self'; object-src 'none'",
    )
    if settings.NOINDEX:
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    if request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.middleware("http")
async def security_guard_middleware(request: Request, call_next):
    decision = await security_guard.inspect(request)
    if decision.blocked:
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=403,
                content={"detail": "Acceso bloqueado temporalmente por seguridad."},
            )
        html = (
            "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>Acceso bloqueado | TuPedidoJR</title>"
            "<style>body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;"
            "background:#f6f8fb;color:#17212b;display:grid;place-items:center;min-height:100vh;padding:24px}"
            ".card{max-width:520px;background:#fff;border:1px solid #e3e9f0;border-radius:16px;"
            "padding:28px;box-shadow:0 18px 50px rgba(13,27,42,.12)}h1{font-size:22px;margin:0 0 10px}"
            "p{font-size:14px;color:#5d6b7a;line-height:1.6}a{color:#0d6efd}</style></head><body>"
            "<div class='card'><h1>Acceso bloqueado temporalmente</h1>"
            "<p>Detectamos actividad inusual desde tu conexión y la bloqueamos por seguridad. "
            "Si crees que es un error, escríbenos y lo revisamos.</p>"
            "<p>Correo: <a href='mailto:tupedidojr@gmail.com'>tupedidojr@gmail.com</a></p></div>"
            "</body></html>"
        )
        from fastapi.responses import HTMLResponse

        return HTMLResponse(html, status_code=403)
    response = await call_next(request)
    try:
        await security_guard.observe_response(request, response.status_code)
    except Exception:
        pass
    return response


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    from fastapi.responses import PlainTextResponse

    if settings.NOINDEX:
        return PlainTextResponse("User-agent: *\nDisallow: /\n")
    base = settings.APP_URL.rstrip("/")
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /web/admin/\n"
        "Disallow: /web/login\n"
        "Disallow: /web/register\n"
        "Disallow: /web/register-restaurant\n"
        "Disallow: /web/profile\n"
        "Disallow: /web/cart\n"
        "Disallow: /api/\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return PlainTextResponse(body)


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    from fastapi.responses import Response
    from sqlalchemy import text

    from app.db.session import async_session

    base = settings.APP_URL.rstrip("/")
    paths = ["/web/inicio", "/web/app", "/manuales"]
    try:
        async with async_session() as db:
            result = await db.execute(text(
                "SELECT slug FROM restaurants "
                "WHERE slug IS NOT NULL AND status = 'active' AND public_page_enabled = true "
                "ORDER BY name"
            ))
            paths += [f"/r/{slug}" for slug in result.scalars().all() if slug]
    except Exception:
        pass

    items = []
    for path in paths:
        priority = "1.0" if path == "/web/inicio" else "0.7"
        items.append(
            f"<url><loc>{base}{path}</loc>"
            "<changefreq>weekly</changefreq>"
            f"<priority>{priority}</priority></url>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(items)
        + "</urlset>"
    )
    return Response(content=xml, media_type="application/xml")


mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("application/pdf", ".pdf")

app.mount("/static", StaticFiles(directory=Path(__file__).parent.parent / "static"), name="static")
_tiles_dir = Path(os.getenv("TILES_DIR", str(Path(__file__).parent.parent / "static" / "tiles")))
_tiles_dir.mkdir(parents=True, exist_ok=True)
app.mount("/tiles", StaticFiles(directory=_tiles_dir), name="tiles")
app.include_router(api_router)
app.include_router(delivery_ws_router)
app.include_router(tracking_ws_router)
app.include_router(web_router)
app.include_router(public_router)

admin = Admin(
    app=app,
    engine=engine,
    session_maker=async_session,
    authentication_backend=AdminAuth(secret_key=settings.SECRET_KEY),
    title="TuPedidoJR",
    logo_url="/static/logo.png",
    logo_width=120,
    logo_height=60,
    templates_dir=str(Path(__file__).parent.parent / "templates"),
)
admin.add_view(UserAdmin)
admin.add_view(RestaurantAdmin)
admin.add_view(MenuCategoryAdmin)
admin.add_view(MenuItemAdmin)
admin.add_view(OrderAdmin)
admin.add_view(OrderItemAdmin)
admin.add_view(DeliveryPersonAdmin)
admin.add_view(DeliveryLocationAdmin)
admin.add_view(ReviewAdmin)
admin.add_view(CouponAdmin)
admin.add_view(SavedAddressAdmin)
admin.add_view(SettingAdmin)
admin.add_view(DeliveryPayoutAdmin)
admin.add_view(RestaurantPayoutAdmin)
admin.add_view(MandadoAdmin)
admin.add_view(ShipmentAdmin)
admin.add_view(ReceiptValidationAdmin)
admin.add_view(BalancePaymentAdmin)
admin.add_view(CashAdvanceAdmin)


@app.get("/", include_in_schema=False)
async def root_redirect():
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/web/inicio")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    from pathlib import Path

    from fastapi.responses import FileResponse

    return FileResponse(Path(__file__).parent.parent / "static" / "favicon.ico")


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME}
