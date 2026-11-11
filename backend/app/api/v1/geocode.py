import json
import unicodedata
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.geocode_service import geocode_address, geocode_structured, reverse_geocode

router = APIRouter()

COLONIAS_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "colonias_juventino_rosas.json"
_COLONIAS = {}
if COLONIAS_FILE.exists():
    _COLONIAS = json.loads(COLONIAS_FILE.read_text(encoding="utf-8"))


class GeocodeRequest(BaseModel):
    address: str = Field(..., min_length=3)
    postal_code: str | None = None
    city: str | None = "Santa Cruz de Juventino Rosas"
    state: str | None = "Guanajuato"


class GeocodeStructuredRequest(BaseModel):
    street: str = Field(..., min_length=3)
    colonia: str = Field(..., min_length=2)
    postal_code: str = Field(..., min_length=4, max_length=6)
    city: str = "Santa Cruz de Juventino Rosas"
    state: str = "Guanajuato"


class GeocodeResult(BaseModel):
    lat: float
    lng: float
    display_name: str
    road: str = ""
    suburb: str = ""
    city: str = ""
    state: str = ""
    postcode: str = ""


class ReverseGeocodeResult(BaseModel):
    lat: float
    lng: float
    display_name: str
    road: str = ""
    house_number: str = ""
    suburb: str = ""
    neighbourhood: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    postcode: str = ""


@router.get("/ip")
async def geocode_ip():
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("http://ip-api.com/json/?fields=status,lat,lon,city,regionName,country,query")
            data = r.json()
            if data.get("status") == "success":
                return {"lat": data["lat"], "lng": data["lon"], "city": data.get("city"), "region": data.get("regionName"), "country": data.get("country"), "ip": data.get("query")}
            return {"lat": 20.644, "lng": -100.993, "city": "Santa Cruz de Juventino Rosas", "region": "Guanajuato", "country": "México"}
    except Exception:
        return {"lat": 20.644, "lng": -100.993, "city": "Santa Cruz de Juventino Rosas", "region": "Guanajuato", "country": "México"}


@router.get("/postal-code/{cp}")
async def postal_code(cp: str):
    data = await _postal_code_payload(cp)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="Código postal no encontrado en Santa Cruz de Juventino Rosas",
        )
    return data


@router.get("/postal-code-reverse")
async def reverse_postal_code(
    lat: float = Query(...),
    lng: float = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """PostGIS point-in-polygon lookup for C.P., colonia and AGEB."""
    context = await _location_context(db, lat, lng)
    if not context:
        raise HTTPException(
            status_code=404,
            detail="No se encontró un código postal para esa ubicación",
        )
    cp = context.get("cp")
    data = await _postal_code_payload(str(cp)) if cp else None
    return {
        **(data or {"cp": cp, "colonias": [], "lat": lat, "lng": lng}),
        **context,
        "source": "postgis",
    }


@router.get("/location-context")
async def location_context(
    lat: float = Query(...),
    lng: float = Query(...),
    db: AsyncSession = Depends(get_db),
):
    context = await _location_context(db, lat, lng)
    if not context:
        raise HTTPException(status_code=404, detail="Ubicación fuera de Juventino Rosas")
    cp = context.get("cp")
    data = await _postal_code_payload(str(cp)) if cp else None
    return {
        **(data or {"cp": cp, "colonias": [], "lat": lat, "lng": lng}),
        **context,
        "source": "postgis",
    }


async def _location_context(db: AsyncSession, lat: float, lng: float) -> dict | None:
    try:
        cp_result = await db.execute(
            text("""
                SELECT cp FROM postal_code_areas
                WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
                ORDER BY ST_Area(geom) ASC LIMIT 1
            """),
            {"lat": lat, "lng": lng},
        )
        cp = cp_result.scalar_one_or_none()
        colonia_result = await db.execute(
            text("""
                SELECT nombre, cp FROM colonia_areas
                WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
                ORDER BY ST_Area(geom) ASC LIMIT 1
            """),
            {"lat": lat, "lng": lng},
        )
        colonia = colonia_result.mappings().first()
        ageb_result = await db.execute(
            text("""
                SELECT cvegeo, cve_ageb, ambito FROM ageb_areas
                WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
                ORDER BY ST_Area(geom) ASC LIMIT 1
            """),
            {"lat": lat, "lng": lng},
        )
        ageb = ageb_result.mappings().first()
    except Exception:
        return None
    if not cp and not colonia and not ageb:
        return None
    return {
        "cp": str(cp) if cp else (str(colonia["cp"]) if colonia and colonia["cp"] else None),
        "colonia": colonia["nombre"] if colonia else None,
        "ageb": ageb["cve_ageb"] if ageb else None,
        "ageb_cvegeo": ageb["cvegeo"] if ageb else None,
        "ambito": ageb["ambito"] if ageb else None,
        "lat": lat,
        "lng": lng,
    }


async def _postal_code_payload(cp: str) -> dict | None:
    cp = cp.strip()
    if not (len(cp) == 5 and cp.isdigit()):
        return None

    # Same SEPOMEX-backed service used by Colmena (cp.terio.dev).
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            response = await client.get(f"https://cp.terio.dev/v1/codigos-postales/{cp}")
        if response.status_code == 200:
            payload = response.json()
            rows = payload.get("datos") or []
            rows = [
                row for row in rows
                if "juventino rosas" in _normalize_text(
                    f"{row.get('municipio', '')} {row.get('ciudad', '')}"
                )
            ]
            if rows:
                colonias = []
                seen = set()
                for row in rows:
                    name = (row.get("asentamiento") or "").strip()
                    if name and name not in seen:
                        seen.add(name)
                        colonias.append({
                            "nombre": name,
                            "tipo": row.get("tipo_asentamiento") or "Colonia",
                        })
                first = rows[0]
                lat = first.get("lat")
                lng = first.get("lng")
                return {
                    "cp": cp,
                    "municipio": first.get("municipio") or "Santa Cruz de Juventino Rosas",
                    "estado": first.get("estado") or "Guanajuato",
                    "ciudad": first.get("ciudad") or "Santa Cruz de Juventino Rosas",
                    "colonias": colonias,
                    "lat": float(lat) if lat is not None else None,
                    "lng": float(lng) if lng is not None else None,
                    "centro_fuente": "cp.terio.dev",
                }
    except Exception:
        pass

    return _COLONIAS.get(cp)


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    return " ".join(text.lower().split())


@router.post("", response_model=list[GeocodeResult])
async def geocode(body: GeocodeRequest):
    results = await geocode_address(
        body.address,
        postalcode=body.postal_code,
        city=body.city,
        state=body.state,
    )
    if not results:
        raise HTTPException(status_code=404, detail="No se encontraron resultados para esa dirección")
    return results


@router.post("/structured", response_model=list[GeocodeResult])
async def geocode_with_colonia(body: GeocodeStructuredRequest):
    """Dirección (calle + colonia + CP) -> coordenadas, sin fijar el mapa."""
    results = await geocode_structured(
        street=body.street,
        colonia=body.colonia,
        postalcode=body.postal_code,
        city=body.city,
        state=body.state,
    )
    if not results:
        raise HTTPException(
            status_code=404,
            detail="No se encontró la dirección. Revisa calle, colonia y código postal.",
        )
    return results


@router.get("/reverse", response_model=ReverseGeocodeResult)
async def geocode_reverse(lat: float = Query(...), lng: float = Query(...)):
    result = await reverse_geocode(lat, lng)
    if not result:
        raise HTTPException(status_code=404, detail="No se encontró dirección para esas coordenadas")
    return result
