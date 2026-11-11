from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VentureDB(Base):
    __tablename__ = "ventures"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[str] = mapped_column(Text, nullable=False)


class PortfolioEventDB(Base):
    __tablename__ = "portfolio_events"
    __table_args__ = (UniqueConstraint("venture_id", "version"),)
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    venture_id: Mapped[str] = mapped_column(
        ForeignKey("ventures.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    request: Mapped[str] = mapped_column(Text, nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
