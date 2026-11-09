from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from sentinel.db import Base


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    business_id: Mapped[str] = mapped_column(String, nullable=False)


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # hashed identifier only


class PaymentInstrument(Base):
    __tablename__ = "payment_instruments"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # hashed token only
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    merchant_id: Mapped[str | None] = mapped_column(String, nullable=True)
    device_id: Mapped[str | None] = mapped_column(String, nullable=True)
    instrument_id: Mapped[str | None] = mapped_column(String, nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    geo: Mapped[str | None] = mapped_column(String, nullable=True)
    label: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    business_id: Mapped[str] = mapped_column(String, nullable=False)
