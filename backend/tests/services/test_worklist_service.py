"""Agent worklist tests.

The section that matters most is awaiting_reply -- it is the one the
dashboard previously approximated with `automation_outcome ==
"no_match_no_response"`, which means "no automation replied", not "no human
replied". These pin the real semantics.
"""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity, IdentityType
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.tenant import Tenant
from app.models.user import User
from app.services import worklist_service as ws


def _tenant(db):
    t = Tenant(name="W", slug=f"w-{uuid.uuid4().hex[:8]}")
    db.add(t); db.commit()
    return t


def _valid_inquiry(db, t, g):
    """shared_contact_details now requires a guest's most recent inquiry to
    sit in a `valid`-category pipeline stage -- see worklist_service.py's
    _qualifying_shared_detail_guests. Tests that only care about identity
    picking/dedup need one of these so that filter doesn't interfere.
    Reuses one "active" stage per tenant -- (tenant_id, key) is unique,
    so a second PipelineStage("active") for the same tenant violates it."""
    stage = db.query(PipelineStage).filter_by(tenant_id=t.id, key="active").first()
    if stage is None:
        stage = PipelineStage(tenant_id=t.id, key="active", label="Active", category="valid")
        db.add(stage); db.flush()
    inquiry = Inquiry(tenant_id=t.id, guest_id=g.id, stage_id=stage.id)
    db.add(inquiry); db.commit()
    return inquiry


def _conv(db, t, *, name="Arjun", assigned_to=None):
    g = Guest(tenant_id=t.id, name=name)
    db.add(g); db.flush()
    c = Conversation(
        tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP,
        is_open=True, assigned_to=assigned_to,
    )
    db.add(c); db.commit()
    return g, c


def _msg(db, t, c, direction, *, body="hi", minutes_ago=5, internal=False):
    m = Message(
        tenant_id=t.id, conversation_id=c.id, direction=direction,
        channel=ChannelType.WHATSAPP, body=body, is_internal=internal,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(m); db.commit()
    return m


# ─── awaiting_reply ──────────────────────────────────────────────────────────

def test_guest_last_message_means_awaiting_reply(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND, body="are you there?")
    rows = ws.awaiting_reply(db, t.id)
    assert len(rows) == 1
    assert rows[0]["last_message"] == "are you there?"
    assert rows[0]["lead"]["name"] == "Arjun"


def test_our_reply_clears_it(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND, minutes_ago=10)
    _msg(db, t, c, MessageDirection.OUTBOUND, minutes_ago=2)
    assert ws.awaiting_reply(db, t.id) == []


def test_guest_replying_after_us_reopens_it(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND, minutes_ago=30)
    _msg(db, t, c, MessageDirection.OUTBOUND, minutes_ago=20)
    _msg(db, t, c, MessageDirection.INBOUND, body="one more thing", minutes_ago=5)
    rows = ws.awaiting_reply(db, t.id)
    assert len(rows) == 1
    assert rows[0]["last_message"] == "one more thing"


def test_closed_conversations_are_excluded(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND)
    c.is_open = False
    db.commit()
    assert ws.awaiting_reply(db, t.id) == []


def test_internal_notes_do_not_count_as_a_reply(db):
    """An internal note is never delivered to the guest, so it must not make
    the thread look answered."""
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND, minutes_ago=10)
    _msg(db, t, c, MessageDirection.OUTBOUND, body="note to self", minutes_ago=2, internal=True)
    assert len(ws.awaiting_reply(db, t.id)) == 1


def test_waiting_minutes_is_reported(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND, minutes_ago=90)
    assert ws.awaiting_reply(db, t.id)[0]["waiting_minutes"] >= 89


