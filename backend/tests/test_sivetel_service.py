"""Cliente y procesamiento automático de Sivetel (sin llamadas reales)."""

from decimal import Decimal

import pytest

from app.models.recarga_order import RecargaOrder
from app.services import recarga_service, sivetel_service


def _config() -> sivetel_service.SivetelConfig:
    return sivetel_service.SivetelConfig(
        base_url="https://example.test/ApiWS",
        account="5555555505",
        user="demo.user",
        password="secret",
        timeout_seconds=10,
    )


def _recarga(**kwargs) -> RecargaOrder:
    data = {
        "company": "Telcel",
        "phone": "4121234567",
        "amount": Decimal("50.00"),
        "fee": Decimal("2.00"),
        "total": Decimal("52.00"),
        "payment_method": "cash",
        "payment_status": "paid",
        "status": "pending",
        "origin": "checkout",
        "debt_applied": True,
        "credit_applied": True,
    }
    data.update(kwargs)
    return RecargaOrder(**data)


@pytest.fixture(autouse=True)
def reset_catalog():
    sivetel_service._PRODUCTS_CACHE = None
    yield
    sivetel_service._PRODUCTS_CACHE = None


class FakeClient:
    products = [
        {
            "nombre": "Telcel",
            "codigo": "TEL050",
            "descripcion": "Telcel $50",
            "monto": "50.00",
        },
        {
            "nombre": "AT&T",
            "codigo": "ATT100",
            "descripcion": "AT&T $100",
            "monto": "100.00",
        },
    ]

    def __init__(self, config):
        self.config = config
        self.calls = []

    async def obtener_productos(self):
        return self.products

    async def reservar(self, numero, producto):
        self.calls.append(("reservar", numero, producto))
        return "req-1"

    async def procesar(self, request_id):
        self.calls.append(("procesar", request_id))
        return {
            "status": True,
            "error": 0,
            "message": "Recarga Exitosa",
            "data": {
                "folio": "FOLIO-1",
                "requestid": request_id,
                "monto": "50.00",
            },
        }

    async def consultar(self, request_id):
        self.calls.append(("consultar", request_id))
        return {
            "status": True,
            "error": 0,
            "message": "Recarga Exitosa",
            "data": {"folio": "FOLIO-1", "requestid": request_id},
        }


async def test_resolver_producto_por_compania_y_monto():
    client = FakeClient(_config())
    code = await sivetel_service.resolver_producto(
        client, "Telcel", Decimal("50")
    )
    assert code == "TEL050"

    with pytest.raises(sivetel_service.SivetelError):
        await sivetel_service.resolver_producto(
            client, "Telcel", Decimal("30")
        )


def test_catalog_payload_clasifica_productos():
    products = [
        {"nombre": "Telcel", "codigo": "TEL020", "descripcion": "Telcel $20", "monto": "20.00"},
        {"nombre": "Internet Móvil", "codigo": "ITM050", "descripcion": "Internet Telcel $50", "monto": "50.00"},
        {"nombre": "Internet Ilimitado", "codigo": "ILIM010", "descripcion": "Internet Ilimitado por tiempo. 1 hora por $10.", "monto": "10.00"},
        {"nombre": "Amigo Sin Límite", "codigo": "ASL050", "descripcion": "Amigo Sin Limite $50", "monto": "50.00"},
        {"nombre": "Datos Movistar", "codigo": "PDM030", "descripcion": "Datos Movistar $30", "monto": "30.00"},
        {"nombre": "Movistar", "codigo": "MOV050", "descripcion": "Movistar $50", "monto": "50.00"},
        {"nombre": "Bait", "codigo": "BAIT550", "descripcion": "Paquete Bait 3 meses $550", "monto": "550.00"},
        {"nombre": "CFE TEIT", "codigo": "FET105", "descripcion": "CFE TEIT $105 - 6 GB - 7 días", "monto": "105.00"},
        {"nombre": "Nextel - ATT", "codigo": "ATT010", "descripcion": "ATT $10", "monto": "10.00"},
        {"nombre": "Unefon", "codigo": "UNE030", "descripcion": "Unefon $30", "monto": "30.00"},
    ]
    payload = sivetel_service.catalog_payload(products)
    assert payload["total"] == 10
    companies = {c["name"]: c for c in payload["companies"]}
    assert set(companies) == {"Telcel", "Movistar", "Bait", "CFE TEIT", "AT&T"}
    assert set(companies["Telcel"]["categories"]) == {"saldo", "datos", "tiempo"}
    assert set(companies["Movistar"]["categories"]) == {"saldo", "datos"}
    assert set(companies["AT&T"]["categories"]) == {"saldo"}
    assert set(companies["Bait"]["categories"]) == {"paquete"}
    assert set(companies["CFE TEIT"]["categories"]) == {"datos"}
    assert companies["Bait"]["categories"]["paquete"][0]["code"] == "BAIT550"
    assert companies["Telcel"]["categories"]["datos"][0]["code"] == "ITM050"
    assert companies["Telcel"]["categories"]["tiempo"][0]["code"] == "ILIM010"


