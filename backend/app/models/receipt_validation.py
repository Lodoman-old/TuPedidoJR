from sqlalchemy import Column, DateTime, DECIMAL, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base, TimestampMixin


class ReceiptValidation(TimestampMixin, Base):
    """Resultado de revisar un comprobante con IA.

    No aprueba ni rechaza pagos: solo guarda el grado de certeza y los datos
    extraídos para que una persona decida.
    """

    __tablename__ = "receipt_validations"

    entity_type = Column(String(30), nullable=False, index=True)
    entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    file_url = Column(Text, nullable=False)
    expected_kind = Column(String(20), nullable=False)
    expected_amount = Column(DECIMAL(10, 2), nullable=True)
    expected_date = Column(DateTime(timezone=True), nullable=True)
    expected_recipient = Column(String(250), nullable=True)

    document_type = Column(String(30), nullable=True)
    confidence = Column(Integer, default=0, nullable=False, index=True)
    status = Column(String(15), default="review", nullable=False)
    extracted = Column(JSONB, nullable=True)
    issues = Column(JSONB, nullable=True)
    summary = Column(Text, nullable=True)

    provider = Column(String(20), default="gemini", nullable=False)
    model = Column(String(60), nullable=True)
    plan_months = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
