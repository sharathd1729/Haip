"""Studio phase 3 (plan 24 Oct 2026): season calendar, theme radar scored in code, shoot & collab brief, monthly deck."""
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import patch

from app.models.audit_event import AuditEvent
from app.models.base import gen_uuid
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.marketing import MarketingCompetitor, MarketingCompetitorPost
from app.models.marketing_research import MarketingSignal, MarketingStrategyDoc
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import marketing_ai_service as ai
from app.services import marketing_radar as radar
from app.services import marketing_strategy as strategy
from tests.conftest import seed_capabilities
from tests.test_marketing_studio_content import BASE, enable_module, make_user, ws  # noqa: F401  (fixture)

TODAY = date(2026, 10, 3)                  # Diwali (7 Nov) is 35 days out: the best lead time


def _say(db, tid, text):
    g = Guest(id=gen_uuid(), tenant_id=tid, name="Asha")
    db.add(g)
    db.flush()
    conv = Conversation(id=gen_uuid(), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    db.add(Message(tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.INBOUND, channel=ChannelType.WHATSAPP,
                   body=text))
    db.commit()


def test_calendar_is_seeded_and_owner_edits_are_checked(client, db, ws):  # noqa: F811
    names = [e["name"] for e in radar.get_calendar(ws["tenant"])]
    assert "Diwali" in names and "Summer escape from Bengaluru heat" in names
    entry = {"entries": [{"name": "Onam", "start": "2026-08-25", "end": "2026-08-28", "keywords": ["onam"]}]}
    assert client.put(f"{BASE}/calendar", json=entry, headers=ws["manager_h"]).status_code == 403
    bad = {"entries": [{"name": "Onam", "start": "2026-08-28", "end": "2026-08-25"}]}
    assert client.put(f"{BASE}/calendar", json=bad, headers=ws["owner_h"]).status_code == 422
    assert client.put(f"{BASE}/calendar", json=entry, headers=ws["owner_h"]).json()["entries"][0]["name"] == "Onam"
    assert db.query(AuditEvent).filter_by(tenant_id=ws["tenant"].id, action="marketing.season_calendar.changed").count() == 1


def test_radar_scores_in_code_with_evidence_and_shoot_by(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    for _ in range(3):
        _say(db, tid, "Any availability for Diwali weekend?")
    db.add(MarketingSignal(tenant_id=tid, source="google_trends", evidence="google", key="d", title="Diwali trip ideas",
                           value=50000, observed_on=TODAY))
    comp = MarketingCompetitor(tenant_id=tid, handle="wild")
    db.add(comp)
    db.flush()
    db.add(MarketingCompetitorPost(tenant_id=tid, competitor_id=comp.id, source="collector", media_id="x",
                                   caption="A long weekend under the stars", posted_at=(TODAY - timedelta(days=3)).isoformat()))
    db.commit()
    out = radar.radar(db, ws["tenant"], TODAY)
    top = out["top"][0]
    assert top["theme"] == "Diwali" and 0 <= top["score"] <= 100 and top["components"]["season"] == 1.0
    assert top["shoot_by"] == (date(2026, 11, 7) - timedelta(days=radar.SHOOT_LEAD_DAYS)).isoformat()
    assert {e["kind"] for e in top["evidence"]} == {"own", "google"}
    bridge = next(t for t in out["all"] if t["theme"] == "24 Nov bridge weekend")
    assert bridge["components"]["platform"] == 1.0 and bridge["components"]["gap"] == 0.0  # competitors are on it
    assert not any(t["theme"] == "Christmas" for t in out["all"])                         # beyond the 8-week horizon
    assert sum(radar.WEIGHTS.values()) == 100


BRIEF = {"focus": "Diwali at Kabini: guests ask for it and Google searches are up.", "must_get": ["door-open reveal"],
         "shots": [{"n": i, "use": "hook" if i == 1 else "story", "scene": "door-open reveal", "shot_size": "wide", "angle": "pov",
                    "movement": "push_in", "lens": "16-24mm", "duration_s": 3, "time_of_day": "golden_hour",
                    "talent": ["couple"], "props": ["diyas"], "audio": "ambient", "on_screen_text": "We woke up here",
                    "why": "POV openings hold attention", "priority": "must"} for i in range(1, 4)],
         "broll": ["wheels on a ghat road"], "hooks": [{"text": f"Hook {i}", "type": "pov"} for i in range(5)],
         "reels": [{"title": "Night at Kabini", "shots": [1, 2, 3], "length_s": 15, "cta": "WhatsApp us"},
                   {"title": "Morning", "shots": [2, 3], "length_s": 10, "cta": "DM us"}],
         "captions": ["Diwali, but the stars are the lights."], "posting_plan": [{"week": 1, "kind": "reel", "what": "Night at Kabini"},
                                                                               {"week": 2, "kind": "carousel", "what": "Shot list"}],
         "collab": {"creator_brief": "Film the reveal.", "deliverables": ["1 Reel", "3 stories"], "usage_rights": "90 days organic"}}


def test_brief_is_written_with_code_owned_label_and_tracking(db, ws):  # noqa: F811
    doc = strategy.request_brief(db, ws["tenant"], {"theme": "Diwali", "date": "2026-10-30", "vehicle": "Ratha 1",
                                                    "collab": True, "creator": "@kabinitales"}, ws["owner"].id)
    db.commit()
    with patch.object(ai, "_call", return_value=(dict(BRIEF), {"model": "m"}, "nvidia")) as call:
        strategy.write(db, ws["tenant"].id, doc.id)
    assert call.call_args.args[0] == "marketing_brief"
    assert doc.status == "ready" and len(doc.body["hooks"]) == 5 and doc.prompt_version == "marketing-shoot-brief-v1"
    assert doc.body["collab"]["asci_label"] == "#Ad" and doc.body["collab"]["tracking_code"].startswith("c-")
    bad = strategy.request_brief(db, ws["tenant"], {"theme": "Diwali"}, ws["owner"].id)
    with patch.object(ai, "_call", return_value=({**BRIEF, "captions": ["Only Rs 4,999 a night!"]}, {"model": "m"}, "nvidia")):
        strategy.write(db, ws["tenant"].id, bad.id)
    assert bad.status == "failed"                                        # handoff price policy: no prices in a brief


def test_deck_grounds_numbers_and_falls_back(db, ws):  # noqa: F811
    doc = strategy.request_deck(db, ws["tenant"], date(2026, 11, 1), None)
    text = {"headline": "November: lean into Diwali. Bookings rose 777 percent.", "last_month": "Not enough data.",
            "learnings": [], "market_notes": [], "themes": ["Diwali"], "shoot_plan": [], "hooks_to_test": [],
            "collab_plan": [], "ad_concepts": []}
    with patch.object(ai, "_call", return_value=(text, {"model": "m"}, "nvidia")):
        strategy.write(db, ws["tenant"].id, doc.id)
    assert doc.status == "ready" and doc.source == "llm" and doc.body["headline"] == "November: lean into Diwali."
    again = strategy.request_deck(db, ws["tenant"], date(2026, 11, 1), None)
    assert again.id == doc.id                                            # one deck per month, recomputed in place
    with patch.object(ai, "_call", side_effect=ai.LLMTransientError("down")):
        strategy.write(db, ws["tenant"].id, doc.id)
    assert doc.source == "deterministic" and doc.body["headline"].startswith("Strategy for 2026-11")


def test_deck_is_due_on_the_first_from_eight_once(db, ws):  # noqa: F811
    assert strategy.due_decks(db, lambda t: datetime(2026, 11, 1, 7, 0)) == []
    assert (ws["tenant"].id, date(2026, 11, 1)) in strategy.due_decks(db, lambda t: datetime(2026, 11, 1, 9, 0))
    strategy.request_deck(db, ws["tenant"], date(2026, 11, 1), None)
    db.commit()
    assert strategy.due_decks(db, lambda t: datetime(2026, 11, 1, 9, 0)) == []


def test_strategy_api_roles_and_isolation(client, db, ws, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.workers.tasks.marketing_research_tasks.write_doc.delay", lambda *a: None)
    assert client.get(f"{BASE}/radar", headers=ws["mkt_h"]).status_code == 200
    r = client.post(f"{BASE}/briefs", json={"theme": "Diwali"}, headers=ws["mkt_h"])
    assert r.status_code == 202 and r.json()["status"] == "pending"
    assert client.post(f"{BASE}/briefs", json={}, headers=ws["mkt_h"]).status_code == 422
    assert client.get(f"{BASE}/decks/latest", headers=ws["mkt_h"]).status_code == 403
    assert client.get(f"{BASE}/decks/latest", headers=ws["manager_h"]).json()["deck"] is None
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    seed_capabilities(db, other.id)
    enable_module(db, other.id)
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.get(f"{BASE}/briefs/{r.json()['id']}", headers=other_h).status_code == 404
    assert client.get(f"{BASE}/briefs", headers=other_h).json() == []
    assert db.query(MarketingStrategyDoc).filter_by(tenant_id=ws["tenant"].id).count() == 1
