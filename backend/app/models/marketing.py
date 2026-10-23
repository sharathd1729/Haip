"""Marketing Studio tables (docs/marketing-website/PHASE0_AUDIT.md §7.3).

Measured provider data and AI assessment are stored in separate columns so they can never be confused in the UI.
A content version is immutable: an edit is a new version, and an approval is bound to one version's sha256.
"""
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class MarketingAudit(Base, TimestampMixin):
    """A social audit: a frozen copy of the measured metrics plus the AI's reading of them."""
    __tablename__ = "marketing_audits"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    channel = Column(String(20), nullable=False, default="instagram")
    measured = Column(JSON, nullable=False)          # provider numbers, with source + captured_at; never AI-written
    assessment = Column(JSON, nullable=True)         # AuditAssessment; AI-written, labelled as such
    status = Column(String(20), nullable=False, default="pending")   # pending | ready | failed
    error = Column(Text, nullable=True)
    prompt_version = Column(String(60), nullable=True)
    model = Column(String(120), nullable=True)
    created_by = Column(String, nullable=True)


class MarketingPlan(Base, TimestampMixin):
    """A strategy + content calendar generated from the profile and (optionally) an audit."""
    __tablename__ = "marketing_plans"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    audit_id = Column(String, nullable=True)
    period_start = Column(String(10), nullable=False)    # YYYY-MM-DD
    period_end = Column(String(10), nullable=False)
    brief = Column(Text, nullable=True)
    body = Column(JSON, nullable=True)                   # MarketingPlanBody
    status = Column(String(20), nullable=False, default="pending")   # pending | ready | failed | archived
    error = Column(Text, nullable=True)
    prompt_version = Column(String(60), nullable=True)
    model = Column(String(120), nullable=True)
    created_by = Column(String, nullable=True)


class MarketingContent(Base, TimestampMixin):
    """One piece of content (post, carousel, story, promo) and its review state."""
    __tablename__ = "marketing_content"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    channel = Column(String(20), nullable=False, default="instagram")
    targets = Column(JSON, nullable=True)            # channels to publish to (agency M3); None = ["instagram"]
    title = Column(String(160), nullable=False)
    property_id = Column(String, nullable=True)
    plan_id = Column(String, nullable=True)
    planned_for = Column(String(10), nullable=True)      # YYYY-MM-DD from the calendar; not a publish schedule
    status = Column(String(20), nullable=False, default="draft")              # schemas.marketing.ITEM_STATUSES
    current_version_id = Column(String, nullable=True)
    approved_version_id = Column(String, nullable=True)
    approved_sha256 = Column(String(64), nullable=True)
    generation_status = Column(String(20), nullable=False, default="idle")    # idle | pending | failed
    generation_error = Column(Text, nullable=True)
    created_by = Column(String, nullable=True)

    __table_args__ = (Index("ix_marketing_content_tenant_status", "tenant_id", "status"),)


class MarketingContentVersion(Base):
    """Immutable. Never updated after insert."""
    __tablename__ = "marketing_content_versions"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    content_id = Column(String, ForeignKey("marketing_content.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    sha256 = Column(String(64), nullable=False)
    origin = Column(String(10), nullable=False)          # ai | human
    note = Column(Text, nullable=True)
    prompt_version = Column(String(60), nullable=True)
    model = Column(String(120), nullable=True)
    created_by = Column(String, nullable=True)           # the person who wrote it, or who asked the AI for it
    created_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("content_id", "version", name="uq_marketing_content_versions_n"),)


class MarketingApproval(Base):
    """Every review decision, bound to the exact version and hash that was seen."""
    __tablename__ = "marketing_approvals"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    content_id = Column(String, ForeignKey("marketing_content.id"), nullable=False, index=True)
    version_id = Column(String, nullable=False)
    sha256 = Column(String(64), nullable=False)
    decision = Column(String(20), nullable=False)        # submitted | approved | rejected | withdrawn
    note = Column(Text, nullable=True)
    actor_user_id = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class MarketingImageJob(Base, TimestampMixin):
    """One AI image request (opt-in per tenant). On success the image becomes a media_assets row with
    source='ai' and status='pending_review': it cannot be used in content until someone with marketing.approve approves it."""
    __tablename__ = "marketing_image_jobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    prompt = Column(Text, nullable=False)
    model = Column(String(60), nullable=False)
    shape = Column(String(20), nullable=False)
    seed = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="pending")   # pending | ready | failed
    error = Column(Text, nullable=True)
    asset_id = Column(String, nullable=True)
    content_id = Column(String, nullable=True)      # the draft it was made for: filled into its empty slot once approved
    created_by = Column(String, nullable=True)


