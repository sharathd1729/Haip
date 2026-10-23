"""The lead autopilot's AI classifier sees who wrote each message (lead-autopilot-classify-v2): [guest] vs [us: team member |
AI assistant | automated message | campaign broadcast], never a bare [outbound], so our own campaign or AI words are not read
as the guest's (message_author)."""
from datetime import timedelta

from app.core.prompt_versions import get_version
from app.services import lead_autopilot_ai as ai
from app.services.lead_autopilot_rules import StageMap
from tests.services._autopilot_fixtures import lead, msg, tenant


def test_context_lines_name_their_author(db):
    t, s = tenant(db)
    g, inq, conv = lead(db, t.id, s["active"])
    msg(db, t.id, conv, "Long weekend offer, 8 guests each. Tell us your dates!", inbound=False, ago=timedelta(days=4),
        sender_name="Campaign: Sept_long weekend", channel_metadata={"kind": "campaign"})
    msg(db, t.id, conv, "Can you give barter collaboration", ago=timedelta(days=3))
    msg(db, t.id, conv, "Our team will get back to you.", inbound=False, ago=timedelta(days=3) - timedelta(minutes=1),
        is_ai_generated=True, was_approved=True, sent_autonomously=True)
    msg(db, t.id, conv, "Hi, Asha here", inbound=False, ago=timedelta(days=1), sender_name="Asha")
    text, index, _ = ai.build_context(db, t.id, inq, StageMap.load(db, t.id))
    assert "[us: campaign broadcast]" in text and "[guest]" in text and "[us: AI assistant]" in text
    assert "[us: team member]" in text and "[outbound]" not in text and "[inbound]" not in text
    assert "[us: campaign broadcast]" in ai.SYSTEM_PROMPT and get_version("lead_autopilot_classify") == "lead-autopilot-classify-v2"


def test_context_never_reads_another_tenants_messages(db):
    t, s = tenant(db)
    g, inq, conv = lead(db, t.id, s["active"])
    msg(db, t.id, conv, "Can you give barter collaboration", ago=timedelta(days=3))
    other, _ = tenant(db)
    text, index, _ = ai.build_context(db, other.id, inq, StageMap.load(db, other.id))
    assert "barter" not in text and index == {}
