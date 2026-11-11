"""Smoke check for a running TuPedidoJR backend.

Usage (inside the backend container or with the same env):

    python -m scripts.smoke
    python -m scripts.smoke http://192.168.1.20:8080

Exits with code 1 if any check fails.
"""
import asyncio
import sys

import httpx
from sqlalchemy import text

from app.db.session import async_session


async def check(name: str, fn) -> bool:
    try:
        detail = await fn()
        print(f"[OK]   {name}" + (f" — {detail}" if detail else ""))
        return True
    except Exception as exc:
        print(f"[FAIL] {name} — {exc}")
        return False


async def main(base: str) -> int:
    results = []

    async with httpx.AsyncClient(base_url=base, timeout=15) as client:
        async def health():
            response = await client.get("/health")
            response.raise_for_status()
            return response.json().get("status")

        async def payments():
            response = await client.get("/api/v1/payments/config")
            response.raise_for_status()
            data = response.json()
            if not data.get("cash_enabled"):
                raise RuntimeError("cash_enabled es false")
            return "solo efectivo activo"

        restaurants = []

        async def list_restaurants():
            response = await client.get("/api/v1/restaurants", params={"limit": 100})
            response.raise_for_status()
            restaurants.extend(response.json())
            return f"{len(restaurants)} restaurantes"

        async def open_status():
            if not restaurants:
                raise RuntimeError("no hay restaurantes para probar")
            response = await client.get(f"/api/v1/restaurants/{restaurants[0]['id']}/open-status")
            response.raise_for_status()
            data = response.json()
            return data["message"]

        async def geocode():
            response = await client.post("/api/v1/geocode/structured", json={
                "street": "Calle 5 de Mayo 209",
                "colonia": "Santa Cruz de Juventino Rosas Centro",
                "postal_code": "38240",
            })
            response.raise_for_status()
            data = response.json()
            if not data:
                raise RuntimeError("sin resultados")
            return f"{data[0]['lat']}, {data[0]['lng']}"

        results.append(await check("Salud del backend", health))
        results.append(await check("Métodos de pago", payments))
        results.append(await check("Listado de restaurantes", list_restaurants))
        results.append(await check("Estado de apertura", open_status))
        results.append(await check("Geocodificación", geocode))

    async def osrm():
        async with async_session() as db:
            result = await db.execute(
                text("SELECT value FROM settings WHERE key = 'OSRM_URL'")
            )
            url = result.scalar_one_or_none()
        if not url:
            raise RuntimeError("OSRM_URL no configurado")
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{url.rstrip('/')}/route/v1/driving/"
                "-100.9751224,20.6332543;-100.9945089,20.6472232",
                params={"overview": "false"},
            )
            response.raise_for_status()
            route = response.json()["routes"][0]
            return f"{route['distance'] / 1000:.2f} km"

    results.append(await check("Ruta OSRM", osrm))

    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} verificaciones correctas")
    return 1 if failed else 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    raise SystemExit(asyncio.run(main(target)))