def test_agent_scope_filters_to_own_conversations(db):
    t = _tenant(db)
    # conversations.assigned_to is a foreign key to users, enforced by PostgreSQL
    me = User(tenant_id=t.id, email="me@ratha.test", name="Me")
    peer = User(tenant_id=t.id, email="peer@ratha.test", name="Peer")
    db.add_all([me, peer]); db.commit()
    _, mine = _conv(db, t, name="Mine", assigned_to=me.id)
    _, theirs = _conv(db, t, name="Theirs", assigned_to=peer.id)
    _msg(db, t, mine, MessageDirection.INBOUND)
    _msg(db, t, theirs, MessageDirection.INBOUND)
    rows = ws.awaiting_reply(db, t.id, scope_user_id=me.id)
    assert [r["lead"]["name"] for r in rows] == ["Mine"]


def test_tenant_isolation(db):
    t1, t2 = _tenant(db), _tenant(db)
    _, c1 = _conv(db, t1, name="T1 lead")
    _, c2 = _conv(db, t2, name="T2 lead")
    _msg(db, t1, c1, MessageDirection.INBOUND)
    _msg(db, t2, c2, MessageDirection.INBOUND)
    assert [r["lead"]["name"] for r in ws.awaiting_reply(db, t1.id)] == ["T1 lead"]


def test_assignee_name_surfaced_so_other_agents_see_who_owns_it(db):
    """A lead self-assigned by one agent must show that agent's name to
    everyone else viewing the worklist -- otherwise a peer's row looks
    unclaimed and still offers "Assign to me" even though the backend
    already rejects that self-assign (automation_engine.py's overlap guard)."""
    t = _tenant(db)
    krisha = User(tenant_id=t.id, email="krisha@ratha.test", name="Krisha")
    db.add(krisha); db.commit()
    g, c = _conv(db, t, name="Prithvi", assigned_to=krisha.id)
    _msg(db, t, c, MessageDirection.INBOUND)
    rows = ws.awaiting_reply(db, t.id)
    assert rows[0]["lead"]["assigned_to"] == krisha.id
    assert rows[0]["lead"]["assigned_agent_name"] == "Krisha"


def test_unassigned_lead_has_no_assignee_name(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND)
    rows = ws.awaiting_reply(db, t.id)
    assert rows[0]["lead"]["assigned_to"] is None
    assert rows[0]["lead"]["assigned_agent_name"] is None


# ─── shared contact details ──────────────────────────────────────────────────

