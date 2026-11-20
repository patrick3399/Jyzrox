"""Gallery, blob, image, tag and reading-progress models."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime

from core.database import Base

_rel = relationship  # alias to avoid shadowing by BlobRelationship.relationship column


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
    # mtime of source_path at the last clean link sync; NULL forces a full diff.
    source_dir_mtime_ns: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    merged_into_gallery_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="SET NULL"), nullable=True
    )
    metadata_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Maintained by a PG trigger that sets it to now() whenever ``pages`` increases.
    # No server_onupdate: expiring it on every UPDATE makes serializers lazy-load
    # it after commit, which raises in async sessions.
    content_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    images: Mapped[list[Image]] = relationship(back_populates="gallery", cascade="all, delete-orphan")
    gallery_tags: Mapped[list[GalleryTag]] = relationship(back_populates="gallery", cascade="all, delete-orphan")
    read_progress: Mapped[list[ReadProgress]] = relationship(back_populates="gallery", cascade="all, delete-orphan")


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
    # NULL while a link page is pending: registered from the folder, not hashed yet (ADR 0015).
    blob_sha256: Mapped[str | None] = mapped_column(Text, ForeignKey("blobs.sha256"), nullable=True)
    external_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # stat fingerprint of external_path when blob_sha256 was computed (link mode).
    source_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_mtime_ns: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
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
    blob: Mapped[Blob | None] = relationship()


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
