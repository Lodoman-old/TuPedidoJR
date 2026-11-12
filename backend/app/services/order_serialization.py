"""Serialización de pedidos con datos sensibles protegidos."""
from app.models.order import Order
from app.schemas.order import OrderOut


def order_out(order: Order, *, can_see_refund: bool) -> OrderOut:
    """Devuelve el pedido ocultando la cuenta bancaria a quien no la necesita."""
    data = OrderOut.model_validate(order)
    if not can_see_refund:
        data.refund_account_holder = None
        data.refund_bank = None
        data.refund_clabe = None
    return data
