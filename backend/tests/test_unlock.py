"""Desbloqueo de la app con huella y continuidad de sesión."""

from httpx import AsyncClient


async def test_unlock_page_public(client: AsyncClient):
    resp = await client.get("/web/unlock")
    assert resp.status_code == 200
    text = resp.text
    assert "Entra a TuPedidoJR" in text
    assert "/web/login" in text
    assert "tupedidojr_bio" in text
    assert "tupedidojr_token" in text


async def test_landing_redirects_native_with_saved_session(client: AsyncClient):
    resp = await client.get("/web/inicio")
    assert resp.status_code == 200
    assert "/web/unlock" in resp.text


async def test_login_remembers_email_and_expired_notice(client: AsyncClient):
    resp = await client.get("/web/login")
    assert resp.status_code == 200
    text = resp.text
    assert "tupedidojr_email" in text
    assert "Tu sesión expiró" in text
