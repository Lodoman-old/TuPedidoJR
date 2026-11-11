"""Helpers to decide when money is actually available for settlement."""

ONLINE_METHODS = {"transfer", "mp"}
COLLECTED_STATUSES = {"approved", "paid"}


def is_order_settleable(order) -> bool:
    """Whether the platform already holds the money for this order.

    Cash orders are collected by the courier, so they are settleable as soon
    as they are delivered. Transfers and online payments only become
    settleable when the platform confirms the payment.
    """
    if order.payment_method in ONLINE_METHODS:
        return order.payment_status in COLLECTED_STATUSES
    return True
