import json
import math
import re
import unicodedata
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "streets_juventino_rosas.json"

_STREETS: dict[str, list[list[list[float]]]] = {}
_ADDRESSES: dict[str, list[dict]] = {}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(
        r"^(calle|avenida|av\.?|privada|prolongacion|prolongación|boulevard|blvd\.?|camino|calzada|andador|circuito)\s+",
        "",
        text,
    )
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


if DATA_FILE.exists():
    _data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    for item in _data.get("streets", []):
        key = normalize(item.get("name") or "")
        if key:
            _STREETS.setdefault(key, []).append(item.get("points") or [])
    for item in _data.get("addresses", []):
        key = normalize(item.get("street") or "")
        if key:
            _ADDRESSES.setdefault(key, []).append(item)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _nearest_point(points: list[list[float]], lat: float, lng: float):
    best = None
    best_distance = None
    for point in points:
        if not point or len(point) < 2:
            continue
        distance = _haversine_km(lat, lng, float(point[0]), float(point[1]))
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best = point
    return best, best_distance


def find_local_street(street: str, number: str | None, center_lat: float, center_lng: float) -> dict | None:
    key = normalize(street)
    if not key:
        return None

    candidates = _STREETS.get(key)
    if not candidates:
        for name, points in _STREETS.items():
            if key in name or name in key:
                candidates = points
                break
    if not candidates:
        return None

    best_point = None
    best_distance = None
    for points in candidates:
        point, distance = _nearest_point(points, center_lat, center_lng)
        if point is not None and (best_distance is None or distance < best_distance):
            best_point = point
            best_distance = distance

    if best_point is None or best_distance is None or best_distance > 5.0:
        return None

    if number:
        addresses = _ADDRESSES.get(key) or []
        exact = [
            a for a in addresses
            if str(a.get("number", "")).strip().lower() == str(number).strip().lower()
        ]
        if exact:
            best_addr = None
            best_addr_distance = None
            for a in exact:
                distance = _haversine_km(center_lat, center_lng, float(a["lat"]), float(a["lng"]))
                if best_addr_distance is None or distance < best_addr_distance:
                    best_addr_distance = distance
                    best_addr = a
            if best_addr:
                return {
                    "lat": float(best_addr["lat"]),
                    "lng": float(best_addr["lng"]),
                    "display_name": f"{street} {number} (número exacto OSM)",
                    "approximate": False,
                }

    return {
        "lat": float(best_point[0]),
        "lng": float(best_point[1]),
        "display_name": f"{street} (aproximado, a {best_distance:.2f} km del centro del C.P.)",
        "approximate": True,
    }
