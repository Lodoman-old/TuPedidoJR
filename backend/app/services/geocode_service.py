import hashlib
import json
import time
from pathlib import Path

import httpx

from app.services.street_service import find_local_street

_CP_FILE = Path(__file__).resolve().parent.parent / "data" / "colonias_juventino_rosas.json"
_CP_DATA = json.loads(_CP_FILE.read_text(encoding="utf-8")) if _CP_FILE.exists() else {}

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {"User-Agent": "TuPedidoJR/1.0 (delivery app; contacto@tupedidojr.app)"}

# Simple in-memory cache to respect Nominatim's fair-use policy.
_CACHE: dict[str, tuple[float, object]] = {}
_CACHE_TTL_SECONDS = 3600


def _cache_get(key: str):
    item = _CACHE.get(key)
    if not item:
        return None
    expires_at, value = item
    if expires_at < time.time():
        _CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value):
    _CACHE[key] = (time.time() + _CACHE_TTL_SECONDS, value)
    if len(_CACHE) > 500:
        # Drop the oldest entries.
        for old_key, _ in sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:100]:
            _CACHE.pop(old_key, None)


def _result(item: dict) -> dict:
    address = item.get("address", {}) or {}
    return {
        "lat": float(item["lat"]),
        "lng": float(item["lon"]),
        "display_name": item.get("display_name", ""),
        "road": address.get("road", ""),
        "suburb": address.get("suburb", address.get("neighbourhood", "")),
        "city": address.get("city", address.get("town", address.get("village", ""))),
        "state": address.get("state", ""),
        "postcode": address.get("postcode", ""),
    }


async def _search(params: dict) -> list[dict]:
    key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    cached = _cache_get(key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    async with httpx.AsyncClient() as client:
        r = await client.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        results = [_result(item) for item in r.json()]
    _cache_set(key, results)
    return results


async def _search_query(
    query: str,
    limit: int = 5,
    countrycodes: str = "mx",
    bounded: bool = True,
) -> list[dict]:
    params = {
        "q": query,
        "format": "json",
        "addressdetails": 1,
        "limit": limit,
        "countrycodes": countrycodes,
        "accept-language": "es",
    }
    if bounded:
        # Rough bounding box around Santa Cruz de Juventino Rosas, Gto.
        params["viewbox"] = "-101.10,20.55,-100.88,20.74"
        params["bounded"] = 1
    return await _search(params)


async def geocode_address(
    address: str,
    limit: int = 5,
    postalcode: str | None = None,
    city: str | None = None,
    state: str | None = None,
    country: str = "México",
    countrycodes: str = "mx",
    bounded: bool = True,
) -> list[dict]:
    parts = [address, city, state, postalcode, country]
    query = ", ".join(part.strip() for part in parts if part and part.strip())
    return await _search_query(query, limit=limit, countrycodes=countrycodes, bounded=bounded)


def _normalize(text: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower().strip()


def _cp_center(cp: str) -> tuple[float, float] | None:
    entry = _CP_DATA.get(cp)
    if not entry or entry.get("lat") is None or entry.get("lng") is None:
        return None
    return float(entry["lat"]), float(entry["lng"])


async def geocode_structured(
    street: str,
    colonia: str,
    postalcode: str,
    city: str = "Santa Cruz de Juventino Rosas",
    state: str = "Guanajuato",
    country: str = "México",
) -> list[dict]:
    """Geocode a Mexican address without requiring a map pin."""
    import re

    # "Calle 5 de Mayo 209" -> street_name "Calle 5 de Mayo", number "209".
    # Trying both variants helps when OSM does not have house numbers.
    match = re.match(r"^(.*?)(?:\s+(\d+[A-Za-z]?))?$", street.strip())
    street_name = (match.group(1) or street).strip() if match else street.strip()
    number = match.group(2) if match else None

    variants = [
        [street, colonia, city, state, postalcode, country],
        [street_name, colonia, city, state, postalcode, country],
        [street_name, city, state, postalcode, country],
    ]
    results: list[dict] = []
    seen: set[tuple] = set()
    for parts in variants:
        query = ", ".join(part.strip() for part in parts if part and part.strip())
        for item in await _search_query(query):
            key = (round(item["lat"], 6), round(item["lng"], 6))
            if key not in seen:
                seen.add(key)
                results.append(item)
        if any((r.get("postcode") or "") == postalcode for r in results):
            break

    # If Nominatim has no result inside the requested CP, use the local OSM
    # street index built for Juventino Rosas. It finds the street by name and
    # snaps it to the point nearest the CP center.
    if not any((r.get("postcode") or "") == postalcode for r in results):
        center = _cp_center(postalcode)
        if center:
            local = find_local_street(street_name, number, center[0], center[1])
            if local:
                results.append({
                    "lat": local["lat"],
                    "lng": local["lng"],
                    "display_name": local["display_name"],
                    "road": street_name,
                    "suburb": colonia,
                    "city": city,
                    "state": state,
                    "postcode": postalcode,
                    "source": "local_street",
                    "approximate": local.get("approximate", True),
                })

    if not results:
        return results

    colonia_norm = _normalize(colonia)

    def score(item: dict) -> tuple:
        return (
            0 if (item.get("postcode") or "") == postalcode else 1,
            0 if colonia_norm and colonia_norm in _normalize(item.get("display_name", "")) else 1,
        )

    return sorted(results, key=score)


async def reverse_geocode(lat: float, lng: float) -> dict | None:
    params = {
        "lat": lat,
        "lon": lng,
        "format": "json",
        "addressdetails": 1,
        "zoom": 18,
        "accept-language": "es",
    }
    key = "reverse:" + hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    cached = _cache_get(key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    async with httpx.AsyncClient() as client:
        r = await client.get(REVERSE_URL, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
    if not data or data.get("error"):
        return None
    address = data.get("address", {}) or {}
    result = {
        "lat": float(data["lat"]),
        "lng": float(data["lon"]),
        "display_name": data.get("display_name", ""),
        "road": address.get("road", ""),
        "house_number": address.get("house_number", ""),
        "suburb": address.get("suburb", address.get("neighbourhood", "")),
        "neighbourhood": address.get("neighbourhood", ""),
        "city": address.get("city", address.get("town", address.get("village", ""))),
        "state": address.get("state", ""),
        "country": address.get("country", ""),
        "postcode": address.get("postcode", ""),
    }
    _cache_set(key, result)
    return result
