"""Cliente de apiCEP: OCR + validación de comprobantes SPEI contra Banxico."""
from __future__ import annotations

import logging
from pathlib import Path

import clabe
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.file_service import UPLOAD_DIR
from app.services.order_service import get_setting_value

logger = logging.getLogger(__name__)
APICEP_URL = "https://api.apicep.cloud/validate-transfer"
MAX_IMAGE_BYTES = 1024 * 1024  # apiCEP acepta máximo 1 MB


class ApiCepError(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _normalize_bank(value: str) -> str:
    bank = (value or "").strip().upper()
    aliases = {
        "BANCO AZTECA": "AZTECA",
        "CITIBANAMEX": "BANAMEX",
        "BBVA": "BBVA MEXICO",
        "BANCOPPEL": "BANCOPPEL",
    }
    return aliases.get(bank, bank)


async def _platform_accounts(db: AsyncSession) -> list[dict]:
    """Cuentas de la plataforma configuradas para recibir transferencias."""
    accounts: list[dict] = []
    for suffix in ("", "_2"):
        clabe_value = "".join(
            ch
            for ch in (
                await get_setting_value(db, f"BANK_CLABE{suffix}", "")
            ).strip()
            if ch.isdigit()
        )
        if len(clabe_value) != 18:
            continue
        bank = ""
        if not suffix:
            bank = _normalize_bank(
                await get_setting_value(db, "APICEP_BENEFICIARY_BANK", "")
            )
        if not bank:
            cep_code = clabe.BANKS.get(clabe_value[:3])
            bank = _normalize_bank(clabe.BANK_NAMES.get(cep_code, ""))
        if not bank:
            continue
        accounts.append({"clabe": clabe_value, "bank": bank})
    return accounts


async def validate_receipt(
    db: AsyncSession,
    *,
    file_url: str,
    expected_amount=None,
) -> dict:
    """Envía el comprobante a apiCEP y devuelve su respuesta JSON."""
    api_key = (await get_setting_value(db, "APICEP_API_KEY", "")).strip()
    if not api_key:
        raise ApiCepError(
            "not_configured", "Falta configurar la API key de apiCEP."
        )
    accounts = await _platform_accounts(db)
    if not accounts:
        raise ApiCepError(
            "not_configured",
            "La CLABE de la plataforma no está configurada para apiCEP.",
        )

    public_url = (
        await get_setting_value(db, "APP_PUBLIC_URL", settings.APP_URL)
    ).rstrip("/")
    if not public_url.startswith("https://"):
        raise ApiCepError(
            "not_public",
            "apiCEP necesita una URL pública HTTPS para leer el comprobante.",
        )
    image_url = (
        file_url if file_url.startswith("http") else f"{public_url}{file_url}"
    )

    path = UPLOAD_DIR / Path(file_url).name
    if (
        path.suffix.lower() == ".pdf"
        and path.exists()
        and path.stat().st_size > MAX_IMAGE_BYTES
    ):
        raise ApiCepError(
            "file_too_large",
            "El PDF supera 1 MB. Sube una captura de pantalla del comprobante.",
        )

    payload = {
        "imageUrl": image_url,
        "system": "SPEI",
    }
    if len(accounts) == 1:
        payload["beneficiary"] = accounts[0]
    else:
        payload["potentialBeneficiaries"] = accounts
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                APICEP_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except Exception as exc:
        logger.exception("apiCEP no respondió")
        raise ApiCepError(
            "network", "No se pudo contactar a apiCEP. Intenta más tarde."
        ) from exc

    if response.status_code == 401:
        raise ApiCepError("auth", "La API key de apiCEP no es válida.")
    if response.status_code == 403:
        raise ApiCepError(
            "no_plan",
            "apiCEP no tiene solicitudes disponibles. Compra un plan.",
        )
    if response.status_code == 429:
        raise ApiCepError(
            "rate_limited",
            "apiCEP alcanzó el límite de solicitudes de tu plan.",
        )
    if response.status_code >= 400:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = str(body.get("error") or "")
        except ValueError:
            detail = ""
        logger.warning(
            "apiCEP respondió %s: %s", response.status_code, response.text[:300]
        )
        raise ApiCepError(
            "error",
            detail[:300]
            or f"apiCEP respondió {response.status_code}. Intenta más tarde.",
        )
    try:
        return response.json()
    except ValueError as exc:
        raise ApiCepError(
            "error", "apiCEP devolvió una respuesta inválida."
        ) from exc
