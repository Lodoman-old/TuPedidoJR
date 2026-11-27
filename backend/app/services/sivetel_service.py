"""Cliente REST de Sivetel para recargas de tiempo aire.

Documentación: https://developers.sivetel.com/
El servicio usa formularios URL-encoded y responde JSON con la forma
``{"status": bool, "error": int, "message": str, "data": ...}``.

Las transacciones se hacen en dos pasos: ``reservarTransaccion`` devuelve un
``requestid`` y ``procesarTransaccion`` lo ejecuta. Si hay timeout se debe
consultar con ``consultarTransaccion`` antes de reintentar.
"""
from __future__ import annotations

import logging
import time
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.order_service import get_setting_value

logger = logging.getLogger(__name__)

PRODUCT_CACHE_SECONDS = 3600
PROVIDER_UNAVAILABLE_MESSAGE = (
    "El servicio de recargas no está disponible por una intermitencia. "
    "Intenta más tarde."
)


class SivetelError(Exception):
    def __init__(self, code: int, message: str):
        self.code = int(code or 0)
        self.message = message or "Error de Sivetel"
        super().__init__(self.message)


@dataclass
class SivetelConfig:
    base_url: str
    account: str
    user: str
    password: str
    timeout_seconds: int


def _bool(value) -> bool:
    return str(value).strip().lower() == "true"


async def load_config(db: AsyncSession) -> SivetelConfig | None:
    """Devuelve la configuración si el procesamiento está activo y completo."""
    if not _bool(await get_setting_value(db, "SIVETEL_ENABLED", "false")):
        return None
    account = str(await get_setting_value(db, "SIVETEL_ACCOUNT", "")).strip()
    user = str(await get_setting_value(db, "SIVETEL_USER", "")).strip()
    password = str(await get_setting_value(db, "SIVETEL_PASSWORD", "")).strip()
    if not account or not user or not password:
        return None
    base_url = str(
        await get_setting_value(
            db, "SIVETEL_BASE_URL", "https://app.sivetel.com/ApiWS"
        )
    ).strip().rstrip("/")
    try:
        timeout = int(await get_setting_value(db, "SIVETEL_TIMEOUT_SECONDS", "90"))
    except (TypeError, ValueError):
        timeout = 90
    return SivetelConfig(
        base_url=base_url or "https://app.sivetel.com/ApiWS",
        account=account,
        user=user,
        password=password,
        timeout_seconds=max(timeout, 10),
    )


