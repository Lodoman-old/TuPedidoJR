from datetime import datetime, timezone

from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.core.security import hash_password, verify_password, decode_access_token, create_access_token
from app.db.session import async_session
from app.models.cash_advance import CashAdvance
from app.models.delivery_location import DeliveryLocation
from app.models.delivery_payout import DeliveryPayout
from app.models.delivery_person import DeliveryPerson
from app.models.mandado import Mandado
from app.models.menu_category import MenuCategory
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.restaurant import Restaurant
from app.models.restaurant_payout import RestaurantPayout
from app.models.review import Review
from app.models.saved_address import SavedAddress
from app.models.setting import Setting
from app.models.coupon import Coupon
from app.models.user import User
from app.schemas.review import ReviewOut


ORDER_STATUS_ES = {
    "pending": "Pendiente",
    "confirmed": "Confirmado",
    "preparing": "Preparando",
    "ready": "Listo",
    "in_delivery": "En reparto",
    "picked_up": "Recogido",
    "delivered": "Entregado",
    "cancelled": "Cancelado",
}
PAYMENT_STATUS_ES = {
    "pending": "Pendiente",
    "approved": "Aprobado",
    "in_process": "En proceso",
    "rejected": "Rechazado",
    "refunded": "Reembolsado",
    "cancelled": "Cancelado",
    "paid": "Pagado",
}
PAYOUT_STATUS_ES = {
    "pending": "Pendiente",
    "paid": "Pagada",
    "confirmed": "Confirmada",
    "cancelled": "Cancelada",
}
MANDADO_STATUS_ES = {
    "pending": "Pendiente",
    "accepted": "Aceptado",
    "buying": "Comprando",
    "purchased": "Comprado",
    "in_delivery": "En camino",
    "completed": "Completado",
    "cancelled": "Cancelado",
}
PAYMENT_METHOD_ES = {
    "cash": "Efectivo",
    "mp": "Mercado Pago",
    "transfer": "Transferencia",
}
REFUND_STATUS_ES = {
    "none": "Sin reembolso",
    "not_required": "No requiere",
    "pending": "Pendiente",
    "refunded": "Reembolsado",
}


def _es(mapping: dict, value):
    return mapping.get(value, value)


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        email = form.get("username", "")
        password = form.get("password", "")

        from sqlalchemy import select
        async with async_session() as db:
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()

        if not user or not verify_password(password, user.password_hash):
            return False

        token = create_access_token(subject=str(user.id))
        request.session.update({"token": token})
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        token = request.session.get("token")
        if not token:
            return False
        payload = decode_access_token(token)
        if payload is None:
            return False
        from sqlalchemy import select
        async with async_session() as db:
            result = await db.execute(
                select(User).where(User.id == payload.get("sub"), User.is_superuser == True)
            )
            user = result.scalar_one_or_none()
        return user is not None


class UserAdmin(ModelView, model=User):
    name = "Usuario"
    name_plural = "Usuarios"
    icon = "fa-solid fa-user"
    column_list = [User.id, User.name, User.email, User.phone, User.is_active, User.is_superuser, User.created_at]
    column_labels = {
        User.name: "Nombre",
        User.email: "Correo",
        User.phone: "Teléfono",
        User.is_active: "Activo",
        User.is_superuser: "Administrador",
        User.created_at: "Creado",
        User.updated_at: "Actualizado",
        User.password_hash: "Contraseña",
        User.address: "Dirección",
        User.location: "Ubicación",
    }
    column_searchable_list = [User.name, User.email]
    column_sortable_list = [User.created_at]
    form_excluded_columns = [User.password_hash, User.created_at, User.updated_at, User.location, User.address]


