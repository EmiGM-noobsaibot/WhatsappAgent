"""
Database models for VidrioBot
SQLite via SQLAlchemy (swap to PostgreSQL in prod with no code changes)
"""
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, JSON, Enum,
    Text, Boolean, ForeignKey, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()

# ─── Enums ───────────────────────────────────────────────────────────────────

class GlassType(str, PyEnum):
    CLARO         = "claro"
    TEMPLADO      = "templado"
    LAMINADO      = "laminado"
    ESPEJO        = "espejo"
    MATE          = "mate"
    REFLECTANTE   = "reflectante"
    VITRAL        = "vitral"

class Thickness(str, PyEnum):
    MM3  = "3mm"
    MM4  = "4mm"
    MM6  = "6mm"
    MM8  = "8mm"
    MM10 = "10mm"
    MM12 = "12mm"

class InstallationType(str, PyEnum):
    VENTANA   = "ventana"
    PUERTA    = "puerta"
    MAMPARA   = "mampara"
    CANCEL    = "cancel"
    FACHADA   = "fachada"
    MESA      = "mesa"
    ESTANTE   = "estante"
    OTRO      = "otro"

class BuyIntent(str, PyEnum):
    HIGH   = "alta"
    MEDIUM = "media"
    LOW    = "baja"

class ConversationStatus(str, PyEnum):
    ACTIVE    = "activa"
    QUOTED    = "cotizada"
    CLOSED    = "cerrada"
    ABANDONED = "abandonada"

# ─── Tables ───────────────────────────────────────────────────────────────────

class Client(Base):
    __tablename__ = "clients"

    id            = Column(Integer, primary_key=True, index=True)
    phone         = Column(String(20), unique=True, index=True, nullable=False)
    name          = Column(String(100), nullable=True)
    city          = Column(String(100), nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversations = relationship("Conversation", back_populates="client")
    quotations    = relationship("Quotation", back_populates="client")


class Conversation(Base):
    __tablename__ = "conversations"

    id            = Column(Integer, primary_key=True, index=True)
    client_id     = Column(Integer, ForeignKey("clients.id"), nullable=False)
    status        = Column(Enum(ConversationStatus), default=ConversationStatus.ACTIVE)
    messages      = Column(JSON, default=list)        # [{role, content, ts}]
    intent_score  = Column(Float, default=0.0)        # 0–100
    buy_intent    = Column(Enum(BuyIntent), nullable=True)
    intent_detail = Column(JSON, default=dict)        # scoring breakdown
    started_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    notified_boss = Column(Boolean, default=False)

    client    = relationship("Client", back_populates="conversations")
    quotation = relationship("Quotation", back_populates="conversation", uselist=False)


class Quotation(Base):
    __tablename__ = "quotations"

    id               = Column(Integer, primary_key=True, index=True)
    client_id        = Column(Integer, ForeignKey("clients.id"), nullable=False)
    conversation_id  = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    folio            = Column(String(20), unique=True, nullable=False)  # e.g. COT-2024-0042

    # Glass specs
    glass_type       = Column(Enum(GlassType), nullable=False)
    thickness        = Column(Enum(Thickness), nullable=False)
    width_cm         = Column(Float, nullable=False)
    height_cm        = Column(Float, nullable=False)
    quantity         = Column(Integer, default=1)
    installation_type= Column(Enum(InstallationType), nullable=False)

    # Modifiers
    with_installation= Column(Boolean, default=False)
    urgency_days     = Column(Integer, default=7)       # días para entrega
    city             = Column(String(100), nullable=True)

    # Pricing
    base_price       = Column(Float, nullable=False)    # precio por m²
    area_m2          = Column(Float, nullable=False)
    material_cost    = Column(Float, nullable=False)
    installation_cost= Column(Float, default=0.0)
    urgency_surcharge= Column(Float, default=0.0)
    subtotal         = Column(Float, nullable=False)
    iva              = Column(Float, nullable=False)
    total            = Column(Float, nullable=False)

    pricing_detail   = Column(JSON, default=dict)       # breakdown completo

    created_at       = Column(DateTime, default=datetime.utcnow)
    valid_until      = Column(DateTime, nullable=True)

    client       = relationship("Client", back_populates="quotations")
    conversation = relationship("Conversation", back_populates="quotation")


class BossNotification(Base):
    __tablename__ = "boss_notifications"

    id             = Column(Integer, primary_key=True, index=True)
    conversation_id= Column(Integer, ForeignKey("conversations.id"), nullable=False)
    quotation_id   = Column(Integer, ForeignKey("quotations.id"), nullable=True)
    channel        = Column(String(20), default="whatsapp")  # whatsapp | email
    payload        = Column(JSON)
    sent_at        = Column(DateTime, default=datetime.utcnow)
    success        = Column(Boolean, default=True)


class DailyReport(Base):
    __tablename__ = "daily_reports"

    id               = Column(Integer, primary_key=True, index=True)
    report_date      = Column(DateTime, nullable=False, unique=True)
    total_conversations   = Column(Integer, default=0)
    total_quotations      = Column(Integer, default=0)
    high_intent_count     = Column(Integer, default=0)
    medium_intent_count   = Column(Integer, default=0)
    low_intent_count      = Column(Integer, default=0)
    potential_revenue     = Column(Float, default=0.0)
    top_products          = Column(JSON, default=list)
    generated_at          = Column(DateTime, default=datetime.utcnow)
    raw_data              = Column(JSON, default=dict)


# ─── DB setup helper ─────────────────────────────────────────────────────────

def get_engine(url: str = "sqlite:///./vidriobot.db"):
    return create_engine(url, connect_args={"check_same_thread": False} if "sqlite" in url else {})

def init_db(engine):
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)
