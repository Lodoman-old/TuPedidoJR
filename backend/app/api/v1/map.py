from io import BytesIO
from fastapi import APIRouter, Query
from fastapi.responses import Response
from PIL import ImageDraw
from staticmap import StaticMap, CircleMarker

router = APIRouter()


@router.get("/static")
async def static_map(
    lat: float = Query(...),
    lng: float = Query(...),
    zoom: int = Query(14, ge=1, le=19),
    width: int = Query(280, ge=100, le=1000),
    height: int = Query(280, ge=100, le=1000),
):
    m = StaticMap(
        width, height,
        url_template="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        headers={"User-Agent": "TuPedidoJR/1.0 (delivery app)"},
    )
    # StaticMap uses (lon, lat) order
    m.add_marker(CircleMarker((lng, lat), "red", 12))
    img = m.render(zoom=zoom)
    # Attribution required by Esri / OpenStreetMap data providers.
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, height - 14, width, height], fill=(255, 255, 255))
    draw.text((4, height - 12), "© Esri, HERE, Garmin, OSM", fill=(70, 70, 70))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")
