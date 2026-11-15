"""Suggest more (services/ig_suggest.py, Automations v2 phase 4): after the final message, a "More stays" button;
a tap shows the workspace's stays or packages as cards (never prices); "I'm interested" thanks the guest and writes the
pick on the enquiry. Workspaces never mix.
"""

import uuid

import pytest

from app.models.automation import AutomationRule
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.ig_automation import IgAutomationEvent
from app.models.inquiry import Inquiry
from app.models.property import Property
from app.models.tenant import Tenant
from app.services import ig_automation, ig_sequence, ig_suggest


class FakeIG:
    def __init__(self):
        self.calls = []

    def _ok(self, *call):
        self.calls.append(call)
        return {"message_id": f"mid.{len(self.calls)}"}

    def send_text(self, rid, text): return self._ok("text", rid, text)
    def send_quick_replies(self, rid, text, quick): return self._ok("quick", rid, text, quick)
    def send_private_reply(self, comment_id, text, quick=None): return self._ok("private", comment_id, text, quick)
    def send_link_button(self, rid, text, title, url): return self._ok("button", rid, text, title, url)
    def send_cards(self, rid, elements): return self._ok("cards", rid, elements)
    def reply_to_comment(self, comment_id, text): return self._ok("public", comment_id, text)
    def follows_us(self, rid): return None


@pytest.fixture
def ig(monkeypatch):
    fake = FakeIG()
    monkeypatch.setattr(ig_automation, "_adapter", lambda db, tenant_id: fake)
    monkeypatch.setattr(ig_sequence, "_queue", lambda *a: None)
    return fake


def _world(db, source="stays"):
    t = Tenant(id=str(uuid.uuid4()), name="Neelgiri", slug=f"n-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Ananya Rao")
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id)
    db.add(inq)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.INSTAGRAM, inquiry_id=inq.id)
    r = AutomationRule(id=str(uuid.uuid4()), tenant_id=t.id, name="PRICE", trigger="ig_dm_received",
                       trigger_config={"keywords": ["price"]}, action="send_instagram_quick_reply",
                       action_config={"message": "Here you go.",
                                      "suggest_more": {"enabled": True, "source": source, "button_title": "More stays"}},
                       is_active=True, run_count=0)
    db.add_all([
        Property(id=str(uuid.uuid4()), tenant_id=t.id, name="Dome Villa", slug=f"d-{uuid.uuid4().hex[:5]}", bedrooms=3,
                 max_adults=8, city="Coorg", photos=["https://cdn.example.in/dome.jpg"], price_per_day=37000),
        Property(id=str(uuid.uuid4()), tenant_id=t.id, name="Pool Cottage", slug=f"p-{uuid.uuid4().hex[:5]}", bedrooms=1,
                 max_adults=2, photos=["http://insecure.example/x.jpg"]),
        Property(id=str(uuid.uuid4()), tenant_id=t.id, name="Closed Villa", slug=f"c-{uuid.uuid4().hex[:5]}", is_active=False),
        c, r,
    ])
    db.commit()
    return t, g, c, inq, r


def _tap(db, t, g, c, r, step):
    return ig_automation.handle_payload(db, t.id, f"igauto:{r.id}:{step}", recipient_id="igsid", guest_id=g.id,
                                        conversation_id=c.id, guest=g)


def test_the_final_message_offers_more_stays(db, ig):
    t, g, c, inq, r = _world(db)
    ig_automation.start(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id, guest=g)
    name, _, text, quick = ig.calls[-1]
    assert name == "quick" and quick[0]["title"] == "More stays" and quick[0]["payload"] == f"igauto:{r.id}:more"


def test_a_tap_shows_the_stays_as_cards_without_prices(db, ig):
    t, g, c, inq, r = _world(db)
    assert _tap(db, t, g, c, r, "more")
    name, _, elements = ig.calls[-1]
    assert name == "cards" and [e["title"] for e in elements] == ["Dome Villa", "Pool Cottage"]   # inactive left out
    assert elements[0]["subtitle"] == "3 bedrooms · up to 8 guests · Coorg"
    assert elements[0]["image_url"] == "https://cdn.example.in/dome.jpg" and "image_url" not in elements[1]  # https only
    assert "37" not in str(elements) and "₹" not in str(elements)                                    # never a price
    assert elements[1]["buttons"][0]["payload"] == f"igauto:{r.id}:ask:1"


def test_im_interested_thanks_them_and_notes_the_pick(db, ig):
    t, g, c, inq, r = _world(db)
    assert _tap(db, t, g, c, r, "ask:0")
    assert "Dome Villa" in ig.calls[-1][2]
    db.refresh(inq)
    assert "Interested in: Dome Villa (Instagram)" in inq.special_requests
    _tap(db, t, g, c, r, "ask:0")
    db.refresh(inq)
    assert inq.special_requests.count("Dome Villa") == 1                   # not written twice
    kinds = [e.kind for e in db.query(IgAutomationEvent).filter_by(rule_id=r.id)]
    assert kinds.count("card_interest") == 2


def test_packages_come_from_published_business_data_only(db, ig, monkeypatch):
    from app.services import sales_gateway

    t, g, c, inq, r = _world(db, source="packages")
    calls = []

    def fake_list(db_, tenant_id, include_rates=False, **kw):
        calls.append((tenant_id, include_rates))
        return sales_gateway.GatewayResult(True, [{"name": "Coorg weekend", "summary": "2 nights, breakfast"}])

    monkeypatch.setattr(sales_gateway, "list_packages", fake_list)
    _tap(db, t, g, c, r, "more")
    assert calls == [(t.id, False)]                                         # never asks for rates
    assert ig.calls[-1][2][0]["title"] == "Coorg weekend"


def test_no_stays_means_a_plain_reply(db, ig):
    t, g, c, inq, r = _world(db)
    db.query(Property).filter_by(tenant_id=t.id).update({"is_active": False})
    db.commit()
    _tap(db, t, g, c, r, "more")
    assert ig.calls[-1][0] == "text"


def test_cards_never_cross_workspaces(db, ig):
    t, g, c, inq, r = _world(db)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    assert ig_suggest.items(db, other.id, "stays") == []
    assert ig_automation.handle_payload(db, other.id, f"igauto:{r.id}:more", recipient_id="igsid", guest_id=g.id,
                                        conversation_id=c.id) is True
    assert ig.calls == []                                                   # the rule isn't that workspace's
