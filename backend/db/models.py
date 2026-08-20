import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

_rel = relationship  # alias to avoid shadowing by BlobRelationship.relationship column
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime

from core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    avatar_style: Mapped[str] = mapped_column(Text, default="gravatar")
    # NULL means follow the language preferences of the current browser/device.
    locale: Mapped[str | None] = mapped_column(Text, nullable=True)
    novel_prefs: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    ui_preferences: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False, server_default=text("'{}'::jsonb")
    )


class NovelReadProgress(Base):
    __tablename__ = "novel_read_progress"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    file_path: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ── Novel knowledge index (Phase 1 Track A; derived, rebuildable from the tree) ──
# PG-native array/json columns carry a `sqlite` variant so the ORM round-trips
# plain Python lists/dicts on the in-memory test engine too.
class NovelNote(Base):
    __tablename__ = "novel_notes"

    file_path: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    note_type: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list] = mapped_column(
        ARRAY(Text).with_variant(JSON, "sqlite"), nullable=False, server_default=text("'{}'::text[]")
    )
    frontmatter: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False, server_default=text("'{}'::jsonb")
    )
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class NovelLink(Base):
    __tablename__ = "novel_links"

    src_path: Mapped[str] = mapped_column(Text, primary_key=True)
    dst_title: Mapped[str] = mapped_column(Text, primary_key=True)
    dst_path: Mapped[str | None] = mapped_column(Text)


class NovelMention(Base):
    __tablename__ = "novel_mentions"

    note_path: Mapped[str] = mapped_column(Text, primary_key=True)
    chapter_path: Mapped[str] = mapped_column(Text, primary_key=True)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_offset: Mapped[int] = mapped_column(Integer, nullable=False)


class Gallery(Base):
    __tablename__ = "galleries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    title_jpn: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[int | None] = mapped_column(Integer)
    source_pages: Mapped[int | None] = mapped_column(Integer)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rating: Mapped[int] = mapped_column(SmallInteger, default=0)
    favorited: Mapped[bool] = mapped_column(Boolean, default=False)
    uploader: Mapped[str | None] = mapped_column(Text)
    download_status: Mapped[str] = mapped_column(Text, default="proxy_only")
    import_mode: Mapped[str | None] = mapped_column(Text)
    tags_array: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    library_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    artist_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    visibility: Mapped[str] = mapped_column(Text, default="public", server_default="public")
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    images: Mapped[list[Image]] = relationship(back_populates="gallery", cascade="all, delete-orphan")
    gallery_tags: Mapped[list[GalleryTag]] = relationship(back_populates="gallery", cascade="all, delete-orphan")
    read_progress: Mapped[list[ReadProgress]] = relationship(back_populates="gallery", cascade="all, delete-orphan")


class GalleryMetadataFieldState(Base):
    """Ownership and source-refresh state for an editable gallery field."""

    __tablename__ = "gallery_metadata_field_states"

    gallery_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True
    )
    field_name: Mapped[str] = mapped_column(Text, primary_key=True)
    origin: Mapped[str] = mapped_column(Text, nullable=False, default="source", server_default="source")
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    source_value: Mapped[object | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GalleryMetadataChange(Base):
    """Append-only scalar metadata history used by the Workbench inspector."""

    __tablename__ = "gallery_metadata_changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    gallery_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_name: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[object | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    new_value: Mapped[object | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    operation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workbench_operations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class WorkbenchOperation(Base):
    """Durable status and summary for bulk edits and destructive operations."""

    __tablename__ = "workbench_operations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued", server_default="queued")
    selection_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    progress: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    params: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Blob(Base):
    __tablename__ = "blobs"

    sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, default="image")
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[float | None] = mapped_column(Float)
    phash: Mapped[str | None] = mapped_column(Text)
    phash_int: Mapped[int | None] = mapped_column(BigInteger)
    phash_q0: Mapped[int | None] = mapped_column(SmallInteger)
    phash_q1: Mapped[int | None] = mapped_column(SmallInteger)
    phash_q2: Mapped[int | None] = mapped_column(SmallInteger)
    phash_q3: Mapped[int | None] = mapped_column(SmallInteger)
    dedup_scanned_threshold: Mapped[int | None] = mapped_column(SmallInteger)
    dedup_scanned_phash_int: Mapped[int | None] = mapped_column(BigInteger)
    dedup_scanned_version: Mapped[int | None] = mapped_column(SmallInteger)
    occurrence_revision: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    extension: Mapped[str] = mapped_column(Text, nullable=False)
    storage: Mapped[str] = mapped_column(Text, default="cas")
    # Compatibility fallback only. Image.external_path + BlobLocation are the
    # authoritative external-location binding (HR-004 / ADR 0007).
    external_path: Mapped[str | None] = mapped_column(Text)
    ref_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    thumbhash: Mapped[str | None] = mapped_column(Text, nullable=True)


