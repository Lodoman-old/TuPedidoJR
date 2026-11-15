"""Redondeo de importes a números enteros.

Regla del negocio:
- 25.5 -> 25 (el .5 exacto se queda en el entero inferior)
- 25.6 -> 26 (si supera .5, sube al siguiente)
"""
from decimal import Decimal, ROUND_HALF_DOWN


def round_half_down(value) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0)).quantize(
            Decimal("1"), rounding=ROUND_HALF_DOWN
        )
    except Exception:
        return Decimal("0")
