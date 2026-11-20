"""Download job, source item, credential, persona and API token models."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime

from core.database import Base


class DownloadJob(Base):
    __tablename__ = "download_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="queued")
    progress: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Immutable request options (for example, a Fanbox content policy).  Queue
    # payloads are transient, so keeping this on the job is required for retry
    # and for explaining why a URL was filtered a particular way.
    options: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    max_retries: Mapped[int] = mapped_column(SmallInteger, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admission_key: Mapped[str | None] = mapped_column(Text)
    admission_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    admission_ticket: Mapped[int | None] = mapped_column(
        BigInteger,
        server_default=text("nextval('download_admission_ticket_seq')"),
    )
    gallery_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="SET NULL"), nullable=True
    )
    subscription_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    # ADR 0022: persona_id is the persona the job last claimed with. It is kept
    # as the sticky preference for retries, even across a later direct claim.
    # persona_name is the snapshot for the current run's display and is cleared
    # by a direct claim.
    persona_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("egress_personas.id", ondelete="SET NULL"), nullable=True
    )
    persona_name: Mapped[str | None] = mapped_column(Text)
    # How this job fetches (services/download_mode.py). Decided at enqueue and
    # never at run time, so retries and recovery replay the same mode.
    mode: Mapped[str] = mapped_column(Text, nullable=False, default="download", server_default=text("'download'"))
    # Durable "stop and keep" intent. The status stays active until the worker
    # (or finalize_stopped_job) finishes the keep path.
    stop_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReadEvent(Base):
    __tablename__ = "read_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    gallery_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), nullable=False)
    image_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("images.id", ondelete="SET NULL"), nullable=True
    )
    page_num: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GallerySourceItem(Base):
    """A source-native work/chapter contained inside one gallery."""

    __tablename__ = "gallery_source_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    gallery_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), nullable=False)
    source_item_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_item_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    source_position: Mapped[int | None] = mapped_column(Integer)
    source_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")

    __table_args__ = (UniqueConstraint("gallery_id", "source_item_id", name="uq_gallery_source_item"),)


class Credential(Base):
    __tablename__ = "credentials"
    __table_args__ = (
        # At most one active account per source; see ADR 0019.
        Index(
            "uq_credentials_active_per_source",
            "source",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active"),
        ),
    )

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    account: Mapped[str] = mapped_column(Text, primary_key=True, server_default=text("'default'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    credential_type: Mapped[str] = mapped_column(Text, nullable=False)
    value_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EgressPersona(Base):
    """A fixed download identity: egress proxy + browser identity (ADR 0022)."""

    __tablename__ = "egress_personas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    proxy_url: Mapped[str | None] = mapped_column(Text)  # None = direct (host default route)
    user_agent: Mapped[str | None] = mapped_column(Text)
    browser_profile: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_exit_ip: Mapped[str | None] = mapped_column(Text)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PersonaAccount(Base):
    """Binds one credential account of a site to exactly one persona."""

    __tablename__ = "persona_accounts"
    __table_args__ = (
        UniqueConstraint("source", "account", name="uq_persona_accounts_account"),
        ForeignKeyConstraint(
            ["source", "account"],
            ["credentials.source", "credentials.account"],
            ondelete="CASCADE",
            name="fk_persona_accounts_credential",
        ),
    )

    persona_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("egress_personas.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    account: Mapped[str] = mapped_column(Text, nullable=False)


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