class MarketingTask(Base, TimestampMixin):
    """Run log of the AI agency: one row per step a role performed (or skipped), grouped by run_id.

    Output lives in the domain tables (audits, plans, content, image jobs); this row points at it (ref_type/ref_id)
    and records status, error and cost, so a weekly run that stops half-way shows exactly where and why."""
    __tablename__ = "marketing_tasks"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    run_id = Column(String, nullable=True, index=True)
    role = Column(String(30), nullable=False)          # services.marketing_agency_service.ROLES
    step = Column(String(40), nullable=False)          # run | audit | plan | draft | image | submit | ...
    status = Column(String(20), nullable=False, default="queued")   # queued|running|done|failed|skipped|needs_approval
    trigger = Column(String(20), nullable=False, default="schedule")  # schedule | manual
    ref_type = Column(String(40), nullable=True)
    ref_id = Column(String, nullable=True)
    detail = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String, nullable=True)

    __table_args__ = (Index("ix_marketing_tasks_tenant_created", "tenant_id", "created_at"),)


class InstagramPostMetricDaily(Base, TimestampMixin):
    """One row per post per day, appended by the insights poller, so post performance has a history
    (instagram_post_snapshots is overwritten in place)."""
    __tablename__ = "instagram_post_metrics_daily"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    media_id = Column(String(100), nullable=False)
    day = Column(String(10), nullable=False)            # YYYY-MM-DD in the workspace timezone
    media_type = Column(String(20), nullable=True)
    posted_at = Column(String(50), nullable=True)
    like_count = Column(Integer, nullable=True)
    comments_count = Column(Integer, nullable=True)
    reach = Column(Integer, nullable=True)
    saved = Column(Integer, nullable=True)
    shares = Column(Integer, nullable=True)
    total_interactions = Column(Integer, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "media_id", "day", name="uq_ig_post_metrics_daily"),)


class MarketingCompetitor(Base, TimestampMixin):
    __tablename__ = "marketing_competitors"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    handle = Column(String(31), nullable=False)
    display_name = Column(String(120), nullable=True)
    notes = Column(Text, nullable=True)
    active = Column(Integer, nullable=False, default=1)
    created_by = Column(String, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "handle", name="uq_marketing_competitors_handle"),)


class MarketingCompetitorSnapshot(Base, TimestampMixin):
    """Public account numbers from Business Discovery (source=api). Deleted when the Facebook connection is removed."""
    __tablename__ = "marketing_competitor_snapshots"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    competitor_id = Column(String, ForeignKey("marketing_competitors.id"), nullable=False, index=True)
    source = Column(String(10), nullable=False, default="api")
    followers_count = Column(Integer, nullable=True)
    media_count = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)


class MarketingCompetitorPost(Base, TimestampMixin):
    """A competitor post: from Business Discovery (source=api) or pasted by a person (source=manual)."""
    __tablename__ = "marketing_competitor_posts"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    competitor_id = Column(String, ForeignKey("marketing_competitors.id"), nullable=False, index=True)
    source = Column(String(10), nullable=False)
    media_id = Column(String(100), nullable=True)
    permalink = Column(String(300), nullable=True)
    caption = Column(Text, nullable=True)
    media_type = Column(String(20), nullable=True)
    like_count = Column(Integer, nullable=True)
    comments_count = Column(Integer, nullable=True)
    posted_at = Column(String(50), nullable=True)
    note = Column(Text, nullable=True)
    created_by = Column(String, nullable=True)

    __table_args__ = (Index("ix_marketing_competitor_posts_comp_media", "competitor_id", "media_id"),)


class MarketingResearchBrief(Base, TimestampMixin):
    """Research analyst output: measured competitor numbers apart from the AI reading of them."""
    __tablename__ = "marketing_research_briefs"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    measured = Column(JSON, nullable=False)
    assessment = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    error = Column(Text, nullable=True)
    prompt_version = Column(String(60), nullable=True)
    model = Column(String(120), nullable=True)
    created_by = Column(String, nullable=True)


class MarketingPublishAttempt(Base, TimestampMixin):
    """Schedule + publish record for one approved version (agency phase C). Unique per (content, version), so a
    retried or re-delivered job can never post the same version twice; the provider container/media ids are stored
    as soon as they exist so a retry can tell whether Instagram already published."""
    __tablename__ = "marketing_publish_attempts"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    content_id = Column(String, ForeignKey("marketing_content.id"), nullable=False, index=True)
    version_id = Column(String, nullable=False)
    sha256 = Column(String(64), nullable=False)
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), nullable=False, default="scheduled")   # scheduled|publishing|published|failed|cancelled
    channel = Column(String(20), nullable=False, default="instagram")  # instagram | facebook | google (agency M3)
    container_ids = Column(JSON, nullable=True)
    media_ids = Column(JSON, nullable=True)
    permalink = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    tries = Column(Integer, nullable=False, default=0)
    scheduled_by = Column(String, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("content_id", "version_id", "channel", name="uq_marketing_publish_attempts_channel"),
                      Index("ix_marketing_publish_attempts_due", "status", "scheduled_for"))


