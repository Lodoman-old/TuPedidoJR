"""Ubicación y dirección homologadas para todas las pantallas móviles."""

import re

from mobile.api import api, ApiError
from mobile.config import get_device_location

FALLBACK_LAT = 20.644
FALLBACK_LNG = -100.993


async def current_position() -> dict:
    """Devuelve la ubicación del dispositivo; si no hay GPS, usa la IP."""
    device = get_device_location()
    if device and device.get("lat") is not None and device.get("lng") is not None:
        return {
            "lat": float(device["lat"]),
            "lng": float(device["lng"]),
            "source": "GPS del dispositivo",
        }
    try:
        geo = await api.geocode_ip()
        return {
            "lat": float(geo.get("lat") or FALLBACK_LAT),
            "lng": float(geo.get("lng") or FALLBACK_LNG),
            "source": "ubicación aproximada por IP",
        }
    except ApiError:
        return {"lat": FALLBACK_LAT, "lng": FALLBACK_LNG, "source": "ubicación aproximada"}


def _clean_cp(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[:5] if len(digits) >= 5 else ""


def pick_colonia(names: list, selected: str) -> str:
    """Elige la colonia oficial aunque el reverso devuelva un alias."""
    options = [name for name in (names or []) if name]
    wanted = str(selected or "").strip()
    if not wanted:
        return options[0] if len(options) == 1 else ""
    target = wanted.lower()
    for name in options:
        if name.lower() == target:
            return name
    for name in options:
        current = name.lower()
        if target in current or current in target:
            return name
    if len(options) == 1:
        return options[0]
    return wanted


async def reverse_address(lat: float, lng: float) -> dict:
    """Obtiene C.P., colonia y calle a partir de coordenadas."""
    cp = ""
    colonia = ""
    street = ""
    try:
        local = await api.reverse_postal_code(lat, lng)
        cp = _clean_cp(local.get("cp"))
        colonia = (local.get("colonia") or "").strip()
    except ApiError:
        pass
    try:
        rev = await api.reverse_geocode(lat, lng)
        street = " ".join(
            part for part in [rev.get("road") or "", rev.get("house_number") or ""]
            if part
        ).strip()
        if not cp:
            cp = _clean_cp(rev.get("postcode"))
        if not colonia:
            colonia = (rev.get("suburb") or rev.get("neighbourhood") or "").strip()
    except ApiError:
        pass
    return {"cp": cp, "colonia": colonia, "street": street}


def compose_address(street: str = "", colonia: str = "", cp: str = "") -> str:
    parts = []
    if street:
        parts.append(street.strip())
    if colonia:
        parts.append(colonia.strip())
    if cp:
        parts.append(f"C.P. {cp}")
    return ", ".join(parts)


async def locate_and_fill(force_device: bool = False) -> dict:
    """Ubica y devuelve coords + dirección lista para llenar formularios."""
    position = await current_position()
    found = await reverse_address(position["lat"], position["lng"])
    found.update(position)
    found["address"] = compose_address(found["street"], found["colonia"], found["cp"])
    return found
