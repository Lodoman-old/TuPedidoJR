import math

TILE_SIZE = 256
ZOOM = 15


def lat_lng_to_tile(lat: float, lng: float, zoom: int = ZOOM):
    n = 1 << zoom
    x_tile = int(math.floor((lng + 180.0) / 360.0 * n))
    lat_rad = math.radians(lat)
    y_tile = int(math.floor((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n))
    max_tile = n - 1
    x_tile = max(0, min(x_tile, max_tile))
    y_tile = max(0, min(y_tile, max_tile))
    return x_tile, y_tile


def tile_center_lng(x_tile: int, zoom: int = ZOOM) -> float:
    n = 1 << zoom
    return x_tile / n * 360.0 - 180.0 + 180.0 / n


def marker_offset(lat: float, lng: float, x_tile: int, y_tile: int, zoom: int = ZOOM) -> tuple[float, float]:
    n = 1 << zoom
    tile_lng_origin = x_tile / n * 360.0 - 180.0
    px = (lng - tile_lng_origin) / (360.0 / n) * TILE_SIZE
    lat_rad = math.radians(lat)
    tile_lat_origin_norm = y_tile / n  # normalized y
    point_norm = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0
    py = (point_norm - tile_lat_origin_norm) * n * TILE_SIZE
    return px, py


def osm_tile_url(x_tile: int, y_tile: int, zoom: int = ZOOM) -> str:
    # ArcGIS World Street Map (same free tiles used in Colmena).
    return (
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        f"World_Street_Map/MapServer/tile/{zoom}/{y_tile}/{x_tile}"
    )


def carto_tile_url(x_tile: int, y_tile: int, zoom: int = ZOOM) -> str:
    subdomain = "abc"[(x_tile + y_tile) % 3]
    return f"https://tile-{subdomain}.openstreetmap.fr/hot/{zoom}/{x_tile}/{y_tile}.png"


MARKER_HTML = """
<div style="width:24px;height:24px;position:absolute;top:-12px;left:-12px;">
  <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" fill="#e53935" stroke="white" stroke-width="2"/>
    <circle cx="12" cy="9" r="3" fill="white"/>
  </svg>
</div>
"""
