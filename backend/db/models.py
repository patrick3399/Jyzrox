import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime

from core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, default="admin")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    avatar_style: Mapped[str] = mapped_column(Text, default="gravatar")
    locale: Mapped[str] = mapped_column(Text, default="en")


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
    posted_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    added_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rating: Mapped[int] = mapped_column(SmallInteger, default=0)
    favorited: Mapped[bool] = mapped_column(Boolean, default=False)
    uploader: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("galleries.id"))
    download_status: Mapped[str] = mapped_column(Text, default="proxy_only")
    import_mode: Mapped[str | None] = mapped_column(Text)
    tags_array: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    last_scanned_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    library_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    artist_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)

    images: Mapped[list["Image"]] = relationship(back_populates="gallery", cascade="all, delete-orphan")
    gallery_tags: Mapped[list["GalleryTag"]] = relationship(back_populates="gallery", cascade="all, delete-orphan")
    read_progress: Mapped["ReadProgress | None"] = relationship(back_populates="gallery", cascade="all, delete-orphan")


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
    extension: Mapped[str] = mapped_column(Text, nullable=False)
    storage: Mapped[str] = mapped_column(Text, default="cas")
    external_path: Mapped[str | None] = mapped_column(Text)
    ref_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Image(Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    gallery_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), nullable=False)
    page_num: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str | None] = mapped_column(Text)
    blob_sha256: Mapped[str] = mapped_column(Text, ForeignKey("blobs.sha256"), nullable=False)
    tags_array: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)

    gallery: Mapped["Gallery"] = relationship(back_populates="images")
    blob: Mapped["Blob"] = relationship()
    image_tags: Mapped[list["ImageTag"]] = relationship(back_populates="image", cascade="all, delete-orphan")


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

    canonical: Mapped["Tag"] = relationship()


class TagImplication(Base):
    __tablename__ = "tag_implications"

    antecedent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    consequent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)

    antecedent: Mapped["Tag"] = relationship(foreign_keys=[antecedent_id])
    consequent: Mapped["Tag"] = relationship(foreign_keys=[consequent_id])


class GalleryTag(Base):
    __tablename__ = "gallery_tags"

    gallery_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tags.id"), primary_key=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(Text, default="metadata")

    gallery: Mapped["Gallery"] = relationship(back_populates="gallery_tags")
    tag: Mapped["Tag"] = relationship()


class ImageTag(Base):
    __tablename__ = "image_tags"

    image_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("images.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tags.id"), primary_key=True)
    confidence: Mapped[float | None] = mapped_column(Float)

    image: Mapped["Image"] = relationship(back_populates="image_tags")
    tag: Mapped["Tag"] = relationship()


class DownloadJob(Base):
    __tablename__ = "download_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="queued")
    progress: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))


class ReadProgress(Base):
    __tablename__ = "read_progress"

    gallery_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True)
    last_page: Mapped[int] = mapped_column(Integer, default=0)
    last_read_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    gallery: Mapped["Gallery"] = relationship(back_populates="read_progress")


class Credential(Base):
    __tablename__ = "credentials"

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    credential_type: Mapped[str] = mapped_column(Text, nullable=False)
    value_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    expires_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    last_verified: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    token_plain: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))


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
    viewed_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    monitor: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    added_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PluginConfig(Base):
    __tablename__ = "plugin_config"

    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FollowedArtist(Base):
    __tablename__ = "followed_artists"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # "pixiv", "ehentai", etc.
    artist_id: Mapped[str] = mapped_column(Text, nullable=False)  # external artist ID
    artist_name: Mapped[str | None] = mapped_column(Text)
    artist_avatar: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_illust_id: Mapped[str | None] = mapped_column(Text)  # last known illust ID for delta checks
    auto_download: Mapped[bool] = mapped_column(Boolean, server_default="false")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "source", "artist_id", name="uq_followed_artist"),
    )


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    cover_gallery_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("galleries.id", ondelete="SET NULL"))
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cover_gallery: Mapped["Gallery | None"] = relationship()
    collection_galleries: Mapped[list["CollectionGallery"]] = relationship(back_populates="collection", cascade="all, delete-orphan")


class CollectionGallery(Base):
    __tablename__ = "collection_galleries"

    collection_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)
    gallery_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    collection: Mapped["Collection"] = relationship(back_populates="collection_galleries")
    gallery: Mapped["Gallery"] = relationship()