class RestaurantAdmin(ModelView, model=Restaurant):
    name = "Negocio"
    name_plural = "Negocios"
    icon = "fa-solid fa-store"
    column_list = [Restaurant.id, Restaurant.name, Restaurant.cuisine, Restaurant.is_open, Restaurant.rating, Restaurant.delivery_fee, Restaurant.fixed_fee, Restaurant.affiliation_expires_at]
    column_labels = {
        Restaurant.name: "Nombre",
        Restaurant.description: "Descripción",
        Restaurant.cuisine: "Giro",
        Restaurant.location: "Ubicación",
        Restaurant.address: "Dirección",
        Restaurant.phone: "Teléfono",
        Restaurant.logo_url: "Logo URL",
        Restaurant.is_open: "Abierto",
        Restaurant.rating: "Calificación",
        Restaurant.owner_id: "Dueño",
        Restaurant.delivery_radius_m: "Radio de entrega (m)",
        Restaurant.delivery_fee: "Costo de envío",
        Restaurant.preparation_base_time_min: "Tiempo base alistamiento (min)",
        Restaurant.commission_percentage: "Comisión %",
        Restaurant.commission_mode: "Modo de cobro (percentage/fixed)",
        Restaurant.fixed_fee: "Cuota fija por pedido",
        Restaurant.affiliation_expires_at: "Afiliación pagada hasta",
        Restaurant.payout_frequency_days: "Días entre liquidaciones",
        Restaurant.bank_name: "Banco",
        Restaurant.bank_account_holder: "Titular de cuenta",
        Restaurant.bank_clabe: "CLABE",
        Restaurant.created_at: "Creado",
        Restaurant.updated_at: "Actualizado",
    }
    column_searchable_list = [Restaurant.name]
    form_excluded_columns = [
        Restaurant.created_at,
        Restaurant.updated_at,
        Restaurant.commission_mode,
        Restaurant.commission_percentage,
    ]
    create_template = "sqladmin/restaurant/create.html"
    edit_template = "sqladmin/restaurant/edit.html"


class MenuCategoryAdmin(ModelView, model=MenuCategory):
    name = "Categoría"
    name_plural = "Categorías"
    icon = "fa-solid fa-tag"
    column_list = [MenuCategory.id, MenuCategory.name, MenuCategory.restaurant_id, MenuCategory.sort_order]
    column_labels = {
        MenuCategory.name: "Nombre",
        MenuCategory.restaurant_id: "Negocio",
        MenuCategory.sort_order: "Orden",
        MenuCategory.created_at: "Creado",
        MenuCategory.updated_at: "Actualizado",
    }
    form_excluded_columns = [MenuCategory.created_at, MenuCategory.updated_at]


class MenuItemAdmin(ModelView, model=MenuItem):
    name = "Producto"
    name_plural = "Productos"
    icon = "fa-solid fa-utensils"
    column_list = [MenuItem.id, MenuItem.name, MenuItem.price, MenuItem.is_available, MenuItem.restaurant_id]
    column_labels = {
        MenuItem.name: "Nombre",
        MenuItem.description: "Descripción",
        MenuItem.price: "Precio",
        MenuItem.image_url: "Imagen URL",
        MenuItem.is_available: "Disponible",
        MenuItem.restaurant_id: "Negocio",
        MenuItem.category_id: "Categoría",
        MenuItem.preparation_time_min: "Tiempo alistamiento (min)",
        MenuItem.created_at: "Creado",
        MenuItem.updated_at: "Actualizado",
    }
    column_searchable_list = [MenuItem.name]
    form_excluded_columns = [MenuItem.created_at, MenuItem.updated_at, MenuItem.image_url]


