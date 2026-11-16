"""Correos con manuales y logo corporativo."""

from app.services.email_service import _email_shell, manuals_html


def test_manual_links_for_business():
    html = manuals_html("https://tupedidojr.test", "business")
    assert "https://tupedidojr.test/manuales/restaurante" in html
    assert "https://tupedidojr.test/manuales/pedidos" in html
    assert "https://tupedidojr.test/manuales/envios" in html
    assert "https://tupedidojr.test/manuales" in html


def test_manual_links_for_courier():
    html = manuals_html("https://tupedidojr.test", "courier")
    assert "https://tupedidojr.test/manuales/repartidor" in html
    assert "https://tupedidojr.test/manuales/restaurante" not in html


def test_email_shell_includes_logo():
    html = _email_shell(
        "Bienvenido",
        "Hola",
        "<p>Contenido</p>",
        logo_url="https://tupedidojr.test/static/logo.png",
    )
    assert "https://tupedidojr.test/static/logo.png" in html
    assert "TuPedidoJR" in html
