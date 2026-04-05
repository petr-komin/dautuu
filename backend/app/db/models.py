import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, Numeric, UniqueConstraint, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    preferred_provider: Mapped[str] = mapped_column(String(50), default="together")
    preferred_model: Mapped[str] = mapped_column(String(200), default="meta-llama/Llama-3.3-70B-Instruct-Turbo")
    # MCP API klíč — generuje se na žádost uživatele, slouží jako Bearer token pro MCP endpoint
    api_key: Mapped[uuid.UUID | None] = mapped_column(default=None, unique=True, nullable=True, index=True)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")
    projects: Mapped[list["Project"]] = relationship(back_populates="user")


class Project(Base):
    """Projekt — seskupení konverzací se sdíleným system promptem (instrukcemi)."""
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship(back_populates="projects")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="project")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="Nová konverzace")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Souhrn konverzace — generuje se automaticky po nečinnosti
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    summarized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # MCP Memory konverzace — speciální konverzace pro vzpomínky přidané přes MCP
    is_mcp_memory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped["User"] = relationship(back_populates="conversations")
    project: Mapped["Project | None"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant | system | tool | tool_call
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Metadata pro tool zprávy (role="tool_call" nebo role="tool"):
    #   tool_call: {"tool_calls": [{"id": "...", "name": "...", "args": {...}}, ...]}
    #   tool:      {"tool_call_id": "...", "tool_name": "..."}
    tool_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # MCP projekt — název projektu/workspace ze kterého byla vzpomínka přidána přes MCP
    # NULL = globální (bez projektu), jinak např. "dautuu", "muj-projekt"
    mcp_project: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class McpServer(Base):
    """Uživatelem nakonfigurovaný externí MCP server — dautuu se k němu připojuje jako klient."""
    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    # HTTP hlavičky pro autentizaci, např. {"Authorization": "Bearer ..."}
    headers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Transport protokol: streamable_http | sse
    transport_type: Mapped[str] = mapped_column(String(20), nullable=False, default="streamable_http")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship()


class UsageLog(Base):
    """Záznam o spotřebě a ceně jednoho volání AI služby."""
    __tablename__ = "usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    # Kontext — kdo a kde
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id"), nullable=True)

    # Typ operace a model
    operation: Mapped[str] = mapped_column(String(20), nullable=False)   # chat | embedding | image | tts | stt | video | web_search
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)

    # Extra kontext operace (např. search query)
    query_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Tokeny (pro chat / embedding / stt)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Jednotky pro ne-tokenové modality (obrázky, sekundy, znaky…)
    units: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    units_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # images | seconds | characters | megapixels

    # Cena v USD (NULL = lokální/Ollama = zdarma)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)


class ModelPricing(Base):
    """Ceník modelů — automaticky synchronizován z API providerů při startu.

    Slouží jako primární zdroj cen pro usage logging.
    Hardcoded dict v pricing.py slouží jen jako fallback pokud DB není dostupná.
    """
    __tablename__ = "model_pricing"
    __table_args__ = (
        UniqueConstraint("provider", "model", name="uq_model_pricing_provider_model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    # Ceny v USD za 1 milion tokenů / jednotku
    # Pro chat modely: input_price_usd_per_m a output_price_usd_per_m
    # Pro embedding modely: input_price_usd_per_m, output_price_usd_per_m = NULL
    # Pro image modely: units_price ($/obrázek nebo $/megapixel), input/output = NULL
    input_price_usd_per_m: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    output_price_usd_per_m: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    units_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    units_type: Mapped[str | None] = mapped_column(String(30), nullable=True)  # per_image | per_megapixel | per_minute | per_1k_chars

    # Metadata
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="manual")  # together_api | openai_api | manual