class OrderAdmin(ModelView, model=Order):
    name = "Pedido"
    name_plural = "Pedidos"
    icon = "fa-solid fa-truck"
    column_list = [Order.id, Order.user_id, Order.restaurant_id, Order.status, Order.payment_method, Order.payment_status, Order.refund_status, Order.total, Order.placed_at]
    column_labels = {
        Order.user_id: "Cliente",
        Order.restaurant_id: "Negocio",
        Order.delivery_person_id: "Repartidor",
        Order.status: "Estado",
        Order.subtotal: "Subtotal",
        Order.delivery_fee: "Envío",
        Order.total: "Total",
        Order.delivery_address: "Dirección de entrega",
        Order.delivery_location: "Ubicación de entrega",
        Order.notes: "Notas",
        Order.estimated_delivery_min: "Tiempo estimado (min)",
        Order.payment_method: "Método de pago",
        Order.payment_status: "Estado del pago",
        Order.payment_id: "ID de pago",
        Order.preference_id: "ID preferencia MP",
        Order.coupon_id: "Cupón",
        Order.coupon_code: "Código de cupón",
        Order.discount_amount: "Descuento",
        Order.platform_commission: "Comisión plataforma",
        Order.flat_usage_fee: "Cargo por uso",
        Order.delivery_earnings: "Ganancia repartidor",
        Order.delivery_distance_km: "Distancia (km)",
        Order.placed_at: "Fecha del pedido",
        Order.confirmed_at: "Confirmado",
        Order.picked_up_at: "Recogido",
        Order.delivered_at: "Entregado",
        Order.cancelled_at: "Cancelado",
        Order.cancelled_by: "Cancelado por",
        Order.cancellation_reason: "Motivo de cancelación",
        Order.refund_amount: "Reembolso",
        Order.refund_status: "Estado del reembolso",
        Order.created_at: "Creado",
        Order.updated_at: "Actualizado",
    }
    column_sortable_list = [Order.placed_at]
    form_excluded_columns = [
        Order.items, Order.created_at, Order.updated_at, Order.placed_at,
        Order.confirmed_at, Order.picked_up_at, Order.delivered_at,
        Order.cancelled_at, Order.cancelled_by,
        Order.delivery_location, Order.preference_id, Order.payment_id,
        Order.platform_commission, Order.flat_usage_fee, Order.delivery_earnings,
        Order.delivery_distance_km,
    ]
    column_formatters = {
        Order.status: lambda m, a: _es(ORDER_STATUS_ES, m.status),
        Order.payment_status: lambda m, a: _es(PAYMENT_STATUS_ES, m.payment_status),
        Order.payment_method: lambda m, a: _es(PAYMENT_METHOD_ES, m.payment_method),
        Order.refund_status: lambda m, a: _es(REFUND_STATUS_ES, m.refund_status),
    }
    column_formatters_detail = column_formatters
    form_choices = {
        Order.status: [(k, v) for k, v in ORDER_STATUS_ES.items()],
        Order.payment_status: [(k, v) for k, v in PAYMENT_STATUS_ES.items()],
        Order.payment_method: [(k, v) for k, v in PAYMENT_METHOD_ES.items() if k in ("cash", "mp", "transfer")],
        Order.refund_status: [(k, v) for k, v in REFUND_STATUS_ES.items()],
    }

    @action(
        name="mark_transfer_received",
        label="Marcar transferencia recibida",
        confirmation_message="¿Marcar las transferencias seleccionadas como recibidas por la plataforma?",
        add_in_list=True,
        add_in_detail=True,
    )
    async def mark_transfer_received(self, request: Request) -> RedirectResponse:
        pks = [pk for pk in request.query_params.get("pks", "").split(",") if pk]
        if pks:
            async with self.session_maker() as session:
                result = await session.execute(
                    select(Order).where(
                        Order.id.in_(pks),
                        Order.payment_method == "transfer",
                    )
                )
                for order in result.scalars().all():
                    order.payment_status = "approved"
                await session.commit()
        return RedirectResponse(
            request.url_for("admin:list", identity=self.identity), status_code=303
        )


class OrderItemAdmin(ModelView, model=OrderItem):
    name = "Artículo de pedido"
    name_plural = "Artículos de pedido"
    icon = "fa-solid fa-receipt"
    column_list = [OrderItem.id, OrderItem.order_id, OrderItem.name, OrderItem.quantity, OrderItem.subtotal]
    column_labels = {
        OrderItem.order_id: "Pedido",
        OrderItem.menu_item_id: "Producto",
        OrderItem.name: "Nombre",
        OrderItem.quantity: "Cantidad",
        OrderItem.unit_price: "Precio unitario",
        OrderItem.subtotal: "Subtotal",
        OrderItem.notes: "Notas",
        OrderItem.created_at: "Creado",
        OrderItem.updated_at: "Actualizado",
    }
    form_excluded_columns = [OrderItem.created_at, OrderItem.updated_at, OrderItem.menu_item_id]


