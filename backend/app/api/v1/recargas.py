from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_superuser
from app.db.session import get_db
from app.models.balance_payment import BalancePayment
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.recarga_order import RecargaOrder
from app.models.user import User
from app.schemas.order import TransferValidationRequest
from app.schemas.recarga import RecargaComplete, RecargaCreate, RecargaFail, RecargaOut
from app.services import bank_service, recarga_service, sivetel_service
from app.services.cep_validation_service import CepValidationError, validate_transfer
from app.services.file_service import save_document
from app.services.order_service import get_setting_value
from app.services.receipt_validation_service import TRANSFER, create_and_validate

router = APIRouter()
admin_router = APIRouter()


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Identificador inválido") from exc


def _out(recarga: RecargaOrder, courier_name: str | None = None) -> RecargaOut:
    data = RecargaOut.model_validate(recarga)
    data.courier_name = courier_name
    data.order_code = str(recarga.order_id)[:8] if recarga.order_id else None
    return data


async def _courier_for_user(db: AsyncSession, user: User) -> DeliveryPerson | None:
    result = await db.execute(
        select(DeliveryPerson).where(DeliveryPerson.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def _transfer_key_used(
    db: AsyncSession, key: str, recarga_id
) -> bool:
    if await db.scalar(
        select(Order.id).where(Order.transfer_tracking_key == key)
    ):
        return True
    if await db.scalar(
        select(BalancePayment.id).where(
            BalancePayment.transfer_tracking_key == key
        )
    ):
        return True
    return bool(
        await db.scalar(
            select(RecargaOrder.id).where(
                RecargaOrder.transfer_tracking_key == key,
                RecargaOrder.id != recarga_id,
            )
        )
    )


@router.get("/catalogo")
async def catalogo(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Catálogo de productos agrupado por compañía y tipo."""
    if not await recarga_service.recharges_enabled(db):
        raise HTTPException(
            status_code=503,
            detail="Las recargas de tiempo aire no están disponibles por ahora.",
        )
    config = await sivetel_service.load_config(db)
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="Sivetel no está configurado.",
        )
    try:
        client = sivetel_service.SivetelClient(config)
        products = await sivetel_service.obtener_catalogo(client)
    except sivetel_service.SivetelError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo consultar el catálogo: {exc.message}",
        ) from exc
    payload = sivetel_service.catalog_payload(products)
    payload["provider"] = await sivetel_service.provider_status(client)
    return payload


async def _resolve_catalog_product(db: AsyncSession, code: str | None) -> dict:
    """Valida el código contra el catálogo vigente de Sivetel."""
    if not code:
        raise HTTPException(
            status_code=400,
            detail="Selecciona un producto del catálogo para la recarga.",
        )
    config = await sivetel_service.load_config(db)
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="Sivetel no está configurado.",
        )
    try:
        client = sivetel_service.SivetelClient(config)
        products = await sivetel_service.obtener_catalogo(client)
    except sivetel_service.SivetelError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo consultar el catálogo: {exc.message}",
        ) from exc
    status = await sivetel_service.provider_status(client)
    if not status["available"]:
        raise HTTPException(status_code=503, detail=status["message"])
    product = sivetel_service.find_product(products, code)
    if product is None:
        raise HTTPException(
            status_code=400,
            detail="El producto de recarga ya no está disponible.",
        )
    return product


@router.post("", response_model=RecargaOut, status_code=201)
async def create_recarga(
    body: RecargaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not await recarga_service.recharges_enabled(db):
        raise HTTPException(
            status_code=503,
            detail="Las recargas de tiempo aire no están disponibles por ahora.",
        )

    if body.payment_method == "transfer":
        product = await _resolve_catalog_product(db, body.product_code)
        try:
            recarga = await recarga_service.create_transfer_recarga(
                db,
                current_user,
                company=product["company"],
                phone=body.phone,
                amount=Decimal(product["amount"]),
                customer_name=body.customer_name,
                product_code=product["code"],
                product_description=product["description"],
                product_kind=product["kind"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _out(recarga)

    dp = await _courier_for_user(db, current_user)
    if dp is None:
        raise HTTPException(
            status_code=403,
            detail="Solo un repartidor puede vender recargas en efectivo.",
        )

    order = None
    if body.order_id:
        order = await db.get(Order, body.order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Pedido no encontrado")
        if order.delivery_person_id != dp.id:
            raise HTTPException(status_code=403, detail="Ese pedido no te pertenece")
        if order.status not in ("in_delivery", "picked_up", "delivered"):
            raise HTTPException(
                status_code=400,
                detail="La recarga solo se puede ofrecer al entregar el pedido.",
            )
    elif not body.product_code:
        raise HTTPException(
            status_code=400,
            detail="Selecciona un producto del catálogo para la recarga.",
        )

    if body.product_code:
        product = await _resolve_catalog_product(db, body.product_code)
        body.company = product["company"]
        body.amount = Decimal(product["amount"])
        body.product_code = product["code"]
        body.product_description = product["description"]
        body.product_kind = product["kind"]

    try:
        recarga = await recarga_service.create_cash_recarga(
            db, dp,
            company=body.company,
            phone=body.phone,
            amount=body.amount,
            order=order,
            customer_name=body.customer_name,
            product_code=body.product_code,
            product_description=body.product_description,
            product_kind=body.product_kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(recarga, current_user.name)


@router.get("/my", response_model=list[RecargaOut])
async def my_recargas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dp = await _courier_for_user(db, current_user)
    if dp is not None:
        rows = await recarga_service.list_recargas_for_courier(db, dp)
    else:
        rows = await recarga_service.list_recargas_for_user(db, current_user.id)
    return [_out(row, current_user.name if dp else None) for row in rows]


@router.get("/portal", response_model=list[RecargaOut])
async def my_portal_recargas(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Recargas compradas desde el portal (solo transferencia)."""
    rows = (
        await db.execute(
            select(RecargaOrder)
            .where(
                RecargaOrder.user_id == current_user.id,
                RecargaOrder.payment_method == "transfer",
            )
            .order_by(RecargaOrder.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return [_out(row) for row in rows]


@router.post("/{recarga_id}/validate-transfer")
async def validate_recarga_transfer(
    recarga_id: str,
    body: TransferValidationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Valida con Banxico la transferencia de una recarga del portal."""
    recarga = await recarga_service.get_recarga(db, _uuid(recarga_id))
    if recarga is None or recarga.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recarga no encontrada")
    if recarga.payment_method != "transfer":
        raise HTTPException(
            status_code=400,
            detail="Esta recarga no se paga por transferencia.",
        )
    if not await recarga_service.recharges_enabled(db):
        raise HTTPException(
            status_code=503,
            detail="Las recargas de tiempo aire no están disponibles por ahora.",
        )
    if recarga.payment_status == "paid":
        return {
            "payment_status": "approved",
            "message": "Esta recarga ya está pagada.",
            "recarga": _out(recarga),
        }

    enabled = (
        await get_setting_value(db, "CEP_ENABLED", "false")
    ).lower() == "true"
    if not enabled:
        raise HTTPException(
            status_code=400,
            detail=(
                "La validación automática con Banxico no está activada. "
                "Envía tu comprobante a soporte para revisión."
            ),
        )

    force_closed = (
        await get_setting_value(db, "CEP_FORCE_CLOSED", "false")
    ).lower() == "true"
    if force_closed:
        recarga.cep_status = "review"
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail=(
                "Banxico está cerrado (simulación). Envía tu comprobante "
                "a soporte para revisión."
            ),
        )

    accounts = await bank_service.receiver_accounts(db)
    sender_bank = str(body.sender_bank or "").strip()
    receiver = next(
        (
            account
            for account in accounts
            if account["bank_code"] != sender_bank
        ),
        accounts[0],
    )

    key = body.clave_rastreo.strip()
    if await _transfer_key_used(db, key, recarga.id):
        raise HTTPException(
            status_code=409,
            detail="Esa transferencia ya fue usada en otro pago.",
        )

    amount_cents = int(
        (Decimal(recarga.total or recarga.amount or 0) * 100).to_integral_value()
    )
    transfer_date = body.transfer_date or datetime.now(timezone.utc).date()
    try:
        cep = await validate_transfer(
            clave_rastreo=key,
            sender_bank=sender_bank,
            receiver_bank=receiver["bank_code"],
            receiver_account=receiver["clabe"],
            amount_cents=amount_cents,
            transfer_date=transfer_date,
        )
    except CepValidationError as exc:
        status_by_error = {
            "not_found": 404,
            "pending": 409,
            "rate_limited": 429,
            "invalid_bank": 400,
            "invalid_account": 400,
            "missing_key": 400,
            "invalid_amount": 400,
            "invalid_date": 400,
            "closed": 409,
            "amount_mismatch": 409,
            "account_mismatch": 409,
            "receiver_mismatch": 409,
            "sender_mismatch": 409,
            "key_mismatch": 409,
            "same_bank": 409,
            "error": 502,
        }
        if exc.status in (
            "not_found",
            "pending",
            "rate_limited",
            "closed",
            "amount_mismatch",
            "account_mismatch",
            "receiver_mismatch",
            "sender_mismatch",
            "key_mismatch",
            "same_bank",
            "error",
        ):
            recarga.cep_status = "review"
            await db.commit()
        raise HTTPException(
            status_code=status_by_error.get(exc.status, 502),
            detail=exc.message,
        ) from exc

    recarga_service.apply_transfer_payment(
        recarga,
        tracking_key=key,
        sender_bank=sender_bank,
        receiver_bank=receiver["bank_code"],
        payload=cep,
    )
    await db.commit()
    await db.refresh(recarga)
    return {
        "payment_status": "approved",
        "message": "Pago validado por Banxico. Tu recarga se está procesando.",
        "recarga": _out(recarga),
    }


@router.post("/{recarga_id}/validate-receipt")
async def validate_recarga_receipt(
    recarga_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lee el comprobante y valida la transferencia de la recarga con Banxico."""
    recarga = await recarga_service.get_recarga(db, _uuid(recarga_id))
    if recarga is None or recarga.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recarga no encontrada")
    if recarga.payment_method != "transfer":
        raise HTTPException(
            status_code=400,
            detail="Esta recarga no se paga por transferencia.",
        )
    if recarga.payment_status == "paid":
        return {
            "payment_status": "approved",
            "cep_status": recarga.cep_status or "valid",
            "message": "Esta recarga ya está pagada.",
            "recarga": _out(recarga),
        }

    enabled = (
        await get_setting_value(db, "CEP_ENABLED", "false")
    ).lower() == "true"
    if not enabled:
        raise HTTPException(
            status_code=400,
            detail="La validación automática con Banxico no está activada.",
        )
    provider = (
        await get_setting_value(db, "RECEIPT_VALIDATION_PROVIDER", "gemini")
    ).strip().lower()
    if provider != "apicep":
        raise HTTPException(
            status_code=400,
            detail="La lectura automática de comprobantes no está activada.",
        )
    validation_enabled = (
        await get_setting_value(db, "RECEIPT_VALIDATION_ENABLED", "false")
    ).lower() == "true"
    if not validation_enabled:
        raise HTTPException(
            status_code=400,
            detail="La lectura automática de comprobantes no está activada.",
        )
    if not (await get_setting_value(db, "APICEP_API_KEY", "")).strip():
        gemini_key = (
            await get_setting_value(db, "GEMINI_API_KEY", "")
        ).strip()
        if not gemini_key:
            raise HTTPException(
                status_code=400,
                detail="La validación automática no está configurada.",
            )

    accounts = await bank_service.receiver_accounts(db)
    expected_recipient = " o ".join(
        account["clabe"] for account in accounts
    )

    try:
        file_url = await save_document(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record = await create_and_validate(
        db,
        "recarga_transfer",
        recarga.id,
        file_url,
        TRANSFER,
        expected_amount=recarga.total,
        expected_date=recarga.created_at or datetime.now(timezone.utc),
        expected_recipient=expected_recipient,
    )
    if record is None:
        raise HTTPException(
            status_code=400,
            detail="No se pudo registrar tu comprobante.",
        )

    extracted = record.extracted or {}
    details = (extracted.get("validation") or {}).get("cepDetails") or {}

    if record.status in ("high", "preapproved"):
        key = str(
            extracted.get("trackingKey")
            or details.get("trackingKey")
            or ""
        ).strip()
        if key and await _transfer_key_used(db, key, recarga.id):
            raise HTTPException(
                status_code=409,
                detail="Esa transferencia ya fue usada en otro pago.",
            )
        recarga_service.apply_transfer_payment(
            recarga,
            tracking_key=key or None,
            sender_bank=(
                extracted.get("senderBank") or details.get("senderBank")
            ),
            receiver_bank=(
                details.get("receiverBank") or extracted.get("receiverBank")
            ),
            payload=extracted,
            cep_status="valid" if record.status == "high" else "preapproved",
        )
        await db.commit()
        await db.refresh(recarga)
        if record.status == "preapproved":
            message = (
                "Pago preaprobado. Tu recarga se está procesando; "
                "Banxico lo confirmará en horario hábil."
            )
        else:
            message = "Pago validado por Banxico. Tu recarga se está procesando."
        return {
            "payment_status": "approved",
            "cep_status": recarga.cep_status,
            "message": message,
            "recarga": _out(recarga),
        }

    if record.status == "pending_cep":
        recarga.cep_status = "pending_cep"
        await db.commit()
        return {
            "payment_status": "pending",
            "cep_status": "pending_cep",
            "message": record.summary or (
                "Tu comprobante quedó pendiente. Banxico valida de 09:30 a 23:00; "
                "lo validaremos automáticamente al abrir."
            ),
            "recarga": _out(recarga),
        }

    if record.status == "review":
        recarga.cep_status = "review"
        await db.commit()
        reason = record.summary or "Pago en revisión."
        issues = record.issues or []
        if issues:
            reason = f"{reason} {issues[0]}"
        return {
            "payment_status": "pending",
            "cep_status": "review",
            "message": (
                "Tu recarga quedó en revisión de pago. "
                "El administrador confirmará tu transferencia. "
                f"{reason}"
            ),
            "recarga": _out(recarga),
        }

    recarga.cep_status = "review"
    await db.commit()
    issues = record.issues or []
    detail = record.error or (str(issues[0]) if issues else "")
    raise HTTPException(
        status_code=422,
        detail=detail or (
            "No se pudo confirmar la transferencia con Banxico. "
            "Revisa que el comprobante sea legible o captura la clave de rastreo."
        ),
    )


@router.post("/{recarga_id}/retry", response_model=RecargaOut)
async def retry_my_recarga(
    recarga_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    recarga = await recarga_service.get_recarga(db, _uuid(recarga_id))
    if not recarga:
        raise HTTPException(status_code=404, detail="Recarga no encontrada")
    dp = await _courier_for_user(db, current_user)
    if dp is None or recarga.delivery_person_id != dp.id:
        raise HTTPException(status_code=403, detail="No puedes reintentar esta recarga")
    try:
        recarga = await recarga_service.retry_recarga(db, recarga)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(recarga, current_user.name)


@admin_router.get("/recargas", response_model=list[RecargaOut])
async def admin_recargas(
    status_filter: str | None = None,
    q: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    query = (
        select(RecargaOrder, User)
        .outerjoin(DeliveryPerson, DeliveryPerson.id == RecargaOrder.delivery_person_id)
        .outerjoin(User, User.id == DeliveryPerson.user_id)
        .order_by(RecargaOrder.created_at.desc())
        .limit(min(max(limit, 1), 300))
    )
    if status_filter in ("requested", "pending", "completed", "failed", "refunded"):
        query = query.where(RecargaOrder.status == status_filter)
    term = (q or "").strip()
    if term:
        like = f"%{term}%"
        query = query.where(or_(
            RecargaOrder.phone.ilike(like),
            RecargaOrder.company.ilike(like),
            RecargaOrder.provider_reference.ilike(like),
        ))
    result = await db.execute(query)
    return [_out(row, user.name if user else None) for row, user in result.all()]


@admin_router.post("/recargas/{recarga_id}/confirm-payment", response_model=RecargaOut)
async def admin_confirm_payment(
    recarga_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    recarga = await recarga_service.get_recarga(db, _uuid(recarga_id))
    if not recarga:
        raise HTTPException(status_code=404, detail="Recarga no encontrada")
    try:
        recarga = await recarga_service.confirm_transfer_payment(db, recarga)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(recarga)


@admin_router.post("/recargas/{recarga_id}/complete", response_model=RecargaOut)
async def admin_complete(
    recarga_id: str,
    body: RecargaComplete | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    recarga = await recarga_service.get_recarga(db, _uuid(recarga_id))
    if not recarga:
        raise HTTPException(status_code=404, detail="Recarga no encontrada")
    try:
        recarga = await recarga_service.complete_recarga(
            db, recarga,
            reference=body.provider_reference if body else None,
            notes=body.notes if body else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(recarga)


@admin_router.post("/recargas/{recarga_id}/fail", response_model=RecargaOut)
async def admin_fail(
    recarga_id: str,
    body: RecargaFail | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    recarga = await recarga_service.get_recarga(db, _uuid(recarga_id))
    if not recarga:
        raise HTTPException(status_code=404, detail="Recarga no encontrada")
    try:
        recarga = await recarga_service.fail_recarga(
            db, recarga, None,
            refund=body.refund if body else True,
            error_message=body.error_message if body else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(recarga)


@admin_router.post("/recargas/{recarga_id}/retry", response_model=RecargaOut)
async def admin_retry(
    recarga_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    recarga = await recarga_service.get_recarga(db, _uuid(recarga_id))
    if not recarga:
        raise HTTPException(status_code=404, detail="Recarga no encontrada")
    try:
        recarga = await recarga_service.retry_recarga(db, recarga)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(recarga)