class SivetelClient:
    def __init__(self, config: SivetelConfig):
        self.config = config

    async def _post(self, method: str, payload: dict | None = None) -> dict:
        data = {
            "cuenta": self.config.account,
            "usuario": self.config.user,
            "password": self.config.password,
        }
        if payload:
            data.update(payload)
        url = f"{self.config.base_url}/{method}"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout_seconds)
            ) as client:
                response = await client.post(
                    url,
                    data=data,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise SivetelError(0, "Sivetel no respondió a tiempo") from exc
        except httpx.HTTPError as exc:
            raise SivetelError(0, f"No se pudo conectar con Sivetel: {exc}") from exc

        if response.status_code >= 400:
            raise SivetelError(
                response.status_code,
                f"Sivetel respondió HTTP {response.status_code}",
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise SivetelError(0, "Sivetel devolvió una respuesta no válida") from exc
        if not isinstance(body, dict):
            raise SivetelError(0, "Sivetel devolvió una respuesta no válida")
        return body

    async def consultar_saldos(self) -> dict:
        body = await self._post("consultarSaldos")
        if not body.get("status"):
            raise SivetelError(body.get("error"), body.get("message"))
        return body.get("data") or {}

    async def obtener_productos(self) -> list[dict]:
        body = await self._post("obtenerProductos")
        if not body.get("status"):
            raise SivetelError(body.get("error"), body.get("message"))
        data = body.get("data") or []
        if isinstance(data, dict):
            data = [data]
        return [row for row in data if isinstance(row, dict)]

    async def reservar(self, numero: str, producto: str) -> str:
        body = await self._post(
            "reservarTransaccion",
            {"numero": numero, "producto": producto},
        )
        if not body.get("status"):
            raise SivetelError(body.get("error"), body.get("message"))
        data = body.get("data") or {}
        request_id = data.get("requestid") if isinstance(data, dict) else None
        if not request_id:
            raise SivetelError(0, "Sivetel no devolvió requestid")
        return str(request_id)

    async def procesar(self, request_id: str) -> dict:
        return await self._post(
            "procesarTransaccion", {"requestid": request_id}
        )

    async def consultar(self, request_id: str) -> dict:
        return await self._post(
            "consultarTransaccion", {"requestid": request_id}
        )

    async def probar_conexion(self) -> dict:
        url = f"{self.config.base_url}/testing"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SivetelError(0, f"No se pudo probar Sivetel: {exc}") from exc


# ---------------------------------------------------------------------------
# Catálogo de productos
# ---------------------------------------------------------------------------

_PRODUCTS_CACHE: tuple[float, list[dict]] | None = None


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.upper().replace("&", " ").split())


COMPANY_ALIASES = {
    "TELCEL": ("TELCEL",),
    "AT&T": ("AT&T", "ATT", "AT T"),
    "MOVISTAR": ("MOVISTAR",),
    "UNEFON": ("UNEFON", "UNE"),
    "AMIGO SIN LIMITE": ("AMIGO SIN LIMITE", "AMIGO"),
    "BAIT": ("BAIT",),
    "VIRGIN": ("VIRGIN",),
    "FLASH": ("FLASH",),
    "WIMBO": ("WIMBO", "WIMO"),
    "DIRI": ("DIRI",),
    "PILLOFON": ("PILLOFON",),
    "CIERTO": ("CIERTO",),
    "OU": ("OUI",),
    "SIMPATI": ("SIMPATI",),
    "WEXX": ("WEXX", "WEEX"),
    "MAZ": ("MAZ", "MAZTIEMPO"),
}


def _company_tokens(company: str) -> tuple[str, ...]:
    normalized = _normalize(company)
    for key, aliases in COMPANY_ALIASES.items():
        if normalized == _normalize(key) or any(
            _normalize(alias) in normalized for alias in aliases
        ):
            return tuple(_normalize(alias) for alias in aliases)
    return (normalized,)


def _amount(value) -> Decimal | None:
    try:
        return Decimal(str(value or "")).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


KIND_ORDER = ("saldo", "datos", "tiempo", "paquete", "otros")
KIND_LABELS = {
    "saldo": "Saldo / tiempo aire",
    "datos": "Paquetes de datos",
    "tiempo": "Internet por tiempo",
    "paquete": "Paquetes",
    "otros": "Otros",
}


# Sivetel maneja algunas marcas/líneas con nombres distintos al operador.
# Las agrupamos para que el cliente vea una sola compañía con sus categorías.
COMPANY_CANONICAL = {
    "AMIGO SIN LIMITE": "Telcel",
    "INTERNET MOVIL": "Telcel",
    "INTERNET ILIMITADO": "Telcel",
    "DATOS MOVISTAR": "Movistar",
    "NEXTEL - ATT": "AT&T",
    "UNEFON": "AT&T",
}


def canonical_company(name: str) -> str:
    return COMPANY_CANONICAL.get(_normalize(name), name)


def classify_product(product: dict) -> str:
    """Deduce la categoría con el nombre y la descripción del catálogo.

    Sivetel no envía un campo ``tipo``; sus productos se distinguen por texto:
    Internet/Datos/GB, Internet por tiempo, Paquete, o saldo normal.
    """
    text = _normalize(
        " ".join(
            str(product.get(key) or "")
            for key in ("nombre", "descripcion")
        )
    )
    if "PAQUETE" in text:
        return "paquete"
    if "ILIMITADO" in text or "POR TIEMPO" in text:
        return "tiempo"
    if any(
        keyword in text
        for keyword in ("INTERNET", "DATOS", "GB", "5G")
    ):
        return "datos"
    return "saldo"


def _product_view(product: dict) -> dict | None:
    code = str(product.get("codigo") or "").strip()
    amount = _amount(product.get("monto"))
    if not code or amount is None:
        return None
    company = str(product.get("nombre") or "Otros").strip() or "Otros"
    company = canonical_company(company)
    description = str(product.get("descripcion") or code).strip()
    kind = classify_product(product)
    return {
        "company": company,
        "code": code,
        "description": description,
        "amount": f"{amount:.2f}",
        "kind": kind,
    }


def catalog_payload(products: list[dict]) -> dict:
    """Agrupa el catálogo por compañía y categoría para la interfaz."""
    companies: dict[str, dict] = {}
    total = 0
    for raw in products:
        view = _product_view(raw)
        if view is None:
            continue
        total += 1
        company = view["company"]
        entry = companies.setdefault(
            company,
            {
                "name": company,
                "categories": {kind: [] for kind in KIND_ORDER},
                "count": 0,
            },
        )
        entry["categories"][view["kind"]].append(view)
        entry["count"] += 1

    for entry in companies.values():
        for kind in KIND_ORDER:
            entry["categories"][kind].sort(
                key=lambda item: (Decimal(item["amount"]), item["description"])
            )
        entry["categories"] = {
            kind: items for kind, items in entry["categories"].items() if items
        }

    ordered = sorted(companies.values(), key=lambda item: item["name"].lower())
    return {
        "companies": ordered,
        "kinds": [
            {"key": kind, "label": KIND_LABELS[kind]}
            for kind in KIND_ORDER
        ],
        "total": total,
    }


def find_product(products: list[dict], code: str) -> dict | None:
    wanted = str(code or "").strip().upper()
    if not wanted:
        return None
    for raw in products:
        if str(raw.get("codigo") or "").strip().upper() == wanted:
            view = _product_view(raw)
            if view is not None:
                return view
    return None


async def obtener_catalogo(
    client: SivetelClient, *, force: bool = False
) -> list[dict]:
    global _PRODUCTS_CACHE
    now = time.time()
    if (
        not force
        and _PRODUCTS_CACHE is not None
        and now - _PRODUCTS_CACHE[0] < PRODUCT_CACHE_SECONDS
    ):
        return _PRODUCTS_CACHE[1]
    products = await client.obtener_productos()
    _PRODUCTS_CACHE = (now, products)
    return products


async def provider_status(client: SivetelClient) -> dict:
    """Indica si Sivetel tiene saldo para tiempo aire.

    No expone el saldo exacto al cliente. Si la consulta falla, se trata como
    intermitencia para no crear recargas que no se puedan procesar.
    """
    try:
        saldos = await client.consultar_saldos()
        raw = saldos.get("tiempoaire") if isinstance(saldos, dict) else None
        balance = Decimal(str(raw if raw is not None else "0"))
    except (SivetelError, InvalidOperation, TypeError, ValueError):
        return {
            "available": False,
            "message": PROVIDER_UNAVAILABLE_MESSAGE,
        }
    available = balance > 0
    return {
        "available": available,
        "message": "" if available else PROVIDER_UNAVAILABLE_MESSAGE,
    }


async def resolver_producto(
    client: SivetelClient, company: str, amount: Decimal
) -> str:
    """Encuentra el código de producto para compañía y monto exactos."""
    target = _amount(amount)
    tokens = _company_tokens(company)
    products = await obtener_catalogo(client)

    candidates = []
    for row in products:
        code = str(row.get("codigo") or "").strip()
        if not code:
            continue
        product_amount = _amount(row.get("monto"))
        if target is None or product_amount != target:
            continue
        haystack = _normalize(
            " ".join(
                str(row.get(key) or "")
                for key in ("nombre", "descripcion", "compania", "operador")
            )
        )
        if any(token and token in haystack for token in tokens):
            candidates.append(code)
    if candidates:
        return candidates[0]

    available = sorted(
        {
            str(_amount(row.get("monto")))
            for row in products
            if _amount(row.get("monto")) is not None
        }
    )
    raise SivetelError(
        405,
        f"No hay producto de {company} por ${target}. "
        f"Montos disponibles: {', '.join(available[:20])}",
    )