class DeliveryPersonAdmin(ModelView, model=DeliveryPerson):
    name = "Repartidor"
    name_plural = "Repartidores"
    icon = "fa-solid fa-motorcycle"
    column_list = [DeliveryPerson.id, DeliveryPerson.user_id, DeliveryPerson.vehicle_type, DeliveryPerson.is_available, DeliveryPerson.is_mandadero, DeliveryPerson.rating, DeliveryPerson.total_deliveries]
    column_labels = {
        DeliveryPerson.user_id: "Usuario",
        DeliveryPerson.vehicle_type: "Vehículo",
        DeliveryPerson.is_available: "Disponible",
        DeliveryPerson.is_mandadero: "Acepta mandados",
        DeliveryPerson.current_location: "Ubicación actual",
        DeliveryPerson.current_order_id: "Pedido actual",
        DeliveryPerson.rating: "Calificación",
        DeliveryPerson.total_deliveries: "Entregas totales",
        DeliveryPerson.payout_method: "Método de pago",
        DeliveryPerson.payout_frequency_days: "Días entre cortes",
        DeliveryPerson.bank_name: "Banco",
        DeliveryPerson.bank_account_holder: "Titular",
        DeliveryPerson.bank_clabe: "CLABE",
        DeliveryPerson.pending_platform_debt: "Deuda plataforma",
        DeliveryPerson.delivery_bonus_per_order: "Bono por envío",
        DeliveryPerson.created_at: "Creado",
        DeliveryPerson.updated_at: "Actualizado",
    }
    form_excluded_columns = [
        DeliveryPerson.created_at, DeliveryPerson.updated_at,
        DeliveryPerson.current_location, DeliveryPerson.current_order_id,
        DeliveryPerson.rating, DeliveryPerson.total_deliveries,
        DeliveryPerson.pending_platform_debt,
    ]
    form_choices = {
        DeliveryPerson.vehicle_type: [
            ("bike", "Bicicleta"),
            ("motorcycle", "Motocicleta"),
            ("car", "Automóvil"),
        ],
        DeliveryPerson.payout_method: [
            ("cash", "Efectivo"),
            ("transfer", "Transferencia"),
        ],
    }


class DeliveryLocationAdmin(ModelView, model=DeliveryLocation):
    name = "Ubicación de reparto"
    name_plural = "Ubicaciones de reparto"
    icon = "fa-solid fa-map-marker"
    column_list = [DeliveryLocation.id, DeliveryLocation.delivery_person_id, DeliveryLocation.order_id, DeliveryLocation.recorded_at]
    column_labels = {
        DeliveryLocation.delivery_person_id: "Repartidor",
        DeliveryLocation.order_id: "Pedido",
        DeliveryLocation.location: "Ubicación",
        DeliveryLocation.recorded_at: "Registrado",
        DeliveryLocation.speed_kmh: "Velocidad (km/h)",
    }
    column_sortable_list = [DeliveryLocation.recorded_at]
    form_excluded_columns = [DeliveryLocation.location, DeliveryLocation.speed_kmh, DeliveryLocation.recorded_at]


class ReviewAdmin(ModelView, model=Review):
    name = "Reseña"
    name_plural = "Reseñas"
    icon = "fa-solid fa-star"
    column_list = [Review.id, Review.order_id, Review.user_id, Review.restaurant_id, Review.rating, Review.created_at]
    column_labels = {
        Review.order_id: "Pedido",
        Review.user_id: "Usuario",
        Review.restaurant_id: "Negocio",
        Review.delivery_person_id: "Repartidor",
        Review.rating: "Calificación",
        Review.comment: "Comentario",
        Review.created_at: "Creado",
        Review.updated_at: "Actualizado",
    }
    column_sortable_list = [Review.created_at]
    form_excluded_columns = [Review.created_at, Review.updated_at, Review.delivery_person_id]


class CouponAdmin(ModelView, model=Coupon):
    name = "Cupón"
    name_plural = "Cupones"
    icon = "fa-solid fa-ticket"
    column_list = [Coupon.code, Coupon.discount_type, Coupon.discount_value, Coupon.current_uses, Coupon.max_uses, Coupon.is_active, Coupon.valid_until]
    column_labels = {
        Coupon.code: "Código",
        Coupon.description: "Descripción",
        Coupon.discount_type: "Tipo de descuento",
        Coupon.discount_value: "Valor del descuento",
        Coupon.min_order_amount: "Monto mínimo",
        Coupon.max_discount: "Descuento máximo",
        Coupon.max_uses: "Usos máximos",
        Coupon.current_uses: "Usos actuales",
        Coupon.is_active: "Activo",
        Coupon.valid_from: "Válido desde",
        Coupon.valid_until: "Válido hasta",
        Coupon.restaurant_id: "Negocio",
        Coupon.created_at: "Creado",
        Coupon.updated_at: "Actualizado",
    }
    column_searchable_list = [Coupon.code]
    form_excluded_columns = [Coupon.created_at, Coupon.updated_at, Coupon.current_uses]
    form_choices = {
        Coupon.discount_type: [
            ("percentage", "Porcentaje"),
            ("fixed", "Monto fijo"),
        ]
    }


