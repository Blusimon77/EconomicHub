from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, Boolean, Float
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime
import enum


class Base(DeclarativeBase):
    pass


class Platform(str, enum.Enum):
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"


class PostStatus(str, enum.Enum):
    DRAFT = "draft"             # Generato dall'AI, non ancora revisionato
    PENDING = "pending"         # In attesa di approvazione umana
    APPROVED = "approved"       # Approvato, pronto per la pubblicazione
    REJECTED = "rejected"       # Rifiutato dall'umano
    SCHEDULED = "scheduled"     # Approvato e pianificato
    PUBLISHED = "published"     # Pubblicato con successo
    FAILED = "failed"           # Errore durante la pubblicazione


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(Enum(Platform), nullable=False)
    status = Column(Enum(PostStatus), default=PostStatus.DRAFT, nullable=False)

    content = Column(Text, nullable=False)
    hashtags = Column(Text, default="")
    image_url = Column(String(500), nullable=True)
    media_path = Column(String(500), nullable=True)

    topic = Column(String(200), nullable=True)
    tone = Column(String(50), default="professionale")
    generated_by = Column(String(50), default="anthropic")

    scheduled_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)
    platform_post_id = Column(String(200), nullable=True)

    approved_by = Column(String(100), nullable=True)
    approval_note = Column(Text, nullable=True)

    # Metriche engagement (popolate da AnalyticsAgent dopo la pubblicazione)
    likes = Column(Integer, nullable=True)
    comments_count = Column(Integer, nullable=True)
    shares = Column(Integer, nullable=True)
    reach = Column(Integer, nullable=True)
    impressions = Column(Integer, nullable=True)
    engagement_rate = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Post {self.id} [{self.platform}] {self.status}>"


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(Enum(Platform), nullable=False)
    platform_comment_id = Column(String(200), unique=True, nullable=False)
    platform_post_id = Column(String(200), nullable=False)

    author_name = Column(String(200), default="")
    content = Column(Text, nullable=False)
    is_mention = Column(Boolean, default=False)

    reply_draft = Column(Text, nullable=True)
    reply_status = Column(Enum(PostStatus), default=PostStatus.DRAFT, nullable=True)
    reply_published_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
