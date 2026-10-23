"""The ONE contact rule (work_queue_signals.touch_rows) never counts a campaign broadcast as a person's contact -- including
campaign rows written before ``messages.sender_kind`` existed (migration 151), which only their "Campaign: <name>" sender name
or metadata identify (message_author). Live: Rathaa's "Sept long weekend" campaign (sender_kind NULL) counted as the team
having contacted the guest."""
from datetime import timedelta

import pytest

from app.services.work_queue_signals import is_legacy_campaign, touch_rows
from tests.services._autopilot_fixtures import NOW, lead, msg, tenant


@pytest.mark.parametrize("name,meta,expected", [
    ("Campaign: Sept_long weekend", None, True),
    (None, {"kind": "campaign", "campaign_id": "c1"}, True),
    ("Asha", None, False),
    (None, None, False),
])
def test_is_legacy_campaign(name, meta, expected):
    assert is_legacy_campaign(name, meta) is expected


def _contacts(db, tenant_id, guest_id):
    return [r for r in touch_rows(db, tenant_id, {guest_id: NOW - timedelta(days=30)}) if r[2] == "contact"]


def test_a_legacy_campaign_row_is_not_contact_but_a_person_is(db):
    t, s = tenant(db)
    g, _, conv = lead(db, t.id, s["active"])
    msg(db, t.id, conv, "Two caravans free, 8 guests each. Tell us your dates!", inbound=False, ago=timedelta(days=3),
        sender_name="Campaign: Sept_long weekend", channel_metadata={"kind": "campaign"})
    msg(db, t.id, conv, "Old broadcast", inbound=False, ago=timedelta(days=2), channel_metadata={"kind": "campaign"})
    assert _contacts(db, t.id, g.id) == []
    msg(db, t.id, conv, "Hi Kiran, Asha here from Ratha", inbound=False, ago=timedelta(days=1), sender_name="Asha")
    assert len(_contacts(db, t.id, g.id)) == 1


def test_contact_never_crosses_tenants(db):
    t, s = tenant(db)
    g, _, conv = lead(db, t.id, s["active"])
    msg(db, t.id, conv, "Hi Kiran, Asha here", inbound=False, ago=timedelta(days=1), sender_name="Asha")
    other, _ = tenant(db)
    assert touch_rows(db, other.id, {g.id: NOW - timedelta(days=30)}) == []