class SavedAddressAdmin(ModelView, model=SavedAddress):
    name = "Dirección"
    name_plural = "Direcciones guardadas"
    icon = "fa-solid fa-map-pin"
    column_list = [SavedAddress.id, SavedAddress.user_id, SavedAddress.name, SavedAddress.address, SavedAddress.is_default]
    column_labels = {
        SavedAddress.user_id: "Usuario",
        SavedAddress.name: "Nombre",
        SavedAddress.address: "Dirección",
        SavedAddress.location: "Ubicación",
        SavedAddress.is_default: "Por defecto",
        SavedAddress.notes: "Notas",
        SavedAddress.created_at: "Creado",
        SavedAddress.updated_at: "Actualizado",
    }
    column_searchable_list = [SavedAddress.name, SavedAddress.address]
    form_excluded_columns = [SavedAddress.created_at, SavedAddress.updated_at, SavedAddress.id, SavedAddress.location, SavedAddress.is_default]


class SettingAdmin(ModelView, model=Setting):
    name = "Configuración"
    name_plural = "Configuraciones"
    icon = "fa-solid fa-cog"
    column_list = [Setting.key, Setting.value, Setting.description]
    column_labels = {
        Setting.key: "Clave",
        Setting.value: "Valor",
        Setting.description: "Descripción",
        Setting.created_at: "Creado",
        Setting.updated_at: "Actualizado",
    }
    column_searchable_list = [Setting.key]
    form_excluded_columns = [Setting.created_at, Setting.updated_at, Setting.id]
    can_delete = True
    can_create = True


class DeliveryPayoutAdmin(ModelView, model=DeliveryPayout):
    name = "Liquidación de repartidor"
    name_plural = "Liquidaciones de repartidores"
    icon = "fa-solid fa-money-bill-wave"
    column_list = [DeliveryPayout.id, DeliveryPayout.delivery_person_id, DeliveryPayout.period_start, DeliveryPayout.period_end, DeliveryPayout.total_earnings, DeliveryPayout.status]
    column_labels = {
        DeliveryPayout.delivery_person_id: "Repartidor",
        DeliveryPayout.period_start: "Inicio",
        DeliveryPayout.period_end: "Fin",
        DeliveryPayout.orders_count: "Pedidos",
        DeliveryPayout.total_earnings: "Total a pagar",
        DeliveryPayout.payout_method: "Método",
        DeliveryPayout.confirmation_code: "Código de confirmación",
        DeliveryPayout.status: "Estado",
        DeliveryPayout.paid_at: "Pagado",
        DeliveryPayout.confirmed_at: "Confirmado",
        DeliveryPayout.notes: "Notas",
        DeliveryPayout.created_at: "Creado",
        DeliveryPayout.updated_at: "Actualizado",
    }
    column_sortable_list = [DeliveryPayout.created_at]
    form_excluded_columns = [
        DeliveryPayout.created_at, DeliveryPayout.updated_at,
        DeliveryPayout.confirmation_code, DeliveryPayout.confirmed_at,
        DeliveryPayout.orders_count, DeliveryPayout.total_earnings,
        DeliveryPayout.delivery_person_id, DeliveryPayout.payout_method,
        DeliveryPayout.period_start, DeliveryPayout.period_end,
    ]
    can_create = False
    can_delete = False
    can_edit = True
    column_default_sort = [("created_at", True)]
    form_widget_args = {
        DeliveryPayout.paid_at: {"type": "datetime-local"},
    }
    column_formatters = {
        DeliveryPayout.status: lambda m, a: _es(PAYOUT_STATUS_ES, m.status),
    }
    column_formatters_detail = column_formatters
    form_choices = {
        DeliveryPayout.status: [(k, v) for k, v in PAYOUT_STATUS_ES.items()],
    }

    @action(
        name="mark_paid",
        label="Marcar como pagado",
        confirmation_message="¿Marcar las liquidaciones seleccionadas como pagadas?",
        add_in_list=True,
        add_in_detail=True,
    )
    async def mark_paid(self, request: Request) -> RedirectResponse:
        pks = [pk for pk in request.query_params.get("pks", "").split(",") if pk]
        if pks:
            now = datetime.now(timezone.utc)
            async with self.session_maker() as session:
                result = await session.execute(
                    select(DeliveryPayout).where(DeliveryPayout.id.in_(pks))
                )
                for payout in result.scalars().all():
                    payout.status = "paid"
                    payout.paid_at = now
                    if payout.confirmed_at is None:
                        payout.confirmed_at = now
                await session.commit()
        return RedirectResponse(
            request.url_for("admin:list", identity=self.identity), status_code=303
        )


