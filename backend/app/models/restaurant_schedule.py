from sqlalchemy import Boolean, Column, ForeignKey, Integer, Time
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class RestaurantSchedule(TimestampMixin, Base):
    """Weekly opening hours for a restaurant.

    ``day_of_week`` follows Python's ``date.weekday()``: 0 = Monday, 6 = Sunday.
    Multiple rows per day allow split shifts (e.g. 13:00-16:00 and 18:00-23:00).
    A row with ``is_closed`` marks the whole day as a day off.
    """

    __tablename__ = "restaurant_schedules"

    restaurant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day_of_week = Column(Integer, nullable=False)
    open_time = Column(Time, nullable=False)
    close_time = Column(Time, nullable=False)
    is_closed = Column(Boolean, default=False, nullable=False)
