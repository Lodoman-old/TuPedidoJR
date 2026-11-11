from sqlalchemy import Column, String, Text

from app.db.base import Base, TimestampMixin


class Setting(TimestampMixin, Base):
    __tablename__ = "settings"

    key = Column(String(255), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=True)
    description = Column(String(500), nullable=True)
