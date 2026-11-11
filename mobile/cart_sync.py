"""Keep the mobile cart in sync with the server snapshot."""
from mobile.api import api


async def hydrate_cart(target: list) -> bool:
    if not getattr(api, "token", None):
        return False
    try:
        data = await api.get_cart_snapshot()
    except Exception:
        return False
    items = data.get("items") or []
    if items:
        target.clear()
        target.extend(items)
        return True
    return False


async def sync_cart(items: list):
    if not getattr(api, "token", None):
        return
    restaurant_id = next(
        (item.get("restaurant_id") for item in items if item.get("restaurant_id")),
        None,
    )
    try:
        await api.save_cart_snapshot(items, restaurant_id)
    except Exception:
        pass