async def test_process_success_marks_completed(db_session, monkeypatch):
    async def fake_config(db):
        return _config()

    monkeypatch.setattr(sivetel_service, "load_config", fake_config)
    monkeypatch.setattr(sivetel_service, "SivetelClient", FakeClient)

    recarga = _recarga()
    db_session.add(recarga)
    await db_session.commit()
    await db_session.refresh(recarga)

    result = await recarga_service.process_recarga_with_sivetel(
        db_session, recarga
    )
    assert result == "completed"

    await db_session.refresh(recarga)
    assert recarga.status == "completed"
    assert recarga.payment_status == "paid"
    assert recarga.provider_request_id == "req-1"
    assert recarga.provider_folio == "FOLIO-1"
    assert recarga.provider_reference == "FOLIO-1"
    assert recarga.completed_at is not None


async def test_process_definitive_error_marks_failed(db_session, monkeypatch):
    class FailingClient(FakeClient):
        async def procesar(self, request_id):
            return {
                "status": False,
                "error": 3,
                "message": "Recarga Fracasada",
                "data": [],
            }

    async def fake_config(db):
        return _config()

    monkeypatch.setattr(sivetel_service, "load_config", fake_config)
    monkeypatch.setattr(sivetel_service, "SivetelClient", FailingClient)

    recarga = _recarga()
    db_session.add(recarga)
    await db_session.commit()
    await db_session.refresh(recarga)

    result = await recarga_service.process_recarga_with_sivetel(
        db_session, recarga
    )
    assert result == "failed"

    await db_session.refresh(recarga)
    assert recarga.status == "failed"
    assert "Recarga Fracasada" in (recarga.error_message or "")


async def test_timeout_leaves_pending_for_retry(db_session, monkeypatch):
    class TimeoutClient(FakeClient):
        async def procesar(self, request_id):
            raise sivetel_service.SivetelError(
                0, "Sivetel no respondió a tiempo"
            )

    async def fake_config(db):
        return _config()

    monkeypatch.setattr(sivetel_service, "load_config", fake_config)
    monkeypatch.setattr(sivetel_service, "SivetelClient", TimeoutClient)

    recarga = _recarga()
    db_session.add(recarga)
    await db_session.commit()
    await db_session.refresh(recarga)

    result = await recarga_service.process_recarga_with_sivetel(
        db_session, recarga
    )
    assert result == "retry"

    await db_session.refresh(recarga)
    assert recarga.status == "pending"
    assert recarga.provider_request_id == "req-1"
    assert recarga.provider_attempts == 1


async def test_existing_request_id_is_consulted_first(
    db_session, monkeypatch
):
    class ConsultClient(FakeClient):
        async def procesar(self, request_id):
            raise AssertionError("No debe procesar si ya fue procesada")

    async def fake_config(db):
        return _config()

    monkeypatch.setattr(sivetel_service, "load_config", fake_config)
    monkeypatch.setattr(sivetel_service, "SivetelClient", ConsultClient)

    recarga = _recarga(provider_request_id="req-1", status="pending")
    db_session.add(recarga)
    await db_session.commit()
    await db_session.refresh(recarga)

    result = await recarga_service.process_recarga_with_sivetel(
        db_session, recarga
    )
    assert result == "completed"

    await db_session.refresh(recarga)
    assert recarga.status == "completed"
    assert recarga.provider_folio == "FOLIO-1"


async def test_recently_recharged_error_is_retried(db_session, monkeypatch):
    class BusyClient(FakeClient):
        async def procesar(self, request_id):
            return {
                "status": False,
                "error": "6050",
                "message": (
                    "Este número ha sido recargado hace menos de 5 minutos. "
                    "Por favor espere un momento"
                ),
                "data": {"requestid": request_id},
            }

    async def fake_config(db):
        return _config()

    monkeypatch.setattr(sivetel_service, "load_config", fake_config)
    monkeypatch.setattr(sivetel_service, "SivetelClient", BusyClient)

    recarga = _recarga()
    db_session.add(recarga)
    await db_session.commit()
    await db_session.refresh(recarga)

    result = await recarga_service.process_recarga_with_sivetel(
        db_session, recarga
    )
    assert result == "retry"

    await db_session.refresh(recarga)
    assert recarga.status == "pending"
    assert recarga.provider_attempts == 1
    assert "5 minutos" in (recarga.error_message or "")