class RestaurantPayoutAdmin(ModelView, model=RestaurantPayout):
    name = "Liquidación de negocio"
    name_plural = "Liquidaciones de negocios"
    icon = "fa-solid fa-building-columns"
    column_list = [RestaurantPayout.id, RestaurantPayout.restaurant_id, RestaurantPayout.period_start, RestaurantPayout.period_end, RestaurantPayout.net_payout, RestaurantPayout.status]
    column_labels = {
        RestaurantPayout.restaurant_id: "Negocio",
        RestaurantPayout.period_start: "Inicio",
        RestaurantPayout.period_end: "Fin",
        RestaurantPayout.orders_count: "Pedidos",
        RestaurantPayout.total_subtotal: "Subtotal total",
        RestaurantPayout.total_commission: "Comisión total",
        RestaurantPayout.total_flat_fees: "Cargos totales",
        RestaurantPayout.net_payout: "Liquidación neta",
        RestaurantPayout.status: "Estado",
        RestaurantPayout.paid_at: "Pagado",
        RestaurantPayout.confirmed_at: "Confirmado",
        RestaurantPayout.notes: "Notas",
        RestaurantPayout.created_at: "Creado",
        RestaurantPayout.updated_at: "Actualizado",
    }
    column_sortable_list = [RestaurantPayout.created_at]
    form_excluded_columns = [
        RestaurantPayout.created_at, RestaurantPayout.updated_at,
        RestaurantPayout.paid_at, RestaurantPayout.confirmed_at,
        RestaurantPayout.total_subtotal, RestaurantPayout.total_commission,
        RestaurantPayout.total_flat_fees, RestaurantPayout.net_payout,
        RestaurantPayout.orders_count,
    ]
    can_create = False
    can_delete = False
    column_formatters = {
        RestaurantPayout.status: lambda m, a: _es(PAYOUT_STATUS_ES, m.status),
    }
    column_formatters_detail = column_formatters
    form_choices = {
        RestaurantPayout.status: [(k, v) for k, v in PAYOUT_STATUS_ES.items()],
    }

    @action(
        name="mark_paid",
        label="Marcar como pagado",
        confirmation_message="¿Marcar las liquidaciones seleccionadas como pagadas?",
        add_in_list=True,
        add_in_detail=True,
    )
    async def mark_paid(self, request: Request) -> RedirectResponse:
        pks = [pk for pk in request.query_params.get("pks", "").split(",") if pk]
        if pks:
            now = datetime.now(timezone.utc)
            async with self.session_maker() as session:
                result = await session.execute(
                    select(RestaurantPayout).where(RestaurantPayout.id.in_(pks))
                )
                for payout in result.scalars().all():
                    payout.status = "paid"
                    payout.paid_at = now
                    if payout.confirmed_at is None:
                        payout.confirmed_at = now
                await session.commit()
        return RedirectResponse(
            request.url_for("admin:list", identity=self.identity), status_code=303
        )


