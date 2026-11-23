"""Serialización de pedidos con datos sensibles protegidos."""
from app.models.order import Order
from app.schemas.order import OrderOut


def order_out(
    order: Order,
    *,
    can_see_refund: bool,
    customer_phone: str | None = None,
) -> OrderOut:
    """Devuelve el pedido ocultando la cuenta bancaria a quien no la necesita.

    El teléfono del cliente solo se pasa cuando quien consulta lo necesita para
    entregar o atender el pedido (negocio asignado, repartidor o admin).
    """
    data = OrderOut.model_validate(order)
    data.customer_phone = customer_phone
    if not can_see_refund:
        data.refund_account_holder = None
        data.refund_bank = None
        data.refund_clabe = None
    return data
