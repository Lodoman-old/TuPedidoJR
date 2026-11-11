import asyncio
import logging

from contextlib import asynccontextmanager

import os
from pathlib import Path

import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from sqladmin import Admin

from app.admin import AdminAuth, CashAdvanceAdmin, CouponAdmin, DeliveryLocationAdmin, DeliveryPayoutAdmin, DeliveryPersonAdmin, MandadoAdmin, MenuCategoryAdmin, MenuItemAdmin, OrderAdmin, OrderItemAdmin, RestaurantAdmin, RestaurantPayoutAdmin, ReviewAdmin, SavedAddressAdmin, SettingAdmin, UserAdmin
from app.api.v1.router import router as api_router
from app.routes.web import router as web_router
from app.routes.public import router as public_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import async_session, engine
from app.services.file_service import ensure_upload_dir
from app.services.push_service import bootstrap_push_settings
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
    task = asyncio.create_task(ws_manager.start_persist_background_task())
    yield
    task.cancel()
    await ws_manager.stop()
    logger.info("Servidor detenido")


app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan)


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
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    if settings.NOINDEX:
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    if request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    from fastapi.responses import PlainTextResponse

    if settings.NOINDEX:
        return PlainTextResponse("User-agent: *\nDisallow: /\n")
    return PlainTextResponse("User-agent: *\nAllow: /\n")


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
admin.add_view(CashAdvanceAdmin)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME}