def test_shared_details_picks_up_phone_and_email(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    _valid_inquiry(db, t, g)
    now = datetime.now(timezone.utc)
    for itype, val in ((IdentityType.PHONE.value, "+919876500001"),
                       (IdentityType.EMAIL.value, "a@b.com")):
        db.add(GuestIdentity(
            tenant_id=t.id, guest_id=g.id, identity_type=itype,
            identity_value=val, confidence=0.9, first_seen_at=now,
        ))
    db.commit()
    rows = ws.shared_contact_details(db, t.id, now - timedelta(hours=1))
    assert len(rows) == 1
    assert len(rows[0]["shared"]) == 2


def test_shared_details_ignores_internal_identity_types(db):
    """device_fingerprint isn't something a guest 'shared'."""
    t = _tenant(db)
    g, c = _conv(db, t)
    now = datetime.now(timezone.utc)
    db.add(GuestIdentity(
        tenant_id=t.id, guest_id=g.id,
        identity_type=IdentityType.DEVICE_FINGERPRINT.value,
        identity_value="abc123", confidence=0.3, first_seen_at=now,
    ))
    db.commit()
    assert ws.shared_contact_details(db, t.id, now - timedelta(hours=1)) == []


def test_shared_details_limit_counts_guests_not_raw_signal_rows(db):
    """Confirmed live on Ratha: the count card said 298, "Showing first 50
    of 298", but only ~30 rows ever rendered. Root cause -- `.limit(limit)`
    was applied to raw GuestIdentity rows (phone + email = 2 rows per
    guest) *before* the by-guest dedupe, so 50 raw rows collapsed to far
    fewer unique guests. 30 guests here each have 2 signals (60 raw rows);
    a limit of 20 must still return 20 distinct guests, not ~10."""
    t = _tenant(db)
    now = datetime.now(timezone.utc)
    guests = []
    for i in range(30):
        g, c = _conv(db, t, name=f"Guest{i}")
        _valid_inquiry(db, t, g)
        guests.append(g)
        db.add(GuestIdentity(
            tenant_id=t.id, guest_id=g.id, identity_type=IdentityType.PHONE.value,
            identity_value=f"+9198765{i:05d}", confidence=0.9,
            first_seen_at=now - timedelta(minutes=i),
        ))
        db.add(GuestIdentity(
            tenant_id=t.id, guest_id=g.id, identity_type=IdentityType.EMAIL.value,
            identity_value=f"guest{i}@example.com", confidence=0.9,
            first_seen_at=now - timedelta(minutes=i),
        ))
    db.commit()

    rows = ws.shared_contact_details(db, t.id, now - timedelta(hours=1), limit=20)
    assert len(rows) == 20
    assert len({r["shared_at"] for r in rows}) == 20  # 20 distinct guests, not fewer
    for r in rows:
        assert len(r["shared"]) == 2  # each guest's phone + email both retained


def test_shared_details_surfaces_assignee_name(db):
    t = _tenant(db)
    jishant = User(tenant_id=t.id, email="jishant@ratha.test", name="Jishant")
    db.add(jishant); db.commit()
    g, c = _conv(db, t, assigned_to=jishant.id)
    _valid_inquiry(db, t, g)
    now = datetime.now(timezone.utc)
    db.add(GuestIdentity(
        tenant_id=t.id, guest_id=g.id, identity_type=IdentityType.PHONE.value,
        identity_value="+919876500002", confidence=0.9, first_seen_at=now,
    ))
    db.commit()
    rows = ws.shared_contact_details(db, t.id, now - timedelta(hours=1))
    assert rows[0]["lead"]["assigned_agent_name"] == "Jishant"


# ─── lead context ────────────────────────────────────────────────────────────

def test_placeholder_names_are_labelled_unnamed(db):
    t = _tenant(db)
    g, c = _conv(db, t, name="Instagram User")
    _msg(db, t, c, MessageDirection.INBOUND)
    assert ws.awaiting_reply(db, t.id)[0]["lead"]["name"] == "Unnamed lead"


def test_has_contact_is_false_without_details(db):
    t = _tenant(db)
    g, c = _conv(db, t)
    _msg(db, t, c, MessageDirection.INBOUND)
    assert ws.awaiting_reply(db, t.id)[0]["lead"]["has_contact"] is False


# ─── totals vs row cap ───────────────────────────────────────────────────────

def test_counts_are_true_totals_not_row_counts(db):
    """Reporting len(rows) understates a backlog past the cap -- verified
    against real data where the true figure was 206 and the cap 50."""
    t = _tenant(db)
    for i in range(4):
        _, c = _conv(db, t, name=f"Lead {i}")
        _msg(db, t, c, MessageDirection.INBOUND)

    original = ws.SECTION_LIMIT
    try:
        ws.SECTION_LIMIT = 2
        out = ws.build_worklist(db, t.id, hours=24)
        assert len(out["awaiting_reply"]) == 2
        assert out["counts"]["awaiting_reply"] == 4
        assert out["truncated"]["awaiting_reply"] is True
    finally:
        ws.SECTION_LIMIT = original


# ─── shared_details stage filtering ────────────────────────────────────────

def test_shared_details_excludes_invalid_stage_leads(db):
    """Confirmed live on Ratha: 180 of 293 "shared their details" guests
    were sitting in an `invalid`-category stage (general_enquiry/RNR) --
    not real leads by this product's own dashboard-counting rule."""
    t = _tenant(db)
    g, c = _conv(db, t)
    stage = PipelineStage(tenant_id=t.id, key="general_enquiry", label="General Enquiry", category="invalid")
    db.add(stage); db.flush()
    db.add(Inquiry(tenant_id=t.id, guest_id=g.id, stage_id=stage.id)); db.commit()

    now = datetime.now(timezone.utc)
    db.add(GuestIdentity(
        tenant_id=t.id, guest_id=g.id, identity_type=IdentityType.PHONE.value,
        identity_value="+919876500009", confidence=0.9, first_seen_at=now,
    ))
    db.commit()

    assert ws.shared_contact_details(db, t.id, now - timedelta(hours=1)) == []
    counts = ws._totals(db, t.id, now - timedelta(hours=1), None, None)
    assert counts["shared_details"] == 0


def test_shared_details_excludes_guest_with_no_inquiry(db):
    """A guest who shared contact info but has no inquiry at all has
    nothing to follow up on -- doesn't qualify either."""
    t = _tenant(db)
    g, c = _conv(db, t)
    now = datetime.now(timezone.utc)
    db.add(GuestIdentity(
        tenant_id=t.id, guest_id=g.id, identity_type=IdentityType.PHONE.value,
        identity_value="+919876500010", confidence=0.9, first_seen_at=now,
    ))
    db.commit()

    assert ws.shared_contact_details(db, t.id, now - timedelta(hours=1)) == []


def test_shared_details_uses_most_recent_inquiry_stage(db):
    """A guest whose latest inquiry moved to a valid stage counts, even if
    an earlier inquiry was invalid."""
    t = _tenant(db)
    g, c = _conv(db, t)
    invalid_stage = PipelineStage(tenant_id=t.id, key="rnr", label="RNR", category="invalid")
    valid_stage = PipelineStage(tenant_id=t.id, key="active", label="Active", category="valid")
    db.add_all([invalid_stage, valid_stage]); db.flush()
    now = datetime.now(timezone.utc)
    db.add(Inquiry(tenant_id=t.id, guest_id=g.id, stage_id=invalid_stage.id,
                    created_at=now - timedelta(days=2)))
    db.add(Inquiry(tenant_id=t.id, guest_id=g.id, stage_id=valid_stage.id,
                    created_at=now - timedelta(days=1)))
    db.commit()
    db.add(GuestIdentity(
        tenant_id=t.id, guest_id=g.id, identity_type=IdentityType.PHONE.value,
        identity_value="+919876500011", confidence=0.9, first_seen_at=now,
    ))
    db.commit()

    rows = ws.shared_contact_details(db, t.id, now - timedelta(hours=1))
    assert len(rows) == 1


# ─── missed_calls ivr_provider filtering ───────────────────────────────────

def _call(db, t, *, ivr_provider, missed=True):
    from app.models.call import Call, CallDirection
    c = Call(
        tenant_id=t.id, ivr_provider=ivr_provider, ivr_call_id=f"call-{uuid.uuid4().hex[:10]}",
        direction=CallDirection.INBOUND, from_number="+919876500020", to_number="+911234567890",
        duration_seconds=0 if missed else 60,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(c); db.commit()
    return c


def test_missed_calls_excludes_disconnected_ivr_provider(db):
    """Confirmed live on Ratha: 384 of 394 "missed calls" were ivr_provider
    "mcube" -- the provider migration 064 moved Ratha off of. Scoped to
    the tenant's current tenant.ivr_provider, not a hardcoded blocklist."""
    t = _tenant(db)
    t.ivr_provider = "vobiz"
    db.add(t); db.commit()

    _call(db, t, ivr_provider="mcube")
    _call(db, t, ivr_provider="vobiz")

    now = datetime.now(timezone.utc)
    rows = ws.missed_calls(db, t.id, now - timedelta(hours=1))
    assert len(rows) == 1
    assert rows[0]["call_id"]

    counts = ws._totals(db, t.id, now - timedelta(hours=1), None, None)
    assert counts["missed_calls"] == 1
