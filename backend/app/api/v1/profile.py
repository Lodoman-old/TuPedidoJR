from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.saved_address import SavedAddress
from app.models.user import User
from app.models.user_cart import UserCart
from app.schemas.auth import UserOut
from app.schemas.common import GeoPoint
from app.schemas.saved_address import SavedAddressCreate, SavedAddressOut, SavedAddressUpdate

router = APIRouter()


def _address_out(addr: SavedAddress) -> SavedAddressOut:
    """Serialize a saved address including its lat/lng."""
    from geoalchemy2.shape import to_shape

    point = to_shape(addr.location)
    return SavedAddressOut(
        id=addr.id,
        user_id=addr.user_id,
        name=addr.name,
        address=addr.address,
        location=GeoPoint(lat=point.y, lng=point.x),
        is_default=addr.is_default,
        notes=addr.notes,
    )


@router.get("/me", response_model=UserOut)
async def get_profile(current_user: User = Depends(get_current_user)):
    return current_user


class CartSnapshot(BaseModel):
    items: list[dict] = []
    restaurant_id: str | None = None


@router.get("/cart")
async def get_cart_snapshot(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(UserCart).where(UserCart.user_id == current_user.id)
    )
    cart = result.scalar_one_or_none()
    if not cart:
        return {"items": [], "restaurant_id": None}
    return {
        "items": cart.payload or [],
        "restaurant_id": str(cart.restaurant_id) if cart.restaurant_id else None,
    }


@router.put("/cart")
async def save_cart_snapshot(
    body: CartSnapshot,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(UserCart).where(UserCart.user_id == current_user.id)
    )
    cart = result.scalar_one_or_none()
    if cart:
        cart.payload = body.items
        cart.restaurant_id = body.restaurant_id
    else:
        db.add(UserCart(
            user_id=current_user.id,
            payload=body.items,
            restaurant_id=body.restaurant_id,
        ))
    await db.commit()
    return {"items": body.items, "restaurant_id": body.restaurant_id}


@router.post("/addresses", response_model=SavedAddressOut, status_code=status.HTTP_201_CREATED)
async def create_address(
    body: SavedAddressCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.is_default:
        await db.execute(
            update(SavedAddress)
            .where(SavedAddress.user_id == current_user.id)
            .values(is_default=False)
        )

    addr = SavedAddress(
        user_id=current_user.id,
        name=body.name,
        address=body.address,
        location=f"SRID=4326;POINT({body.location.lng} {body.location.lat})",
        is_default=body.is_default,
        notes=body.notes,
    )
    db.add(addr)
    await db.commit()
    await db.refresh(addr)
    return _address_out(addr)


@router.get("/addresses", response_model=list[SavedAddressOut])
async def list_addresses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SavedAddress)
        .where(SavedAddress.user_id == current_user.id)
        .order_by(SavedAddress.is_default.desc(), SavedAddress.created_at.desc())
    )
    return [_address_out(addr) for addr in result.scalars().all()]


@router.get("/addresses/{addr_id}", response_model=SavedAddressOut)
async def get_address(
    addr_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SavedAddress).where(SavedAddress.id == addr_id, SavedAddress.user_id == current_user.id)
    )
    addr = result.scalar_one_or_none()
    if not addr:
        raise HTTPException(status_code=404, detail="Dirección no encontrada")
    return _address_out(addr)


@router.put("/addresses/{addr_id}", response_model=SavedAddressOut)
async def update_address(
    addr_id: str,
    body: SavedAddressUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SavedAddress).where(SavedAddress.id == addr_id, SavedAddress.user_id == current_user.id)
    )
    addr = result.scalar_one_or_none()
    if not addr:
        raise HTTPException(status_code=404, detail="Dirección no encontrada")

    if body.is_default:
        await db.execute(
            update(SavedAddress)
            .where(SavedAddress.user_id == current_user.id, SavedAddress.id != addr_id)
            .values(is_default=False)
        )

    if body.name is not None:
        addr.name = body.name
    if body.address is not None:
        addr.address = body.address
    if body.location is not None:
        addr.location = f"SRID=4326;POINT({body.location.lng} {body.location.lat})"
    if body.is_default is not None:
        addr.is_default = body.is_default
    if body.notes is not None:
        addr.notes = body.notes

    await db.commit()
    await db.refresh(addr)
    return _address_out(addr)


@router.delete("/addresses/{addr_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    addr_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SavedAddress).where(SavedAddress.id == addr_id, SavedAddress.user_id == current_user.id)
    )
    addr = result.scalar_one_or_none()
    if not addr:
        raise HTTPException(status_code=404, detail="Dirección no encontrada")
    await db.delete(addr)
    await db.commit()
