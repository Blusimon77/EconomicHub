from __future__ import annotations
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from models.post import Base


class OwnProduct(Base):
    """Prodotto Cela — importato da celaplatforms.com o inserito manualmente."""
    __tablename__ = "own_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(300), nullable=False)           # Es: "DT22", "DT30 Hybrid"
    product_line = Column(String(200), default="")       # Es: "DT-Truck", "DT-Crawler", "Fire"
    category = Column(String(200), default="")           # Es: "Piattaforma industriale", "Antincendio"
    description = Column(Text, default="")

    # Specifiche tecniche
    working_height = Column(Float, nullable=True)        # metri
    tech_specs = Column(Text, default="")                # JSON: [{key, value, unit}]
    tech_summary = Column(Text, default="")              # testo libero delle specs

    # Sorgente
    page_url = Column(String(1000), default="")          # URL celaplatforms.com
    brochure_url = Column(String(1000), default="")      # URL PDF
    brochure_filename = Column(String(300), default="")  # PDF salvato in locale

    scraped_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    comparisons = relationship(
        "ProductComparison", back_populates="own_product",
        foreign_keys="ProductComparison.own_product_id",
        cascade="all, delete-orphan",
    )


class ProductComparison(Base):
    """Analisi comparativa: 1 nostro prodotto vs N prodotti competitor."""
    __tablename__ = "product_comparisons"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Nostro prodotto
    own_product_id = Column(Integer, ForeignKey("own_products.id"), nullable=True)
    own_product_name = Column(String(300), default="")   # cache del nome

    # Prodotti competitor confrontati (JSON: [{id, name, competitor_name}])
    competitor_products_snapshot = Column(Text, default="")

    # Titolo opzionale
    title = Column(String(300), default="")

    # Output AI
    summary = Column(Text, default="")
    comparison_table = Column(Text, default="")   # JSON: [{feature, our_value, competitors:{}, advantage}]
    per_competitor = Column(Text, default="")     # JSON: [{name, competitor_name, verdict, score, strengths, weaknesses}]
    recommendations = Column(Text, default="")    # JSON: [{priority, action, rationale}]
    raw_response = Column(Text, default="")

    generated_by = Column(String(50), default="anthropic")
    created_at = Column(DateTime, default=datetime.utcnow)

    own_product = relationship(
        "OwnProduct", back_populates="comparisons",
        foreign_keys=[own_product_id],
    )
