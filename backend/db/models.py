"""ORM models. Related models live in the ``db.models_*`` modules and are re-exported here."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    ForeignKey,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime

from core.database import Base
from db.models_collections import Collection as Collection
from db.models_collections import CollectionGallery as CollectionGallery
from db.models_collections import Dataset as Dataset
from db.models_collections import DatasetImage as DatasetImage
from db.models_collections import ExcludedBlob as ExcludedBlob
from db.models_collections import GalleryMetadataChange as GalleryMetadataChange
from db.models_collections import GalleryMetadataFieldState as GalleryMetadataFieldState
from db.models_collections import GalleryPermission as GalleryPermission
from db.models_collections import GalleryShareLink as GalleryShareLink
from db.models_collections import GalleryVersion as GalleryVersion
from db.models_collections import ImportConflict as ImportConflict
from db.models_collections import WorkbenchOperation as WorkbenchOperation
from db.models_downloads import ApiToken as ApiToken
from db.models_downloads import Credential as Credential
from db.models_downloads import DownloadJob as DownloadJob
from db.models_downloads import EgressPersona as EgressPersona
from db.models_downloads import GallerySourceItem as GallerySourceItem
from db.models_downloads import PersonaAccount as PersonaAccount
from db.models_downloads import ReadEvent as ReadEvent
from db.models_gallery import Blob as Blob
from db.models_gallery import BlobLocation as BlobLocation
from db.models_gallery import BlobRelationship as BlobRelationship
from db.models_gallery import Gallery as Gallery
from db.models_gallery import GalleryTag as GalleryTag
from db.models_gallery import Image as Image
from db.models_gallery import ReadProgress as ReadProgress
from db.models_gallery import Tag as Tag
from db.models_gallery import TagAlias as TagAlias
from db.models_gallery import TagImplication as TagImplication
from db.models_userdata import DEFAULT_SUBSCRIPTION_CRON as DEFAULT_SUBSCRIPTION_CRON
from db.models_userdata import BlockedTag as BlockedTag
from db.models_userdata import BrowseHistory as BrowseHistory
from db.models_userdata import GalleryCategory as GalleryCategory
from db.models_userdata import LibraryPath as LibraryPath
from db.models_userdata import PluginConfig as PluginConfig
from db.models_userdata import SavedSearch as SavedSearch
from db.models_userdata import SiteConfig as SiteConfig
from db.models_userdata import Subscription as Subscription
from db.models_userdata import SubscriptionGroup as SubscriptionGroup
from db.models_userdata import TagTranslation as TagTranslation
from db.models_userdata import UserFavorite as UserFavorite
from db.models_userdata import UserImageFavorite as UserImageFavorite
from db.models_userdata import UserRating as UserRating
from db.models_userdata import UserReadingList as UserReadingList


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