class MarketingReview(Base, TimestampMixin):
    """Brand review of a draft's TEXT (agency M1). Keyed by the hash of the guest-visible text, so a version that only
    changes photos or the look keeps its review. `findings` = deterministic checks (only these can be `high` and block
    the agency from sending a draft for approval); `advice` = the AI reviewer's opinion, shown to the approver."""
    __tablename__ = "marketing_reviews"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    content_id = Column(String, ForeignKey("marketing_content.id"), nullable=False, index=True)
    version_id = Column(String, nullable=False)                   # the version the review was run on
    text_sha = Column(String(64), nullable=False)
    findings = Column(JSON, nullable=False)                       # list[ReviewFinding]
    blocking = Column(Boolean, nullable=False, default=False)
    advice = Column(JSON, nullable=True)                          # list[ReviewFinding] from the AI reviewer
    summary = Column(Text, nullable=True)
    scores = Column(JSON, nullable=True)                          # critic 1-5: hook, specificity, voice, clarity, ask (M3)
    ai_status = Column(String(20), nullable=False, default="skipped")   # skipped | pending | ready | failed
    ai_error = Column(Text, nullable=True)
    model = Column(String(120), nullable=True)
    prompt_version = Column(String(60), nullable=True)

    __table_args__ = (UniqueConstraint("content_id", "text_sha", name="uq_marketing_reviews_text"),)


class MarketingCreativeJob(Base, TimestampMixin):
    """One request to an outside creative tool (agency M2b): a Canva design filled from a draft, or a Higgsfield clip
    made from library photos. The finished file lands in media_assets (a Canva export as an active photo the owner
    designed; an AI video as pending_review, unusable until approved). The tool's own ids are saved as soon as they
    exist, so a retry polls the same request instead of paying for a new one."""
    __tablename__ = "marketing_creative_jobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    provider = Column(String(20), nullable=False)          # canva | higgsfield
    kind = Column(String(20), nullable=False)              # design | video
    content_id = Column(String, nullable=True)             # the draft a Canva design was filled from
    inputs = Column(JSON, nullable=False)                  # template id + field data, or model + photo ids + prompt
    external_id = Column(String(200), nullable=True)       # Canva design id / Higgsfield request id
    external_url = Column(Text, nullable=True)             # Canva edit link (the owner can open it in Canva)
    idempotency_key = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="pending")   # pending | running | ready | failed
    error = Column(Text, nullable=True)
    asset_id = Column(String, nullable=True)
    polls = Column(Integer, nullable=False, default=0)
    created_by = Column(String, nullable=True)


class MarketingGuestReview(Base, TimestampMixin):
    """A public guest review (Google Business Profile today) and HAIP's reply to it (agency M3).

    The review text is untrusted input. A reply is drafted by AI or a person, approved by someone with
    marketing.approve, then posted; `reply_posted` is what Google shows. Unique per (tenant, source, external_id)."""
    __tablename__ = "marketing_guest_reviews"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    source = Column(String(20), nullable=False, default="google")
    external_id = Column(String(300), nullable=False)
    location = Column(String(200), nullable=True)
    rating = Column(Integer, nullable=True)
    reviewer = Column(String(200), nullable=True)
    comment = Column(Text, nullable=True)
    reviewed_at = Column(String(40), nullable=True)
    reply_status = Column(String(20), nullable=False, default="none")   # none | drafting | draft | approved | posted | failed
    reply_draft = Column(Text, nullable=True)
    reply_origin = Column(String(10), nullable=True)                    # ai | human
    reply_posted = Column(Text, nullable=True)
    reply_error = Column(Text, nullable=True)
    drafted_by = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    posted_at = Column(DateTime(timezone=True), nullable=True)
    # Agency M7: the review turned into a post, only after a person recorded that the guest agreed.
    content_id = Column(String, nullable=True)
    consent_note = Column(String(300), nullable=True)
    consent_by = Column(String, nullable=True)
    consent_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "source", "external_id", name="uq_marketing_guest_reviews_ext"),)


class MarketingNewsletter(Base, TimestampMixin):
    """An email newsletter built from approved posts (agency M3). Sent only by a person with marketing.approve, to
    guests with an email address and recorded marketing consent, minus anyone who unsubscribed from email."""
    __tablename__ = "marketing_newsletters"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    subject = Column(String(200), nullable=False)
    intro = Column(Text, nullable=True)
    content_ids = Column(JSON, nullable=False)              # approved marketing_content ids, in order
    status = Column(String(20), nullable=False, default="draft")   # draft | sending | sent | failed
    created_by = Column(String, nullable=True)
    sent_by = Column(String, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    recipients = Column(Integer, nullable=False, default=0)
    delivered = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)


class MarketingNewsletterRecipient(Base, TimestampMixin):
    """One guest a newsletter goes to. Unique per (newsletter, guest), so a re-run never emails anyone twice."""
    __tablename__ = "marketing_newsletter_recipients"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    newsletter_id = Column(String, ForeignKey("marketing_newsletters.id"), nullable=False, index=True)
    guest_id = Column(String, nullable=False)
    email = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="queued")   # queued | sent | failed | unsubscribed
    error = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("newsletter_id", "guest_id", name="uq_marketing_newsletter_recipient"),)
