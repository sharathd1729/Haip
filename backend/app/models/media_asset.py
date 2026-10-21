"""Tenant media library shared by Marketing Studio (and later the Website Builder).

The file lives in R2 under a tenant-prefixed key (services/media_storage.py); this row is the metadata and provenance.
Read URLs are presigned on demand, never stored. `Property.photos` stays as it is and is not copied here.
"""
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid

ASSET_SOURCES = ("upload", "template", "ai", "instagram")


class MediaAsset(Base, TimestampMixin):
    __tablename__ = "media_assets"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    property_id = Column(String, nullable=True)
    storage_key = Column(String(300), nullable=False)
    mime_type = Column(String(40), nullable=False)
    bytes = Column(Integer, nullable=False)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    sha256 = Column(String(64), nullable=False)
    alt_text = Column(Text, nullable=True)
    source = Column(String(20), nullable=False, default="upload")    # ASSET_SOURCES
    provenance = Column(JSON, nullable=True)                          # template id + inputs, or AI provider/model/prompt version
    created_by = Column(String, nullable=True)
    status = Column(String(20), nullable=False, default="active")     # active | archived | pending_review (AI, unapproved) | derived (rendered for posting)

    # Agency M2 (migration 160): what a vision model saw (schemas.marketing.PhotoTags), and the owner's OK to post a
    # photo that shows people. A photo tagged with people is never picked automatically until people_ok is true.
    tags = Column(JSON, nullable=True)
    tag_model = Column(String(80), nullable=True)
    tagged_at = Column(DateTime(timezone=True), nullable=True)
    people_ok = Column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_media_assets_tenant_sha", "tenant_id", "sha256"),)
