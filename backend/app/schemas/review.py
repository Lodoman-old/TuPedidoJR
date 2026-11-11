from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    order_id: str
    restaurant_id: str | None = None
    delivery_person_id: str | None = None
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = None


class ReviewOut(BaseModel):
    id: UUID
    order_id: UUID
    user_id: UUID
    restaurant_id: UUID | None
    delivery_person_id: UUID | None
    rating: int
    comment: str | None
    created_at: datetime

    class Config:
        from_attributes = True
