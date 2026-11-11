from geoalchemy2 import Geometry
from sqlalchemy import Column, Integer, String

from app.db.base import Base


class PostalCodeArea(Base):
    __tablename__ = "postal_code_areas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cp = Column(String(5), unique=True, nullable=False)
    geom = Column(Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=False)
