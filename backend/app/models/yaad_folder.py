"""Yaad folders (migration 205, services/personal_folders.py): the person's own groups of calls.

A folder is made only by the person: name, keywords, and a sorting prompt in their own words. Summarised calls are filed
automatically when the keywords or prompt match (source "auto"), or by hand (source "manual"). A call the person takes out
keeps its row with excluded=True, so automatic sorting never puts it back.
"""

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, ForeignKey, String, Text, UniqueConstraint

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class YaadFolder(Base, TimestampMixin, TenantMixin):
    __tablename__ = "yaad_folders"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    color = Column(String(20), nullable=False, default="mango")
    keywords = Column(JSON, nullable=False, default=list)
    prompt = Column(Text, nullable=False, default="")
    created_by = Column(String, ForeignKey("users.id"), nullable=True)


class YaadFolderCall(Base, TimestampMixin, TenantMixin):
    __tablename__ = "yaad_folder_calls"
    __table_args__ = (UniqueConstraint("folder_id", "call_id", name="uq_yaad_folder_calls_folder_call"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    folder_id = Column(String, ForeignKey("yaad_folders.id", ondelete="CASCADE"), nullable=False, index=True)
    call_id = Column(String, ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String(10), nullable=False, default="auto")  # auto | manual
    excluded = Column(Boolean, nullable=False, default=False)


class YaadEvent(Base, TimestampMixin, TenantMixin):
    """Yaad calendar event (migration 206, services/personal_calendar.py). status suggested | accepted | dismissed."""

    __tablename__ = "yaad_events"
    __table_args__ = (UniqueConstraint("tenant_id", "source_key", name="uq_yaad_events_tenant_source"),)

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    title = Column(String(160), nullable=False)
    day = Column(Date, nullable=False)
    start_time = Column(String(5), nullable=True)  # HH:MM, none = all day
    place = Column(String(160), nullable=False, default="")
    notes = Column(Text, nullable=False, default="")
    people = Column(JSON, nullable=False, default=list)  # [{name, role}]: the stakeholders
    status = Column(String(12), nullable=False, default="accepted")
    call_id = Column(String, ForeignKey("calls.id", ondelete="SET NULL"), nullable=True)
    source_ref = Column(JSON, nullable=True)  # {at, quote}: the moment on the call this plan was said
    source_key = Column(String(64), nullable=True)  # one per call plan: a re-read never duplicates a suggestion
    google = Column(Boolean, nullable=False, default=False)  # the person wants it in Google Calendar
    google_event_id = Column(String(255), nullable=True)
    google_synced_at = Column(DateTime(timezone=True), nullable=True)
    google_error = Column(String(300), nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)


class YaadAsk(Base, TimestampMixin, TenantMixin):
    """One Ask Yaad chat (a session): its questions and answers, newest turn last. `folder_id` = asked inside a folder
    (answers only from that folder's calls)."""

    __tablename__ = "yaad_asks"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    folder_id = Column(String, ForeignKey("yaad_folders.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(160), nullable=False)
    # [{id, at, question, answer, sources: [{n, call_id, title, contact, at, t, quote}], followups: [str]}]
    turns = Column(JSON, nullable=False, default=list)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
