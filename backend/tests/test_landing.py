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


async def test_root_redirects_to_landing(client: AsyncClient):
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/web/inicio"
