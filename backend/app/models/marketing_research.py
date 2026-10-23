"""Research signals and the swipe file (studio plan phase 2, migration 175). Both tenant tables with RLS."""
from sqlalchemy import JSON, Column, Date, Float, ForeignKey, Index, String, Text, UniqueConstraint

from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class MarketingSignal(Base, TimestampMixin):
    """One observation from an outside source on one day: a Google trend, a news item, a YouTube video, a competitor's
    Places rating, a keyword's monthly volume, a hashtag's top post, a trending audio, a competitor ad.
    evidence = own | platform | google (the plan's three kinds of evidence)."""
    __tablename__ = "marketing_signals"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    source = Column(String(20), nullable=False)        # google_trends | google_news | youtube | places | keywords | hashtag | audio | ad_library
    evidence = Column(String(10), nullable=False)      # own | platform | google
    key = Column(String(200), nullable=False)          # stable id within the source (url, place id, keyword, audio id ...)
    title = Column(Text, nullable=True)
    url = Column(Text, nullable=True)
    value = Column(Float, nullable=True)               # traffic, views, rating count, searches, likes+comments ...
    data = Column(JSON, nullable=True)
    query = Column(String(200), nullable=True)         # what was asked (destination, competitor, hashtag)
    observed_on = Column(Date, nullable=False)

    __table_args__ = (UniqueConstraint("tenant_id", "source", "key", "observed_on", name="uq_marketing_signals_day"),
                      Index("ix_marketing_signals_tenant_source_day", "tenant_id", "source", "observed_on"))


class MarketingSwipeItem(Base, TimestampMixin):
    """A proven hook / shot pattern read from a Reel (competitor or own): what the video does in its first seconds,
    its shots, text, CTA and pacing (cut times by ffmpeg, the rest by the vision model), with the source link."""
    __tablename__ = "marketing_swipe_items"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    evidence = Column(String(10), nullable=False, default="platform")
    competitor_post_id = Column(String, nullable=True, index=True)
    source_url = Column(Text, nullable=True)
    status = Column(String(12), nullable=False, default="pending")    # pending | ready | failed
    reading = Column(JSON, nullable=True)              # hook_text, hook_type, format, shots, text_on_screen, cta
    cut_times = Column(JSON, nullable=True)            # seconds, from ffmpeg scene detection
    pacing = Column(String(10), nullable=True)         # fast | medium | slow (cuts per second, code)
    error = Column(Text, nullable=True)
    model = Column(String(120), nullable=True)
    prompt_version = Column(String(60), nullable=True)
