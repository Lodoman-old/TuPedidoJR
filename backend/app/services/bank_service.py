"""Cuentas bancarias receptoras configuradas para transferencias."""

from __future__ import annotations

import clabe
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.order_service import get_setting_value


async def receiver_accounts(db: AsyncSession) -> list[dict]:
    """Devuelve las cuentas CLABE válidas configuradas en ajustes."""
    accounts: list[dict] = []
    for suffix in ("", "_2"):
        clabe_value = "".join(
            ch
            for ch in (await get_setting_value(db, f"BANK_CLABE{suffix}", "")).strip()
            if ch.isdigit()
        )
        if len(clabe_value) != 18:
            continue
        bank_code = clabe.BANKS.get(clabe_value[:3])
        if not bank_code:
            continue
        accounts.append(
            {
                "clabe": clabe_value,
                "bank_code": bank_code,
                "bank_name": (
                    await get_setting_value(db, f"BANK_NAME{suffix}", "")
                ).strip(),
                "holder": (
                    await get_setting_value(
                        db, f"BANK_ACCOUNT_HOLDER{suffix}", ""
                    )
                ).strip(),
            }
        )
    if not accounts:
        raise ValueError("La cuenta bancaria de la plataforma no está configurada.")
    return accounts
