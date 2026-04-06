from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from datetime import datetime
from models.post import Base


class CompanyContext(Base):
    """Contesto aziendale usato dall'AI per generare contenuti più pertinenti."""
    __tablename__ = "company_context"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identità aziendale
    company_name = Column(String(200), default="")
    description = Column(Text, default="")          # Chi siamo
    mission = Column(Text, default="")              # Mission/vision
    values = Column(Text, default="")               # Valori aziendali
    founded = Column(String(50), default="")        # Anno fondazione / storia

    # Mercato
    products_services = Column(Text, default="")   # Prodotti/servizi offerti
    target_audience = Column(Text, default="")     # Pubblico di riferimento
    sector = Column(String(200), default="")       # Settore/industria
    competitors = Column(Text, default="")         # Principali concorrenti

    # Comunicazione
    tone_of_voice = Column(Text, default="")       # Tono di voce del brand
    topics_to_avoid = Column(Text, default="")     # Argomenti da evitare
    content_pillars = Column(Text, default="")     # Pilastri di contenuto

    # Note libere
    additional_notes = Column(Text, default="")

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_prompt_block(self) -> str:
        """Genera un blocco di testo da iniettare nei prompt AI."""
        parts = []
        if self.company_name:
            parts.append(f"AZIENDA: {self.company_name}")
        if self.description:
            parts.append(f"DESCRIZIONE: {self.description}")
        if self.mission:
            parts.append(f"MISSION: {self.mission}")
        if self.values:
            parts.append(f"VALORI: {self.values}")
        if self.products_services:
            parts.append(f"PRODOTTI/SERVIZI: {self.products_services}")
        if self.target_audience:
            parts.append(f"PUBBLICO TARGET: {self.target_audience}")
        if self.sector:
            parts.append(f"SETTORE: {self.sector}")
        if self.tone_of_voice:
            parts.append(f"TONO DI VOCE: {self.tone_of_voice}")
        if self.content_pillars:
            parts.append(f"PILASTRI DI CONTENUTO: {self.content_pillars}")
        if self.topics_to_avoid:
            parts.append(f"ARGOMENTI DA EVITARE: {self.topics_to_avoid}")
        if self.additional_notes:
            parts.append(f"NOTE: {self.additional_notes}")
        return "\n".join(parts)


class ContextWebsite(Base):
    """Siti web di riferimento per il contesto aziendale."""
    __tablename__ = "context_websites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(500), nullable=False)
    label = Column(String(200), default="")         # Etichetta descrittiva
    category = Column(String(100), default="")      # Es: sito_aziendale, competitor, settore
    notes = Column(Text, default="")                # Note su questo sito
    scraped_content = Column(Text, default="")      # Contenuto estratto (opzionale)
    last_scraped_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
