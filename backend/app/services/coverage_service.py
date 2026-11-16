"""Cobertura de entrega: solo el municipio de Juventino Rosas.

Los polígonos por código postal de Juventino Rosas viven en PostGIS
(``postal_code_areas``) y cubren todo el municipio, incluidas las
comunidades rurales. El chequeo falla abierto: si la tabla no tiene
datos o PostGIS responde con error, no se bloquea la venta.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.order_service import get_setting_value

OUT_OF_COVERAGE_MESSAGE = (
    "La dirección está fuera de nuestra zona de entrega: por ahora solo "
    "entregamos dentro de Juventino Rosas. Si quieres, puedes recoger tu "
    "pedido en el negocio."
)


async def coverage_enabled(db: AsyncSession) -> bool:
    raw = await get_setting_value(db, "COVERAGE_ENFORCE", "true")
    return str(raw).strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


async def _margin_meters(db: AsyncSession) -> float:
    raw = await get_setting_value(db, "COVERAGE_MARGIN_M", "500")
    try:
        margin = float(raw)
    except (TypeError, ValueError):
        margin = 500.0
    return min(max(margin, 0.0), 5000.0)


async def is_inside_coverage(
    db: AsyncSession,
    lat: float | None,
    lng: float | None,
) -> bool | None:
    """True dentro del municipio, False fuera, None si no se pudo verificar."""
    if lat is None or lng is None:
        return None
    try:
        margin = await _margin_meters(db)
        result = await db.execute(
            text(
                """
                SELECT
                    EXISTS (SELECT 1 FROM postal_code_areas) AS has_areas,
                    EXISTS (
                        SELECT 1 FROM postal_code_areas
                        WHERE ST_Intersects(
                            geom,
                            ST_Buffer(
                                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                                :margin
                            )::geometry
                        )
                    ) AS inside
                """
            ),
            {"lat": float(lat), "lng": float(lng), "margin": margin},
        )
        row = result.mappings().first()
        if not row or not row["has_areas"]:
            return None
        return bool(row["inside"])
    except Exception:
        return None


async def ensure_coverage(
    db: AsyncSession,
    lat: float | None,
    lng: float | None,
) -> None:
    """Lanza 400 si el punto de entrega está fuera del municipio."""
    if not await coverage_enabled(db):
        return
    inside = await is_inside_coverage(db, lat, lng)
    if inside is False:
        raise HTTPException(status_code=400, detail=OUT_OF_COVERAGE_MESSAGE)
