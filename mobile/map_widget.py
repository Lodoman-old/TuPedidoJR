import math
import flet as ft
from mobile.config import get_server_url


def map_url(lat: float, lng: float, zoom: int = 14, size: int = 280) -> str:
    return f"{get_server_url()}/api/v1/map/static?lat={lat}&lng={lng}&zoom={zoom}&width={size}&height={size}"


def map_image(lat: float, lng: float, zoom: int = 14, size: int = 280):
    url = map_url(lat, lng, zoom, size)
    img = ft.Image(src=url, width=size, height=size, fit="fill")
    container = ft.Container(
        content=img, width=size, height=size,
        border_radius=10, clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )
    return container, img, None


def update_map(img, _marker, lat: float, lng: float, zoom: int = 14, size: int = 280):
    img.src = map_url(lat, lng, zoom, size)
