from geoalchemy2 import Geometry
from sqlalchemy import Column, Integer, String

from app.db.base import Base


class ColoniaArea(Base):
    __tablename__ = "colonia_areas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(180), nullable=False)
    cp = Column(String(5), nullable=True)
    geom = Column(Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=False)


class AgebArea(Base):
    __tablename__ = "ageb_areas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cvegeo = Column(String(20), unique=True, nullable=False)
    cve_ageb = Column(String(10), nullable=False)
    ambito = Column(String(10), nullable=False)
    geom = Column(Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=False)
