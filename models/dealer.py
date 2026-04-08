"""
Anagrafica rivenditori globale.
Un dealer può trattare prodotti di più costruttori (nostra azienda + competitor).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text,
)
from sqlalchemy.orm import relationship

from models.post import Base


class Dealer(Base):
    """Ragione sociale di un rivenditore/concessionario."""
    __tablename__ = "dealers"

    id           = Column(Integer, primary_key=True, index=True)
    name         = Column(String(500), nullable=False)
    website      = Column(String(1000), default="")
    email        = Column(String(200), default="")
    phone        = Column(String(100), default="")

    # Indirizzo strutturato
    address      = Column(String(500), default="")   # via/numero
    city         = Column(String(200), default="")
    state        = Column(String(200), default="")   # provincia/stato
    country      = Column(String(100), default="")
    postal_code  = Column(String(20),  default="")
    latitude     = Column(Float,       nullable=True)
    longitude    = Column(Float,       nullable=True)

    notes        = Column(Text, default="")
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow)

    brands = relationship(
        "DealerBrand",
        back_populates="dealer",
        cascade="all, delete-orphan",
        lazy="joined",
    )


class DealerBrand(Base):
    """Associazione dealer ↔ costruttore/brand."""
    __tablename__ = "dealer_brands"

    id            = Column(Integer, primary_key=True)
    dealer_id     = Column(Integer, ForeignKey("dealers.id"), nullable=False)
    # NULL → nostra azienda; valorizzato → competitor
    competitor_id = Column(Integer, ForeignKey("competitors.id"), nullable=True)
    is_own_brand  = Column(Boolean, default=False)

    dealer     = relationship("Dealer", back_populates="brands")
    competitor = relationship("Competitor", foreign_keys=[competitor_id])
