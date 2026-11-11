"""Seed database with test data: restaurants, menus, delivery persons."""

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import async_session
from app.models.user import User
from app.models.restaurant import Restaurant
from app.models.menu_category import MenuCategory
from app.models.menu_item import MenuItem
from app.models.delivery_person import DeliveryPerson
from app.models.setting import Setting


async def _clean_db(db: AsyncSession):
    await db.execute(text("DELETE FROM cash_advances"))
    await db.execute(text("DELETE FROM mandados"))
    await db.execute(text("DELETE FROM delivery_payouts"))
    await db.execute(text("DELETE FROM restaurant_payouts"))
    await db.execute(text("DELETE FROM reviews"))
    await db.execute(text("DELETE FROM delivery_locations"))
    await db.execute(text("DELETE FROM order_items"))
    await db.execute(text("DELETE FROM orders"))
    await db.execute(text("DELETE FROM delivery_persons"))
    await db.execute(text("DELETE FROM menu_items"))
    await db.execute(text("DELETE FROM menu_categories"))
    await db.execute(text("DELETE FROM restaurants"))
    await db.execute(text("DELETE FROM users"))
    await db.execute(text("DELETE FROM settings"))
    await db.commit()


async def seed():
    async with async_session() as db:
        print("🧹 Limpiando base de datos...")
        await _clean_db(db)

        now = datetime.now(timezone.utc)
        hashed = hash_password("123456")

        # ── USERS ───────────────────────────────────────────
        users_data = [
            User(id=uuid.uuid4(), name="Carlos López", email="carlos@email.com",
                 phone="555-1001", password_hash=hashed, is_active=True, is_superuser=True),
            User(id=uuid.uuid4(), name="María García", email="maria@email.com",
                 phone="555-1002", password_hash=hashed, is_active=True),
            User(id=uuid.uuid4(), name="Don Taco (Dueño)", email="don@tacos.com",
                 phone="555-2001", password_hash=hashed, is_active=True),
            User(id=uuid.uuid4(), name="Pizza Mía (Dueño)", email="info@pizzamia.com",
                 phone="555-2002", password_hash=hashed, is_active=True),
            User(id=uuid.uuid4(), name="Sushi House (Dueño)", email="info@sushi.com",
                 phone="555-2003", password_hash=hashed, is_active=True),
            User(id=uuid.uuid4(), name="Pedro Pérez", email="pedro@repartidor.com",
                 phone="555-3001", password_hash=hashed, is_active=True),
        ]
        db.add_all(users_data)
        await db.flush()

        (
            carlos, maria,
            don_taco_owner, pizza_owner, sushi_owner,
            pedro,
        ) = users_data

        print(f"  ✓ {len(users_data)} usuarios creados")

        # ── RESTAURANTS ─────────────────────────────────────
        # Coordinates: Santa Cruz de Juventino Rosas, Guanajuato (approx 20.644, -100.993)
        restaurants_data = [
            Restaurant(
                id=uuid.uuid4(), owner_id=don_taco_owner.id,
                name="Taquería El Norteño", description="Tacos al pastor, bistec y costilla. Tortillas hechas a mano.",
                location="SRID=4326;POINT(-100.9930 20.6440)",
                address="Av. Hidalgo 45, Centro", phone="555-8101",
                logo_url=None, is_open=True, rating=4.5, delivery_radius_m=4000, delivery_fee=15.00,
                preparation_base_time_min=10, commission_percentage=12.0,
            ),
            Restaurant(
                id=uuid.uuid4(), owner_id=pizza_owner.id,
                name="Pizza Mía", description="Pizzas artesanales, pastas y ensaladas. Hornos de leña.",
                location="SRID=4326;POINT(-100.9910 20.6460)",
                address="Calle Juárez 102, Centro", phone="555-8102",
                logo_url=None, is_open=True, rating=4.2, delivery_radius_m=5000, delivery_fee=20.00,
                preparation_base_time_min=15, commission_percentage=15.0,
            ),
            Restaurant(
                id=uuid.uuid4(), owner_id=sushi_owner.id,
                name="Sushi House", description="Rollos, sashimis y platillos japoneses. Frescura garantizada.",
                location="SRID=4326;POINT(-100.9950 20.6420)",
                address="Blvd. Independencia 78, Zona Norte", phone="555-8103",
                logo_url=None, is_open=True, rating=4.7, delivery_radius_m=3500, delivery_fee=18.00,
                preparation_base_time_min=12, commission_percentage=15.0,
            ),
        ]
        db.add_all(restaurants_data)
        await db.flush()

        (tacos, pizza, sushi) = restaurants_data
        print(f"  ✓ {len(restaurants_data)} restaurantes creados")

        # ── MENU CATEGORIES ─────────────────────────────────
        cats_data = [
            MenuCategory(id=uuid.uuid4(), restaurant_id=tacos.id, name="Tacos", sort_order=1),
            MenuCategory(id=uuid.uuid4(), restaurant_id=tacos.id, name="Bebidas", sort_order=2),
            MenuCategory(id=uuid.uuid4(), restaurant_id=pizza.id, name="Pizzas", sort_order=1),
            MenuCategory(id=uuid.uuid4(), restaurant_id=pizza.id, name="Pastas", sort_order=2),
            MenuCategory(id=uuid.uuid4(), restaurant_id=pizza.id, name="Bebidas", sort_order=3),
            MenuCategory(id=uuid.uuid4(), restaurant_id=sushi.id, name="Rollos", sort_order=1),
            MenuCategory(id=uuid.uuid4(), restaurant_id=sushi.id, name="Bebidas", sort_order=2),
        ]
        db.add_all(cats_data)
        await db.flush()

        (
            tacos_cat, tacos_drinks,
            pizza_cat, pasta_cat, pizza_drinks,
            sushi_cat, sushi_drinks,
        ) = cats_data
        print(f"  ✓ {len(cats_data)} categorías creadas")

        # ── MENU ITEMS ──────────────────────────────────────
        items_data = [
            # Taquería El Norteño
            MenuItem(id=uuid.uuid4(), restaurant_id=tacos.id, category_id=tacos_cat.id,
                     name="Taco al Pastor", description="Carne al pastor con piña, cebolla y cilantro.",
                     price=25.00, preparation_time_min=5, is_available=True),
            MenuItem(id=uuid.uuid4(), restaurant_id=tacos.id, category_id=tacos_cat.id,
                     name="Taco de Bistec", description="Bistec asado con cebolla y verduras.",
                     price=30.00, preparation_time_min=7, is_available=True),
            MenuItem(id=uuid.uuid4(), restaurant_id=tacos.id, category_id=tacos_cat.id,
                     name="Taco de Costilla", description="Costilla de res deshebrada, salsa verde.",
                     price=35.00, preparation_time_min=8, is_available=True),
            MenuItem(id=uuid.uuid4(), restaurant_id=tacos.id, category_id=tacos_cat.id,
                     name="Taco de Suadero", description="Suadero dorado con cebolla y cilantro.",
                     price=28.00, preparation_time_min=6, is_available=True),
            MenuItem(id=uuid.uuid4(), restaurant_id=tacos.id, category_id=tacos_drinks.id,
                     name="Agua de Horchata", price=18.00, preparation_time_min=2, is_available=True),
            MenuItem(id=uuid.uuid4(), restaurant_id=tacos.id, category_id=tacos_drinks.id,
                     name="Refresco de Cola 500ml", price=22.00, preparation_time_min=1, is_available=True),
            # Pizza Mía
            MenuItem(id=uuid.uuid4(), restaurant_id=pizza.id, category_id=pizza_cat.id,
                     name="Pizza Margherita", description="Queso mozzarella, albahaca fresca, salsa de tomate.",
                     price=120.00, preparation_time_min=20, is_available=True),
            MenuItem(id=uuid.uuid4(), restaurant_id=pizza.id, category_id=pizza_cat.id,
                     name="Pizza Pepperoni", description="Pepperoni clásico con queso extra.",
                     price=135.00, preparation_time_min=20, is_available=True),
            MenuItem(id=uuid.uuid4(), restaurant_id=pizza.id, category_id=pizza_cat.id,
                     name="Pizza Hawaiana", description="Jamón, piña, queso mozzarella.",
                     price=130.00, preparation_time_min=20, is_available=True),
            MenuItem(id=uuid.uuid4(), restaurant_id=pizza.id, category_id=pasta_cat.id,
                     name="Spaghetti Bolognese", description="Carne molida, salsa de jitomate, parmesano.",
                     price=95.00, preparation_time_min=15, is_available=True),
            MenuItem(id=uuid.uuid4(), restaurant_id=pizza.id, category_id=pizza_drinks.id,
                     name="Agua de Jamaica", price=18.00, preparation_time_min=2, is_available=True),
            # Sushi House
            MenuItem(id=uuid.uuid4(), restaurant_id=sushi.id, category_id=sushi_cat.id,
                     name="Roll California", description="Cangrejo, aguacate, pepino, ajonjolí.",
                     price=85.00, preparation_time_min=12, is_available=True),
            MenuItem(id=uuid.uuid4(), restaurant_id=sushi.id, category_id=sushi_cat.id,
                     name="Roll Philadelphia", description="Salmón ahumado, queso crema, aguacate.",
                     price=95.00, preparation_time_min=12, is_available=True),
            MenuItem(id=uuid.uuid4(), restaurant_id=sushi.id, category_id=sushi_cat.id,
                     name="Roll Dragón", description="Langostino tempura, aguacate, salsa eel.",
                     price=110.00, preparation_time_min=15, is_available=True),
            MenuItem(id=uuid.uuid4(), restaurant_id=sushi.id, category_id=sushi_cat.id,
                     name="Sashimi Mix (8 pzas)", description="Salmón, atún, pez blanco.",
                     price=140.00, preparation_time_min=10, is_available=True),
            MenuItem(id=uuid.uuid4(), restaurant_id=sushi.id, category_id=sushi_drinks.id,
                     name="Té Verde Helado", price=20.00, preparation_time_min=2, is_available=True),
        ]
        db.add_all(items_data)
        print(f"  ✓ {len(items_data)} productos creados")

        # ── DELIVERY PERSON ─────────────────────────────────
        dp = DeliveryPerson(
            id=uuid.uuid4(), user_id=pedro.id, vehicle_type="motorcycle",
            is_available=True, rating=4.8, total_deliveries=45,
            is_mandadero=True, payout_method="cash", payout_frequency_days=3,
            current_location="SRID=4326;POINT(-99.1320 19.4330)",
        )
        db.add(dp)
        print("  ✓ 1 repartidor creado")

        # ── SETTINGS ────────────────────────────────────────
        settings_data = [
            Setting(key="APP_COMMISSION_PERCENTAGE", value="15.0",
                    description="Porcentaje de comisión global para pedidos de tienda"),
            Setting(key="APP_FLAT_USAGE_FEE", value="5.0",
                    description="Cargo fijo por uso de plataforma (pesos)"),
            Setting(key="DELIVERY_BASE_FEE", value="20.0",
                    description="Tarifa base de envío (pesos)"),
            Setting(key="DELIVERY_FREE_RADIUS_KM", value="2.0",
                    description="Kilómetros incluidos sin costo extra"),
            Setting(key="DELIVERY_EXTRA_FEE_PER_KM", value="5.0",
                    description="Cargo adicional por km extra (pesos)"),
            Setting(key="MANDADO_PLATFORM_FEE", value="10.0",
                    description="Comisión fija por mandado (pesos)"),
            Setting(key="MANDADO_RISK_FEE_TYPE", value="percentage",
                    description="Tipo de extra por riesgo: percentage o fixed"),
            Setting(key="MANDADO_RISK_PERCENTAGE", value="10.0",
                    description="Porcentaje de extra por riesgo sobre presupuesto"),
            Setting(key="MANDADO_RISK_FIXED_AMOUNT", value="15.0",
                    description="Monto fijo de extra por riesgo (pesos, si el tipo es fixed)"),
            Setting(key="MANDADO_ACTIVE", value="true",
                    description="Activar servicio de mandados"),
            Setting(key="MP_ENABLED", value="false",
                    description="Activar pagos con Mercado Pago"),
            Setting(key="TRANSFER_ENABLED", value="false",
                    description="Activar pagos por transferencia bancaria"),
            Setting(key="CITY_CENTER_LAT", value="20.644",
                    description="Latitud del centro de la ciudad (origen de mandados)"),
            Setting(key="CITY_CENTER_LNG", value="-100.993",
                    description="Longitud del centro de la ciudad (origen de mandados)"),
            Setting(key="OSRM_URL", value="",
                    description="URL de OSRM para distancia por ruta (ej. http://localhost:5000)"),
            Setting(key="ROUTE_DISTANCE_FACTOR", value="1.0",
                    description="Factor aplicado a la distancia lineal si no hay OSRM"),
        ]
        db.add_all(settings_data)
        print(f"  ✓ {len(settings_data)} configuraciones creadas")

        await db.commit()
        print(f"\n✅ Seed completado exitosamente.")
        print(f"   Usuarios: carlos@email.com / maria@email.com / pedro@repartidor.com")
        print(f"   Todos con password: 123456")
        print(f"   Negocios: Taquería El Norteño, Pizza Mía, Sushi House")
        print(f"   Configuraciones: commission 15%, flat fee $5, delivery base $20")


if __name__ == "__main__":
    asyncio.run(seed())