class BlobLocation(Base):
    """One external filesystem location containing a blob's bytes."""

    __tablename__ = "blob_locations"

    blob_sha256: Mapped[str] = mapped_column(
        Text,
        ForeignKey("blobs.sha256", ondelete="CASCADE"),
        primary_key=True,
    )
    external_path: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Image(Base):
    __tablename__ = "images"
    __table_args__ = (
        ForeignKeyConstraint(
            ["blob_sha256", "external_path"],
            ["blob_locations.blob_sha256", "blob_locations.external_path"],
            name="fk_images_blob_location",
        ),
        Index("idx_images_external_path", "external_path", postgresql_where=text("external_path IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    gallery_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), nullable=False)
    page_num: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str | None] = mapped_column(Text)
    blob_sha256: Mapped[str] = mapped_column(Text, ForeignKey("blobs.sha256"), nullable=False)
    external_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_array: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    visibility: Mapped[str] = mapped_column(Text, default="active", server_default="active", nullable=False)
    source_item_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_item_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_image_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("images.id", ondelete="SET NULL"), nullable=True
    )
    source_item_row_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("gallery_source_items.id", ondelete="SET NULL"), nullable=True
    )

    gallery: Mapped[Gallery] = relationship(back_populates="images")
    blob: Mapped[Blob] = relationship()
    image_tags: Mapped[list[ImageTag]] = relationship(back_populates="image", cascade="all, delete-orphan")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0)


class TagAlias(Base):
    __tablename__ = "tag_aliases"

    alias_namespace: Mapped[str] = mapped_column(Text, primary_key=True)
    alias_name: Mapped[str] = mapped_column(Text, primary_key=True)
    canonical_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)

    canonical: Mapped[Tag] = relationship()


class TagImplication(Base):
    __tablename__ = "tag_implications"

    antecedent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    consequent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)

    antecedent: Mapped[Tag] = relationship(foreign_keys=[antecedent_id])
    consequent: Mapped[Tag] = relationship(foreign_keys=[consequent_id])


class GalleryTag(Base):
    __tablename__ = "gallery_tags"

    gallery_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tags.id"), primary_key=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(Text, default="metadata")

    gallery: Mapped[Gallery] = relationship(back_populates="gallery_tags")
    tag: Mapped[Tag] = relationship()


class ImageTag(Base):
    __tablename__ = "image_tags"

    image_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("images.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tags.id"), primary_key=True)
    confidence: Mapped[float | None] = mapped_column(Float)

    image: Mapped[Image] = relationship(back_populates="image_tags")
    tag: Mapped[Tag] = relationship()


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


class ReadProgress(Base):
    __tablename__ = "read_progress"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    gallery_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True
    )
    last_page: Mapped[int] = mapped_column(Integer, default=0)
    last_image_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("images.id", ondelete="SET NULL"), nullable=True
    )
    last_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    gallery: Mapped[Gallery] = relationship(back_populates="read_progress")


