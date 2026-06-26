from datetime import datetime

from sqlalchemy import BIGINT, DECIMAL, DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PurchaseRecord(Base):
    __tablename__ = "purchase_records"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    product_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    purchase_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    purchase_spec: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    order_no: Mapped[str | None] = mapped_column(String(255), nullable=True)

    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    shop_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bill_quantity: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    final_purchase_price: Mapped[float | None] = mapped_column(DECIMAL(18, 4), nullable=True)
    selling_price: Mapped[float | None] = mapped_column(DECIMAL(18, 4), nullable=True)
    settlement_unit_price: Mapped[float | None] = mapped_column(DECIMAL(18, 4), nullable=True)
    settlement_amount: Mapped[float | None] = mapped_column(DECIMAL(18, 4), nullable=True)
    gross_profit_margin: Mapped[float | None] = mapped_column(DECIMAL(10, 4), nullable=True)
    tax_included: Mapped[str | None] = mapped_column(String(16), nullable=True)
    invoice_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tax_rate: Mapped[float | None] = mapped_column(DECIMAL(10, 4), nullable=True)
    product_link: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    context_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    turn_index: Mapped[int] = mapped_column(BIGINT, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
