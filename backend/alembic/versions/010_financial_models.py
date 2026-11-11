"""financial models, mandados, payouts, cash advances

Revision ID: 010
Revises: 009
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geography

revision = "010"
down_revision = "009"


def _add_col(table: str, col_name: str, col_type: str, default: str | None = None, nullable: bool = True):
    """ALTER TABLE ADD COLUMN IF NOT EXISTS (raw SQL)."""
    parts = [f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{col_name}" {col_type}']
    if default is not None:
        parts[0] += f" DEFAULT {default}"
    if not nullable:
        parts[0] += " NOT NULL"
    op.execute(parts[0])


def upgrade():
    # ── Restaurant ──
    _add_col("restaurants", "commission_percentage", "DECIMAL(4,1)")
    _add_col("restaurants", "payout_frequency_days", "INTEGER", default="7", nullable=False)
    _add_col("restaurants", "bank_name", "VARCHAR(100)")
    _add_col("restaurants", "bank_account_holder", "VARCHAR(150)")
    _add_col("restaurants", "bank_clabe", "VARCHAR(18)")

    # ── DeliveryPerson ──
    _add_col("delivery_persons", "payout_method", "VARCHAR(10)", default="'cash'", nullable=False)
    _add_col("delivery_persons", "payout_frequency_days", "INTEGER", default="3", nullable=False)
    _add_col("delivery_persons", "bank_name", "VARCHAR(100)")
    _add_col("delivery_persons", "bank_account_holder", "VARCHAR(150)")
    _add_col("delivery_persons", "bank_clabe", "VARCHAR(18)")
    _add_col("delivery_persons", "is_mandadero", "BOOLEAN", default="false", nullable=False)
    _add_col("delivery_persons", "pending_platform_debt", "DECIMAL(10,2)", default="0", nullable=False)

    # ── Order ──
    _add_col("orders", "platform_commission", "DECIMAL(10,2)", default="0", nullable=False)
    _add_col("orders", "flat_usage_fee", "DECIMAL(10,2)", default="0", nullable=False)
    _add_col("orders", "delivery_earnings", "DECIMAL(10,2)", default="0", nullable=False)
    _add_col("orders", "delivery_distance_km", "DECIMAL(8,2)")

    # ── Drop orphan tables if any (from partial previous runs) ──
    for t in ("cash_advances", "mandados", "restaurant_payouts", "delivery_payouts"):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")

    # ── DeliveryPayout ──
    op.create_table(
        "delivery_payouts",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("delivery_person_id", sa.Uuid(), sa.ForeignKey("delivery_persons.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("orders_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_earnings", sa.DECIMAL(10, 2), server_default="0", nullable=False),
        sa.Column("payout_method", sa.String(10), nullable=False),
        sa.Column("confirmation_code", sa.String(6), nullable=False),
        sa.Column("status", sa.String(15), server_default="pending", nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── RestaurantPayout ──
    op.create_table(
        "restaurant_payouts",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("restaurant_id", sa.Uuid(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("orders_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_subtotal", sa.DECIMAL(10, 2), server_default="0", nullable=False),
        sa.Column("total_commission", sa.DECIMAL(10, 2), server_default="0", nullable=False),
        sa.Column("total_flat_fees", sa.DECIMAL(10, 2), server_default="0", nullable=False),
        sa.Column("net_payout", sa.DECIMAL(10, 2), server_default="0", nullable=False),
        sa.Column("status", sa.String(15), server_default="pending", nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── Mandado ──
    op.create_table(
        "mandados",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("delivery_person_id", sa.Uuid(), sa.ForeignKey("delivery_persons.id"), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("estimated_budget", sa.DECIMAL(10, 2), nullable=False),
        sa.Column("product_total", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("delivery_fee", sa.DECIMAL(10, 2), server_default="0", nullable=False),
        sa.Column("risk_fee", sa.DECIMAL(10, 2), server_default="0", nullable=False),
        sa.Column("platform_fee", sa.DECIMAL(10, 2), server_default="10", nullable=False),
        sa.Column("estimated_total", sa.DECIMAL(10, 2), nullable=False),
        sa.Column("final_total", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("payment_method", sa.String(10), server_default="cash", nullable=False),
        sa.Column("payment_status", sa.String(15), server_default="pending", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("delivery_address", sa.Text(), nullable=False),
        sa.Column("delivery_location", Geography(geometry_type="POINT", srid=4326), nullable=False),
        sa.Column("receipt_photo_url", sa.Text(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── CashAdvance ──
    op.create_table(
        "cash_advances",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("delivery_person_id", sa.Uuid(), sa.ForeignKey("delivery_persons.id"), nullable=False),
        sa.Column("mandado_id", sa.Uuid(), sa.ForeignKey("mandados.id"), nullable=True),
        sa.Column("amount", sa.DECIMAL(10, 2), nullable=False),
        sa.Column("status", sa.String(15), server_default="taken", nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_table("cash_advances")
    op.drop_table("mandados")
    op.drop_table("restaurant_payouts")
    op.drop_table("delivery_payouts")
    op.drop_column("orders", "delivery_distance_km")
    op.drop_column("orders", "delivery_earnings")
    op.drop_column("orders", "flat_usage_fee")
    op.drop_column("orders", "platform_commission")
    op.drop_column("delivery_persons", "pending_platform_debt")
    op.drop_column("delivery_persons", "is_mandadero")
    op.drop_column("delivery_persons", "bank_clabe")
    op.drop_column("delivery_persons", "bank_account_holder")
    op.drop_column("delivery_persons", "bank_name")
    op.drop_column("delivery_persons", "payout_frequency_days")
    op.drop_column("delivery_persons", "payout_method")
    op.drop_column("restaurants", "bank_clabe")
    op.drop_column("restaurants", "bank_account_holder")
    op.drop_column("restaurants", "bank_name")
    op.drop_column("restaurants", "payout_frequency_days")
    op.drop_column("restaurants", "commission_percentage")
