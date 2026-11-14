from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.restaurants import router as restaurants_router
from app.api.v1.reservations import router as reservations_router, restaurant_router as restaurant_reservations_router
from app.api.v1.orders import router as orders_router
from app.api.v1.delivery import router as delivery_router
from app.api.v1.reviews import router as reviews_router
from app.api.v1.payments import router as payments_router
from app.api.v1.profile import router as profile_router
from app.api.v1.coupons import router as coupons_router
from app.api.v1.geocode import router as geocode_router
from app.api.v1.mandados import router as mandados_router
from app.api.v1.upload import router as upload_router
from app.api.v1.map import router as map_router
from app.api.v1.push import router as push_router
from app.api.v1.settings import router as settings_router
from app.api.v1.reports import router as reports_router
from app.api.v1.admin_payouts import router as admin_payouts_router
from app.api.v1.admin_dashboard import router as admin_dashboard_router
from app.api.v1.admin_audit import router as admin_audit_router
from app.api.v1.admin_restaurants import router as admin_restaurants_router
from app.api.v1.restaurant_registration import router as restaurant_registration_router
from app.api.v1.team import router as team_router
from app.api.v1.debug import router as debug_router

router = APIRouter(prefix="/api/v1")

router.include_router(auth_router, prefix="/auth", tags=["Autenticación"])
router.include_router(restaurants_router, prefix="/restaurants", tags=["Restaurantes"])
router.include_router(reservations_router, prefix="/reservations", tags=["Reservaciones"])
router.include_router(restaurant_reservations_router, prefix="/restaurants", tags=["Reservaciones"])
router.include_router(orders_router, prefix="/orders", tags=["Pedidos"])
router.include_router(delivery_router, prefix="/delivery", tags=["Repartidores"])
router.include_router(reviews_router, prefix="/reviews", tags=["Reseñas"])
router.include_router(payments_router, prefix="/payments", tags=["Pagos"])
router.include_router(profile_router, prefix="/profile", tags=["Perfil"])
router.include_router(coupons_router, prefix="/coupons", tags=["Cupones"])
router.include_router(geocode_router, prefix="/geocode", tags=["Geocodificación"])
router.include_router(mandados_router, prefix="/mandados", tags=["Mandados"])
router.include_router(upload_router, prefix="/upload", tags=["Cargas"])
router.include_router(map_router, prefix="/map", tags=["Mapa"])
router.include_router(push_router, prefix="/push", tags=["Notificaciones"])
router.include_router(settings_router, prefix="/settings", tags=["Configuración"])
router.include_router(reports_router, prefix="/reports", tags=["Reportes"])
router.include_router(admin_payouts_router, prefix="/admin", tags=["Administración"])
router.include_router(admin_dashboard_router, prefix="/admin", tags=["Administración"])
router.include_router(admin_audit_router, prefix="/admin", tags=["Administración"])
router.include_router(admin_restaurants_router, prefix="/admin", tags=["Administración"])
router.include_router(restaurant_registration_router, prefix="/restaurant-registration", tags=["Restaurantes"])
router.include_router(team_router, prefix="/restaurants/{restaurant_id}/team", tags=["Restaurantes"])
router.include_router(debug_router, prefix="/debug", tags=["Diagnóstico"])