class MandadoAdmin(ModelView, model=Mandado):
    name = "Mandado"
    name_plural = "Mandados"
    icon = "fa-solid fa-box"
    column_list = [Mandado.id, Mandado.user_id, Mandado.description, Mandado.status, Mandado.estimated_total]
    column_labels = {
        Mandado.user_id: "Cliente",
        Mandado.delivery_person_id: "Repartidor",
        Mandado.description: "Descripción",
        Mandado.estimated_budget: "Presupuesto estimado",
        Mandado.product_total: "Total real productos",
        Mandado.delivery_fee: "Envío",
        Mandado.risk_fee: "Extra por riesgo",
        Mandado.platform_fee: "Comisión plataforma",
        Mandado.estimated_total: "Total estimado",
        Mandado.final_total: "Total final",
        Mandado.payment_method: "Método de pago",
        Mandado.payment_status: "Estado del pago",
        Mandado.status: "Estado",
        Mandado.delivery_address: "Dirección",
        Mandado.delivery_location: "Ubicación",
        Mandado.receipt_photo_url: "Foto del ticket",
        Mandado.accepted_at: "Aceptado",
        Mandado.purchased_at: "Comprado",
        Mandado.delivered_at: "Entregado",
        Mandado.created_at: "Creado",
        Mandado.updated_at: "Actualizado",
    }
    column_sortable_list = [Mandado.created_at]
    form_excluded_columns = [
        Mandado.delivery_location, Mandado.created_at, Mandado.updated_at,
        Mandado.accepted_at, Mandado.purchased_at, Mandado.delivered_at,
        Mandado.final_total, Mandado.payment_status, Mandado.receipt_photo_url,
    ]
    form_choices = {
        Mandado.status: [
            ("pending", "Pendiente"),
            ("accepted", "Aceptado"),
            ("buying", "Comprando"),
            ("purchased", "Comprado"),
            ("in_delivery", "En camino"),
            ("completed", "Completado"),
            ("cancelled", "Cancelado"),
        ],
        Mandado.payment_method: [
            ("cash", "Efectivo"),
            ("mp", "Mercado Pago"),
        ],
        Mandado.payment_status: [
            ("pending", "Pendiente"),
            ("paid", "Pagado"),
        ],
    }
    column_formatters = {
        Mandado.status: lambda m, a: _es(MANDADO_STATUS_ES, m.status),
        Mandado.payment_status: lambda m, a: _es(PAYMENT_STATUS_ES, m.payment_status),
        Mandado.payment_method: lambda m, a: _es(PAYMENT_METHOD_ES, m.payment_method),
    }
    column_formatters_detail = column_formatters


class CashAdvanceAdmin(ModelView, model=CashAdvance):
    name = "Avance de caja"
    name_plural = "Avances de caja"
    icon = "fa-solid fa-coins"
    column_list = [CashAdvance.id, CashAdvance.delivery_person_id, CashAdvance.order_id, CashAdvance.amount, CashAdvance.pays_restaurant, CashAdvance.status, CashAdvance.taken_at]
    column_labels = {
        CashAdvance.delivery_person_id: "Repartidor",
        CashAdvance.order_id: "Pedido",
        CashAdvance.mandado_id: "Mandado",
        CashAdvance.approved_by: "Aprobado por",
        CashAdvance.amount: "Monto",
        CashAdvance.pays_restaurant: "Pago al restaurante",
        CashAdvance.settlement_method: "Forma de liquidación",
        CashAdvance.status: "Estado",
        CashAdvance.taken_at: "Tomado",
        CashAdvance.settled_at: "Liquidado",
        CashAdvance.notes: "Notas",
    }
    column_sortable_list = [CashAdvance.taken_at]
    form_excluded_columns = [CashAdvance.taken_at, CashAdvance.settled_at]
    form_choices = {
        CashAdvance.status: [
            ("pending", "Solicitado"),
            ("approved", "Entregado"),
            ("settled", "Liquidado"),
            ("rejected", "Rechazado"),
        ],
        CashAdvance.settlement_method: [
            ("cash", "Efectivo"),
            ("payout", "Descontado del pago"),
            ("restaurant_payment", "Pago al restaurante"),
        ],
    }
    column_formatters = {
        CashAdvance.status: lambda m, a: _es({
            "pending": "Solicitado", "approved": "Entregado",
            "settled": "Liquidado", "rejected": "Rechazado",
        }, m.status),
    }
    column_formatters_detail = column_formatters

