"""Landing pública antes del login."""

from httpx import AsyncClient


async def test_landing_public(client: AsyncClient):
    resp = await client.get("/web/inicio")
    assert resp.status_code == 200
    text = resp.text.lower()
    assert "primer servicio de entrega en línea" in text
    assert "/web/app/apk" in text
    assert "/web/login" in text
    assert "/web/register-restaurant" in text
    assert "afiliación anual" in text
    assert "500" in text
    assert "tupedidojr@gmail.com" in text


async def test_root_redirects_to_landing(client: AsyncClient):
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/web/inicio"


async def test_app_download_does_not_expose_internal_ip(client: AsyncClient):
    resp = await client.get("/web/app")
    assert resp.status_code == 200
    assert "192.168.0.7" not in resp.text
    assert "Servidor / conexión" in resp.text
