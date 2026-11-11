import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import WebSocket
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self, async_session_factory: async_sessionmaker):
        self.async_session_factory = async_session_factory
        self.delivery_connections: dict[str, WebSocket] = {}  # delivery_person_id -> ws
        self.customer_connections: dict[str, set[WebSocket]] = defaultdict(set)  # order_id -> {ws}
        self.location_buffer: dict[str, list[dict]] = defaultdict(list)
        self._persist_task: asyncio.Task | None = None

    async def connect_delivery(self, delivery_person_id: str, order_id: str, ws: WebSocket):
        await ws.accept()
        self.delivery_connections[delivery_person_id] = ws
        logger.info("Delivery %s connected for order %s", delivery_person_id, order_id)

    async def connect_customer(self, order_id: str, ws: WebSocket):
        await ws.accept()
        self.customer_connections[order_id].add(ws)
        logger.info("Customer connected for order %s", order_id)

    def disconnect_delivery(self, delivery_person_id: str, order_id: str):
        self.delivery_connections.pop(delivery_person_id, None)
        self._flush_buffer(delivery_person_id)
        logger.info("Delivery %s disconnected", delivery_person_id)

    def disconnect_customer(self, order_id: str, ws: WebSocket):
        self.customer_connections[order_id].discard(ws)
        if not self.customer_connections[order_id]:
            del self.customer_connections[order_id]

    async def notify_order_status(self, order_id: str, new_status: str):
        await self._broadcast_to_customers(order_id, {
            "type": "status_update",
            "status": new_status,
        })

    async def handle_delivery_location(self, delivery_person_id: str, order_id: str, data: dict):
        point = {
            "delivery_person_id": delivery_person_id,
            "order_id": order_id,
            "lat": data["lat"],
            "lng": data["lng"],
            "speed_kmh": data.get("speed_kmh"),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.location_buffer[delivery_person_id].append(point)
        await self._broadcast_to_customers(order_id, {
            "type": "location_update",
            "lat": data["lat"],
            "lng": data["lng"],
            "speed_kmh": data.get("speed_kmh"),
            "recorded_at": point["recorded_at"],
        })

        if len(self.location_buffer[delivery_person_id]) >= 50:
            await self._flush_buffer(delivery_person_id)

    async def _broadcast_to_customers(self, order_id: str, message: dict):
        connections = self.customer_connections.get(order_id, set())
        stale = set()
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                stale.add(ws)
        for ws in stale:
            connections.discard(ws)

    async def _flush_buffer(self, delivery_person_id: str | None = None):
        if delivery_person_id:
            ids = [delivery_person_id]
        else:
            ids = list(self.location_buffer.keys())

        for dp_id in ids:
            points = self.location_buffer.pop(dp_id, [])
            if not points:
                continue

            try:
                async with self.async_session_factory() as session:
                    await self._persist_batch(session, points)
            except Exception as e:
                logger.error("Failed to persist locations for %s: %s", dp_id, e)

    async def _persist_batch(self, db: AsyncSession, points: list[dict]):
        values = []
        for p in points:
            values.append(
                f"('{p['delivery_person_id']}', '{p['order_id']}', "
                f"ST_SetSRID(ST_MakePoint({p['lng']}, {p['lat']}), 4326), "
                f"'{p['recorded_at']}'::timestamptz, {p['speed_kmh'] or 'NULL'})"
            )

        await db.execute(text(f"""
            INSERT INTO delivery_locations (delivery_person_id, order_id, location, recorded_at, speed_kmh)
            VALUES {', '.join(values)}
        """))

        last = points[-1]
        await db.execute(text(f"""
            UPDATE delivery_persons
            SET current_location = ST_SetSRID(ST_MakePoint({last['lng']}, {last['lat']}), 4326)
            WHERE id = '{last['delivery_person_id']}'
        """))
        await db.commit()

    async def start_persist_background_task(self):
        async def _loop():
            while True:
                await asyncio.sleep(30)
                await self._flush_buffer()

        self._persist_task = asyncio.create_task(_loop())

    async def stop(self):
        if self._persist_task:
            self._persist_task.cancel()
        await self._flush_buffer()
