from sqlalchemy import Boolean, Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geography

from app.db.base import Base, TimestampMixin


class SavedAddress(TimestampMixin, Base):
    __tablename__ = "saved_addresses"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    address = Column(Text, nullable=False)
    location = Column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    notes = Column(String(255), nullable=True)