class ReadEvent(Base):
    __tablename__ = "read_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    gallery_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), nullable=False
    )
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

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    credential_type: Mapped[str] = mapped_column(Text, nullable=False)
    value_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BrowseHistory(Base):
    __tablename__ = "browse_history"
    __table_args__ = (UniqueConstraint("user_id", "source", "source_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    thumb: Mapped[str | None] = mapped_column(Text)
    gid: Mapped[int | None] = mapped_column(BigInteger)
    token: Mapped[str | None] = mapped_column(Text)
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TagTranslation(Base):
    __tablename__ = "tag_translations"
    __table_args__ = (UniqueConstraint("namespace", "name", "language"),)

    namespace: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    language: Mapped[str] = mapped_column(Text, primary_key=True, default="zh")
    translation: Mapped[str] = mapped_column(Text, nullable=False)


class BlockedTag(Base):
    __tablename__ = "blocked_tags"
    __table_args__ = (UniqueConstraint("user_id", "namespace", "name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    namespace: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class LibraryPath(Base):
    __tablename__ = "library_paths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    pattern: Mapped[str] = mapped_column(Text, default="{title}", server_default="{title}", nullable=False)
    import_mode: Mapped[str] = mapped_column(Text, default="link", server_default="link", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    monitor: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PluginConfig(Base):
    __tablename__ = "plugin_config"

    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SubscriptionGroup(Base):
    __tablename__ = "subscription_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    schedule: Mapped[str] = mapped_column(Text, nullable=False, default="0 */6 * * *")
    concurrency: Mapped[int] = mapped_column(SmallInteger, default=2)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(SmallInteger, default=5)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(Text, default="idle")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_download: Mapped[bool] = mapped_column(Boolean, default=True)
    # Source-specific download policy. Credentials remain global; this controls
    # what this subscription chooses to fetch with those credentials.
    download_options: Mapped[dict] = mapped_column(JSONB, default=dict)
    cron_expr: Mapped[str | None] = mapped_column(Text, default="0 */2 * * *")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_item_id: Mapped[str | None] = mapped_column(Text)
    last_status: Mapped[str] = mapped_column(Text, default="pending")
    last_error: Mapped[str | None] = mapped_column(Text)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    batch_total: Mapped[int] = mapped_column(Integer, default=0)
    batch_enqueued: Mapped[int] = mapped_column(Integer, default=0)
    group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("subscription_groups.id", ondelete="SET NULL"), nullable=True
    )
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("download_jobs.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (UniqueConstraint("user_id", "url", name="uq_subscription_user_url"),)


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    cover_gallery_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("galleries.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cover_gallery: Mapped[Gallery | None] = relationship()
    collection_galleries: Mapped[list[CollectionGallery]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )


class CollectionGallery(Base):
    __tablename__ = "collection_galleries"

    collection_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    gallery_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    collection: Mapped[Collection] = relationship(back_populates="collection_galleries")
    gallery: Mapped[Gallery] = relationship()


class Dataset(Base):
    """A user-owned, persistent image selection for model training/export."""

    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    selection_spec: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    dataset_images: Mapped[list[DatasetImage]] = relationship(back_populates="dataset", cascade="all, delete-orphan")


class DatasetImage(Base):
    """Durable image membership, including explicit exclusions."""

    __tablename__ = "dataset_images"

    dataset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True)
    image_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("images.id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="included", server_default="included")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual", server_default="manual")
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    dataset: Mapped[Dataset] = relationship(back_populates="dataset_images")
    image: Mapped[Image] = relationship()


class LoraModel(Base):
    __tablename__ = "lora_models"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    dataset_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_words: Mapped[list[str]] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    training_params: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GeneratedImageMetadata(Base):
    __tablename__ = "generated_image_metadata"

    image_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("images.id", ondelete="CASCADE"), primary_key=True
    )
    prompt_json: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    workflow_json: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GalleryPermission(Base):
    __tablename__ = "gallery_permissions"

    gallery_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    can_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GalleryShareLink(Base):
    __tablename__ = "gallery_share_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    gallery_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filter_r18: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GalleryVersion(Base):
    __tablename__ = "gallery_versions"

    gallery_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[str] = mapped_column(Text, nullable=False)
    linked_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ImportConflict(Base):
    __tablename__ = "import_conflicts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    existing_gallery_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    incoming_payload: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExcludedBlob(Base):
    __tablename__ = "excluded_blobs"

    gallery_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True
    )
    blob_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    excluded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BlobRelationship(Base):
    __tablename__ = "blob_relationships"
    __table_args__ = (UniqueConstraint("sha_a", "sha_b", name="uq_blob_pair"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sha_a: Mapped[str] = mapped_column(Text, ForeignKey("blobs.sha256", ondelete="CASCADE"))
    sha_b: Mapped[str] = mapped_column(Text, ForeignKey("blobs.sha256", ondelete="CASCADE"))
    hamming_dist: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    relationship: Mapped[str] = mapped_column(Text, nullable=False, default="needs_context")
    suggested_keep: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    diff_score: Mapped[float | None] = mapped_column(Float)
    diff_type: Mapped[str | None] = mapped_column(Text)
    context_scope: Mapped[str | None] = mapped_column(Text)
    context_revision_a: Mapped[int | None] = mapped_column(BigInteger)
    context_revision_b: Mapped[int | None] = mapped_column(BigInteger)
    decision: Mapped[str | None] = mapped_column(Text)
    decision_keep_sha: Mapped[str | None] = mapped_column(Text)
    decision_by_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tier: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    blob_a: Mapped[Blob] = _rel(foreign_keys="[BlobRelationship.sha_a]")
    blob_b: Mapped[Blob] = _rel(foreign_keys="[BlobRelationship.sha_b]")


class UserFavorite(Base):
    __tablename__ = "user_favorites"
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    gallery_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserImageFavorite(Base):
    __tablename__ = "user_image_favorites"
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    image_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("images.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserRating(Base):
    __tablename__ = "user_ratings"
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    gallery_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserReadingList(Base):
    __tablename__ = "user_reading_list"
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    gallery_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SiteConfig(Base):
    __tablename__ = "site_configs"

    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    overrides: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    adaptive: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    auto_probe: Mapped[dict | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
