from __future__ import annotations
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from models.post import Base


class Competitor(Base):
    __tablename__ = "competitors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    website = Column(String(500), default="")
    sector = Column(String(200), default="")
    description = Column(Text, default="")

    # Analisi strategica
    strengths = Column(Text, default="")
    weaknesses = Column(Text, default="")
    content_strategy = Column(Text, default="")
    target_audience = Column(Text, default="")
    tone_of_voice = Column(Text, default="")
    unique_topics = Column(Text, default="")        # Argomenti su cui sono forti
    posting_frequency = Column(String(100), default="")

    # Valutazione
    threat_level = Column(Integer, default=2)       # 1-3: basso, medio, alto
    is_active = Column(Boolean, default=True)

    # Contenuto sito
    scraped_content = Column(Text, default="")
    last_scraped_at = Column(DateTime, nullable=True)

    # Ricerca web (Tavily)
    search_results = Column(Text, default="")   # JSON: [{title, url, content}]
    last_searched_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    socials = relationship("CompetitorSocial", back_populates="competitor", cascade="all, delete-orphan")
    observations = relationship("CompetitorObservation", back_populates="competitor", cascade="all, delete-orphan", order_by="CompetitorObservation.created_at.desc()")


class CompetitorSocial(Base):
    __tablename__ = "competitor_socials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    competitor_id = Column(Integer, ForeignKey("competitors.id"), nullable=False)
    platform = Column(String(50), nullable=False)   # linkedin, facebook, instagram
    profile_url = Column(String(500), default="")
    handle = Column(String(200), default="")
    followers = Column(String(50), default="")      # stringa per flessibilità (es "12.4K")
    avg_likes = Column(String(50), default="")
    avg_comments = Column(String(50), default="")
    posting_days = Column(String(200), default="")  # Es: lun, mer, ven
    content_types = Column(Text, default="")        # Es: video, caroselli, testo
    notes = Column(Text, default="")

    competitor = relationship("Competitor", back_populates="socials")


class CompetitorObservation(Base):
    __tablename__ = "competitor_observations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    competitor_id = Column(Integer, ForeignKey("competitors.id"), nullable=False)
    category = Column(String(100), default="generale")  # contenuto, tono, audience, campagna, altro
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    competitor = relationship("Competitor", back_populates="observations")


class CompetitorAnalysis(Base):
    """Analisi AI del panorama competitivo, generata on-demand."""
    __tablename__ = "competitor_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # JSON strutturato restituito dall'AI
    summary = Column(Text, default="")
    landscape = Column(Text, default="")        # panorama generale
    per_competitor = Column(Text, default="")   # JSON: [{id, name, insights, social_score, verdict}]
    opportunities = Column(Text, default="")    # JSON: [str]
    threats = Column(Text, default="")          # JSON: [str]
    recommendations = Column(Text, default="")  # JSON: [str]
    content_gaps = Column(Text, default="")     # JSON: [str]
    data_quality = Column(Text, default="")
    sources_used = Column(Text, default="")     # JSON: {competitor_name: [{title,url,content}]}
    raw_response = Column(Text, default="")
    generated_by = Column(String(50), default="anthropic")
    created_at = Column(DateTime, default=datetime.utcnow)
