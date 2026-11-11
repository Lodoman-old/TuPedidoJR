import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.constants import PaymentStatus
from app.db.session import get_db
from app.models.order import Order
from app.models.user import User
from app.schemas.payment import BankDetailsOut, CreatePreferenceRequest, CreatePreferenceResponse, PaymentStatusOut

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_mp_client(access_token: str):
    import mercadopago
    return mercadopago.SDK(access_token)


async def _get_mp_token(db: AsyncSession) -> str:
    from app.services.setting_service import get_setting
    token = await get_setting(db, "MERCADO_PAGO_ACCESS_TOKEN")
    if not token:
        raise HTTPException(status_code=502, detail="Mercado Pago no configurado. Configura el token en el panel de admin.")
    return token


async def _payment_flags(db: AsyncSession) -> dict:
    from app.services.setting_service import get_setting
    from app.services.loyalty_service import loyalty_config
    mp_enabled = (await get_setting(db, "MP_ENABLED", "false")).lower() == "true"
    transfer_enabled = (await get_setting(db, "TRANSFER_ENABLED", "false")).lower() == "true"
    loyalty = await loyalty_config(db)
    return {
        "cash_enabled": True,
        "mp_enabled": mp_enabled,
        "transfer_enabled": transfer_enabled,
        "loyalty_enabled": loyalty["enabled"],
        "loyalty_visible": loyalty["visible"],
        "loyalty_value_per_point": f"{loyalty['value_per_point']:.2f}",
    }


@router.get("/config")
async def payment_config(db: AsyncSession = Depends(get_db)):
    """Public flags so cart UIs can hide disabled payment methods."""
    return await _payment_flags(db)


@router.get("/bank-details", response_model=BankDetailsOut)
async def get_bank_details(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.setting_service import get_setting
    return BankDetailsOut(
        bank_name=await get_setting(db, "BANK_NAME", ""),
        account_holder=await get_setting(db, "BANK_ACCOUNT_HOLDER", ""),
        clabe=await get_setting(db, "BANK_CLABE", ""),
        card=await get_setting(db, "BANK_CARD", ""),
        recipient="TuPedidoJR",
    )


@router.post("/create-preference", response_model=CreatePreferenceResponse)
async def create_preference(
    body: CreatePreferenceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order).where(Order.id == body.order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a este pedido")
    if order.payment_status != PaymentStatus.PENDING:
        raise HTTPException(status_code=400, detail="Este pedido ya fue procesado")

    flags = await _payment_flags(db)
    if not flags["mp_enabled"]:
        raise HTTPException(
            status_code=400,
            detail="Mercado Pago está deshabilitado por el momento. Paga en efectivo al recibir.",
        )

    items = []
    for oi in order.items:
        items.append({
            "title": oi.name,
            "quantity": oi.quantity,
            "unit_price": float(oi.unit_price),
            "currency_id": "MXN",
        })

    preference_data = {
        "items": items,
        "payer": {"email": current_user.email},
        "back_urls": {
            "success": settings.MERCADO_PAGO_SUCCESS_URL,
            "failure": settings.MERCADO_PAGO_FAILURE_URL,
            "pending": settings.MERCADO_PAGO_PENDING_URL,
        },
        "auto_return": "approved",
        "external_reference": str(order.id),
        "notification_url": f"{settings.APP_URL}/api/v1/payments/webhook",
    }

    try:
        token = await _get_mp_token(db)
        sdk = _get_mp_client(token)
        result = sdk.preference().create(preference_data)
        if result["status"] not in (200, 201):
            raise HTTPException(status_code=502, detail="Error al crear preferencia en Mercado Pago")
        pref = result["response"]

        order.preference_id = pref["id"]
        await db.commit()

        return CreatePreferenceResponse(
            preference_id=pref["id"],
            checkout_url=pref["init_point"],
            sandbox_init_point=pref.get("sandbox_init_point"),
        )
    except HTTPException:
        raise
    except Exception as ex:
        logger.exception("Error creando preferencia MP")
        raise HTTPException(status_code=502, detail=f"Error de conexión con Mercado Pago: {ex}")


@router.post("/webhook")
async def webhook(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid body")

    action = body.get("action") or body.get("type", "")
    if action not in ("payment.created", "payment.updated", "payment"):
        return {"status": "ignored"}

    data = body.get("data", {})
    payment_id = data.get("id") if isinstance(data, dict) else None
    if not payment_id:
        return {"status": "ignored"}

    try:
        token = await _get_mp_token(db)
        sdk = _get_mp_client(token)
        payment_result = sdk.payment().get(payment_id)
        if payment_result["status"] != 200:
            logger.warning("No se pudo obtener payment %s", payment_id)
            return {"status": "error"}

        pdata = payment_result["response"]
        external_ref = pdata.get("external_reference")
        mp_status = pdata.get("status")

        if not external_ref or not mp_status:
            return {"status": "ignored"}

        status_map = {
            "approved": PaymentStatus.APPROVED,
            "in_process": PaymentStatus.IN_PROCESS,
            "rejected": PaymentStatus.REJECTED,
            "refunded": PaymentStatus.REFUNDED,
            "cancelled": PaymentStatus.CANCELLED,
        }
        new_status = status_map.get(mp_status)
        if new_status:
            await db.execute(
                update(Order)
                .where(Order.id == external_ref)
                .values(payment_status=new_status, payment_id=str(payment_id))
            )
            await db.commit()
            logger.info("Payment %s -> %s for order %s", payment_id, mp_status, external_ref)

        return {"status": "ok"}
    except Exception as ex:
        logger.exception("Error procesando webhook MP")
        return {"status": "error", "detail": str(ex)}


@router.get("/{order_id}/status", response_model=PaymentStatusOut)
async def payment_status(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a este pedido")
    return PaymentStatusOut(
        order_id=order.id,
        payment_status=order.payment_status.value if order.payment_status else "pending",
        payment_id=order.payment_id,
    )
