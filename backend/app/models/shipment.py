import secrets

from sqlalchemy import Boolean, Column, DateTime, DECIMAL, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geography

from app.db.base import Base, TimestampMixin


class Shipment(TimestampMixin, Base):
    """Envío de un negocio a un cliente que no necesita cuenta.

    El negocio ya cerró la venta por su propio canal (WhatsApp, Facebook o
    teléfono) y usa la red de repartidores solo para entregar el paquete.
    """

    __tablename__ = "shipments"

    store_id = Column(
        UUID(as_uuid=True), ForeignKey("restaurants.id"), nullable=False, index=True
    )
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    delivery_person_id = Column(
        UUID(as_uuid=True), ForeignKey("delivery_persons.id"), nullable=True, index=True
    )

    status = Column(String(20), default="pending", nullable=False, index=True)
    recipient_name = Column(String(150), nullable=False)
    recipient_phone = Column(String(20), nullable=False)
    delivery_address = Column(Text, nullable=False)
    delivery_location = Column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    delivery_references = Column(Text, nullable=True)

    package_description = Column(Text, nullable=False)
    declared_value = Column(DECIMAL(10, 2), default=0, nullable=False)
    collect_amount = Column(DECIMAL(10, 2), default=0, nullable=False)
    amount_to_collect = Column(DECIMAL(10, 2), default=0, nullable=False)
    shipping_paid_by = Column(String(10), default="store", nullable=False)

    delivery_fee = Column(DECIMAL(10, 2), default=0, nullable=False)
    platform_fee = Column(DECIMAL(10, 2), default=10, nullable=False)
    distance_km = Column(DECIMAL(8, 2), nullable=True)
    tip_amount = Column(DECIMAL(10, 2), default=0, nullable=False)

    store_charge = Column(DECIMAL(10, 2), default=0, nullable=False)
    store_credit = Column(DECIMAL(10, 2), default=0, nullable=False)
    store_charge_settled = Column(Boolean, default=False, nullable=False)
    store_credit_settled = Column(Boolean, default=False, nullable=False)
    courier_earnings = Column(DECIMAL(10, 2), default=0, nullable=False)
    courier_settled = Column(Boolean, default=False, nullable=False)

    cash_collected = Column(DECIMAL(10, 2), default=0, nullable=False)
    cash_remitted = Column(Boolean, default=False, nullable=False)
    payment_status = Column(String(20), default="pending", nullable=False)
    cod_status = Column(String(20), default="not_required", nullable=False)

    pickup_code = Column(String(6), nullable=True)
    delivery_code = Column(String(4), nullable=True)
    public_token = Column(
        String(64), unique=True, nullable=False, index=True,
        default=lambda: secrets.token_urlsafe(24),
    )

    pickup_photo_url = Column(Text, nullable=True)
    delivery_photo_url = Column(Text, nullable=True)

    accepted_at = Column(DateTime(timezone=True), nullable=True)
    picked_up_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    cancellation_reason = Column(Text, nullable=True)
    failure_reason = Column(Text, nullable=True)
    return_fee = Column(DECIMAL(10, 2), default=0, nullable=False)
