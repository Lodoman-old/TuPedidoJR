"""initial migration: create all tables with postgis

Revision ID: 001
Revises:
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")

    op.execute("""
        CREATE TABLE users (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name VARCHAR(100) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE,
            phone VARCHAR(20),
            password_hash VARCHAR(255) NOT NULL,
            address TEXT,
            location GEOGRAPHY(Point, 4326),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_superuser BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.create_index("ix_users_email", "users", ["email"])

    op.execute("""
        CREATE TABLE restaurants (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            owner_id UUID NOT NULL REFERENCES users(id),
            name VARCHAR(150) NOT NULL,
            description TEXT,
            location GEOGRAPHY(Point, 4326) NOT NULL,
            address TEXT NOT NULL,
            phone VARCHAR(20),
            logo_url TEXT,
            is_open BOOLEAN NOT NULL DEFAULT TRUE,
            rating DECIMAL(2,1) NOT NULL DEFAULT 0.0,
            delivery_radius_m INTEGER NOT NULL DEFAULT 3000,
            delivery_fee DECIMAL(10,2) NOT NULL DEFAULT 0.0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE menu_categories (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            restaurant_id UUID NOT NULL REFERENCES restaurants(id),
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE menu_items (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            restaurant_id UUID NOT NULL REFERENCES restaurants(id),
            category_id UUID REFERENCES menu_categories(id),
            name VARCHAR(150) NOT NULL,
            description TEXT,
            price DECIMAL(10,2) NOT NULL,
            image_url TEXT,
            is_available BOOLEAN NOT NULL DEFAULT TRUE,
            preparation_time_min INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TYPE order_status AS ENUM (
            'pending', 'confirmed', 'preparing', 'ready',
            'in_delivery', 'delivered', 'cancelled'
        )
    """)

    # delivery_persons first (without current_order_id FK to avoid circular ref)
    op.execute("""
        CREATE TABLE delivery_persons (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID NOT NULL UNIQUE REFERENCES users(id),
            vehicle_type VARCHAR(20) NOT NULL,
            is_available BOOLEAN NOT NULL DEFAULT TRUE,
            current_location GEOGRAPHY(Point, 4326),
            current_order_id UUID,
            rating DECIMAL(2,1) NOT NULL DEFAULT 0.0,
            total_deliveries INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE orders (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID NOT NULL REFERENCES users(id),
            restaurant_id UUID NOT NULL REFERENCES restaurants(id),
            delivery_person_id UUID REFERENCES delivery_persons(id),
            status order_status NOT NULL DEFAULT 'pending',
            subtotal DECIMAL(10,2) NOT NULL,
            delivery_fee DECIMAL(10,2) NOT NULL,
            total DECIMAL(10,2) NOT NULL,
            delivery_address TEXT NOT NULL,
            delivery_location GEOGRAPHY(Point, 4326) NOT NULL,
            notes TEXT,
            estimated_delivery_min INTEGER,
            placed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            confirmed_at TIMESTAMPTZ,
            picked_up_at TIMESTAMPTZ,
            delivered_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # Now add the circular FK from delivery_persons to orders
    op.execute("""
        ALTER TABLE delivery_persons
        ADD CONSTRAINT fk_dp_current_order
        FOREIGN KEY (current_order_id) REFERENCES orders(id)
    """)

    op.execute("""
        CREATE TABLE order_items (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            order_id UUID NOT NULL REFERENCES orders(id),
            menu_item_id UUID NOT NULL REFERENCES menu_items(id),
            quantity INTEGER NOT NULL,
            unit_price DECIMAL(10,2) NOT NULL,
            subtotal DECIMAL(10,2) NOT NULL,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE delivery_locations (
            id BIGSERIAL PRIMARY KEY,
            delivery_person_id UUID NOT NULL REFERENCES delivery_persons(id),
            order_id UUID NOT NULL REFERENCES orders(id),
            location GEOGRAPHY(Point, 4326) NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            speed_kmh DECIMAL(5,1)
        )
    """)

    op.execute("CREATE INDEX idx_restaurants_location ON restaurants USING GIST (location)")
    op.execute("CREATE INDEX idx_delivery_persons_location ON delivery_persons USING GIST (current_location)")
    op.execute("CREATE INDEX idx_delivery_locations_lookup ON delivery_locations (delivery_person_id, recorded_at DESC)")
    op.execute("CREATE INDEX idx_orders_status ON orders (status) WHERE status IN ('pending', 'confirmed', 'preparing', 'in_delivery')")


def downgrade():
    op.execute("DROP TABLE IF EXISTS delivery_locations CASCADE")
    op.execute("DROP TABLE IF EXISTS order_items CASCADE")
    op.execute("DROP TABLE IF EXISTS orders CASCADE")
    op.execute("DROP TYPE IF EXISTS order_status")
    op.execute("DROP TABLE IF EXISTS delivery_persons CASCADE")
    op.execute("DROP TABLE IF EXISTS menu_items CASCADE")
    op.execute("DROP TABLE IF EXISTS menu_categories CASCADE")
    op.execute("DROP TABLE IF EXISTS restaurants CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")
