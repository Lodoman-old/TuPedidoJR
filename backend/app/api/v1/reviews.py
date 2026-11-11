from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.constants import OrderStatus
from app.db.session import get_db
from app.models.delivery_person import DeliveryPerson
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.review import Review
from app.models.user import User
from app.schemas.review import ReviewCreate, ReviewOut

router = APIRouter()


@router.post("", response_model=ReviewOut, status_code=201)
async def create_review(
    body: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Order).where(Order.id == body.order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No puedes calificar este pedido")
    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(status_code=400, detail="Solo puedes calificar pedidos entregados")

    if body.restaurant_id and str(body.restaurant_id) != str(order.restaurant_id):
        raise HTTPException(status_code=400, detail="El restaurante no corresponde a este pedido")
    if body.delivery_person_id and (
        order.delivery_person_id is None
        or str(body.delivery_person_id) != str(order.delivery_person_id)
    ):
        raise HTTPException(status_code=400, detail="El repartidor no corresponde a este pedido")

    existing_stmt = select(Review).where(
        Review.order_id == order.id, Review.user_id == current_user.id
    )
    if body.restaurant_id:
        existing_stmt = existing_stmt.where(Review.restaurant_id == body.restaurant_id)
    if body.delivery_person_id:
        existing_stmt = existing_stmt.where(Review.delivery_person_id == body.delivery_person_id)
    existing = await db.execute(existing_stmt)
    if existing.scalars().first():
        if body.restaurant_id:
            raise HTTPException(status_code=400, detail="Ya calificaste este restaurante")
        if body.delivery_person_id:
            raise HTTPException(status_code=400, detail="Ya calificaste a este repartidor")
        raise HTTPException(status_code=400, detail="Ya calificaste este pedido")

    review = Review(
        order_id=order.id,
        user_id=current_user.id,
        restaurant_id=body.restaurant_id,
        delivery_person_id=body.delivery_person_id,
        rating=body.rating,
        comment=body.comment,
    )
    db.add(review)
    await db.flush()

    if body.restaurant_id:
        await _update_avg_rating(db, Restaurant, body.restaurant_id)

    if body.delivery_person_id:
        await _update_avg_rating(db, DeliveryPerson, body.delivery_person_id)

    await db.commit()
    await db.refresh(review)
    return review


async def _update_avg_rating(db, model_cls, entity_id: str):
    if model_cls == Restaurant:
        filter_col = Review.restaurant_id
    else:
        filter_col = Review.delivery_person_id
    result = await db.execute(select(Review.rating).where(filter_col == entity_id))
    ratings = result.scalars().all()
    if ratings:
        avg = round(sum(ratings) / len(ratings), 1)
        entity = (await db.execute(select(model_cls).where(model_cls.id == entity_id))).scalar_one()
        entity.rating = avg


@router.get("/order/{order_id}", response_model=list[ReviewOut])
async def get_order_reviews(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Review).where(
            Review.order_id == order_id,
            Review.user_id == current_user.id,
        )
    )
    return result.scalars().all()


@router.get("/restaurant/{restaurant_id}", response_model=list[ReviewOut])
async def get_restaurant_reviews(
    restaurant_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Review).where(Review.restaurant_id == restaurant_id).order_by(Review.created_at.desc())
    )
    return result.scalars().all()


@router.get("/delivery/{delivery_person_id}", response_model=list[ReviewOut])
async def get_delivery_reviews(
    delivery_person_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Review).where(Review.delivery_person_id == delivery_person_id).order_by(Review.created_at.desc())
    )
    return result.scalars().all()
