from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from app.core.security import decode_access_token
from app.db.session import async_session
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.tracking_service import build_tracking
from app.ws.manager import ConnectionManager

router = APIRouter()


def get_ws_manager() -> ConnectionManager:
    from app.main import ws_manager
    return ws_manager


async def _can_track(order: Order, user: User) -> bool:
    if user.is_superuser or str(order.user_id) == str(user.id):
        return True
    async with async_session() as db:
        resto = await db.execute(select(Restaurant).where(Restaurant.id == order.restaurant_id))
        restaurant = resto.scalar_one_or_none()
        if restaurant and str(restaurant.owner_id) == str(user.id):
            return True
        dp_result = await db.execute(
            select(DeliveryPerson).where(DeliveryPerson.user_id == user.id)
        )
        dp = dp_result.scalar_one_or_none()
        return bool(dp and order.delivery_person_id and str(order.delivery_person_id) == str(dp.id))


@router.websocket("/orders/{order_id}/track")
async def order_track_ws(
    websocket: WebSocket,
    order_id: str,
    token: str | None = Query(None),
    manager: ConnectionManager = Depends(get_ws_manager),
):
    if not token:
        await websocket.close(code=4001, reason="Token requerido")
        return

    payload = decode_access_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Token inválido")
        return

    async with async_session() as db:
        user_result = await db.execute(select(User).where(User.id == payload["sub"]))
        user = user_result.scalar_one_or_none()
        order_result = await db.execute(select(Order).where(Order.id == order_id))
        order = order_result.scalar_one_or_none()

        if not user or not order:
            await websocket.close(code=4004, reason="Pedido no encontrado")
            return
        if not await _can_track(order, user):
            await websocket.close(code=4003, reason="Sin acceso a este pedido")
            return

        state = await build_tracking(db, order)

    await manager.connect_customer(order_id, websocket)
    await websocket.send_json(jsonable_encoder({"type": "tracking_state", **state}))

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect_customer(order_id, websocket)
    except Exception:
        manager.disconnect_customer(order_id, websocket)
