from enum import StrEnum


class OrderStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    AWAITING_COURIER = "awaiting_courier"
    PREPARING = "preparing"
    READY = "ready"
    IN_DELIVERY = "in_delivery"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class VehicleType(StrEnum):
    BIKE = "bike"
    MOTORCYCLE = "motorcycle"
    CAR = "car"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    IN_PROCESS = "in_process"
    REJECTED = "rejected"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class MandadoStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    BUYING = "buying"
    PURCHASED = "purchased"
    IN_DELIVERY = "in_delivery"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MandadoPaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"


class PayoutStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
