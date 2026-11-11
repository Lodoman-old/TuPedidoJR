from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends

from app.api.deps import get_current_user
from app.models.user import User
from app.ws.manager import ConnectionManager

router = APIRouter()


def get_ws_manager() -> ConnectionManager:
    from app.main import ws_manager
    return ws_manager


@router.websocket("/delivery/{order_id}/location")
async def delivery_location_ws(
    websocket: WebSocket,
    order_id: str,
    manager: ConnectionManager = Depends(get_ws_manager),
):
    await websocket.accept()

    try:
        auth_data = await websocket.receive_json()
        token = auth_data.get("token")
        if not token:
            await websocket.close(code=4001, reason="Token requerido")
            return

        from app.core.security import decode_access_token
        payload = decode_access_token(token)
        if not payload:
            await websocket.close(code=4001, reason="Token inválido")
            return

        delivery_person_id = payload["sub"]
    except Exception:
        await websocket.close(code=4001, reason="Autenticación fallida")
        return

    await manager.connect_delivery(delivery_person_id, order_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "location":
                await manager.handle_delivery_location(
                    delivery_person_id, order_id, data
                )
    except WebSocketDisconnect:
        manager.disconnect_delivery(delivery_person_id, order_id)
    except Exception as e:
        manager.disconnect_delivery(delivery_person_id, order_id)
