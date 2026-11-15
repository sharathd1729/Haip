"""Instagram toolkit phase 2: reel hook score, formula match, beat sheet, the AI step after a reel draft, choosing."""
import uuid
from unittest.mock import patch

from app.models.marketing import MarketingContent, MarketingContentVersion
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import marketing_ai_service as ai
from app.services import marketing_content_service as svc
from app.services import marketing_hooks as hooks
from tests.conftest import seed_capabilities
from tests.test_marketing_studio_content import BASE, enable_module, make_user, ws  # noqa: F401  (fixture)

RAW = {"model": "openai/gpt-oss-20b", "input_tokens": 10, "output_tokens": 10}
REEL = {"kind": "reel", "caption": "Monsoon weekends in Coonoor. DM us for dates.",
        "clips": [{"seconds": 3, "caption": "Rain on the deck", "media": {"alt_text": "rain on the deck"}},
                  {"seconds": 4, "caption": "Chai by the window", "media": {"alt_text": "chai"}}]}
HOOKS = {"options": [
    {"formula_id": 3, "spoken": "Nobody tells you Coonoor is best in the rain.", "on_screen": "COONOOR IN THE RAIN"},
    {"formula_id": 23, "spoken": "Hey guys, so today we have something.", "on_screen": "HELLO"},
    {"formula_id": 4, "spoken": "Two nights in Coonoor for Rs 9,000 this July.", "on_screen": "Rs 9,000 WEEKEND"}],
    "script": [{"line": "Most weekends here sell out when the mist rolls in.", "shot": "rain on the deck"},
               {"line": "Chai at six, the valley still white below you.", "shot": "chai by the window"},
               {"line": "DM us RAIN and we'll send the Coonoor dates.", "shot": "deck at dusk"}]}


def test_hook_score_separates_a_real_hook_from_a_greeting():
    good = hooks.score_hook("Nobody tells you Coonoor is best in the rain.")
    bad = hooks.score_hook("Hey guys, so today we have something.")
    assert good["score"] >= 70 > hooks.WEAK_BELOW > bad["score"] and bad["flags"]
    assert bad["verdict"] == "weak" and good["verdict"] in ("strong", "ok")


def test_classify_names_the_formula():
    assert hooks.classify("Stop booking hill stations in May.") == 2
    assert hooks.classify("Nobody tells you that the mist lifts by nine.") == 3
    assert hooks.classify("the deck") is None


def test_beats_time_the_script_and_flag_a_long_hook():
    sheet = hooks.beats([{"line": " ".join(["word"] * 12), "shot": "deck"}, {"line": "DM us for word dates.", "shot": "x"}])
    assert sheet["rows"][0]["label"] == "Hook" and sheet["rows"][-1]["label"] == "Ask"
    assert sheet["rows"][0]["flags"] and sheet["total_seconds"] > 4
    assert any("Loops" in n for n in sheet["notes"])


def test_plan_greys_weak_options_and_blocks_prices():
    plan = hooks.build_plan(HOOKS, "handoff")
    good, weak, priced = plan["options"]
    assert good["reason"] is None and not good["blocked"]
    assert weak["score"] < 50 and weak["reason"] and not weak["blocked"]
    assert priced["blocked"] and "price" in priced["reason"]
    assert plan["beats_for"] == 0 and plan["beats"]["rows"][0]["line"] == good["spoken"]
    assert not hooks.build_plan(HOOKS, "grounded")["options"][2]["blocked"]


def _reel(db, tenant_id, actor_id):
    item = svc.create_item(db, tenant_id, kind="reel", title="Monsoon reel", actor_id=actor_id)
    db.commit()
    with patch.object(ai, "_call", side_effect=[(dict(REEL), RAW, "nvidia"), (HOOKS, RAW, "nvidia")]):
        ai.run_content(db, tenant_id, item.id, actor_id, None)
    db.commit()
    db.refresh(item)
    return item


def test_reel_draft_gets_three_scored_options_from_the_same_run(db, ws):
    item = _reel(db, ws["tenant"].id, ws["mkt"].id)
    assert item.current_version_id and item.hook_plan["status"] == "ready" and len(item.hook_plan["options"]) == 3
    assert item.hook_plan["prompt_version"] == "marketing-reel-hooks-v1"


def test_hook_failure_never_loses_the_draft(db, ws):
    item = svc.create_item(db, ws["tenant"].id, kind="reel", title="Reel", actor_id=ws["mkt"].id)
    db.commit()
    with patch.object(ai, "_call", side_effect=[(dict(REEL), RAW, "nvidia"), ai.LLMTransientError("down")]):
        ai.run_content(db, ws["tenant"].id, item.id, ws["mkt"].id, None)
    db.commit()
    db.refresh(item)
    assert item.current_version_id and item.hook_plan["status"] == "failed"


def test_choose_puts_the_line_on_the_first_clip_and_saves_the_formula(client, db, ws):
    from app.models.audit_event import AuditEvent

    item = _reel(db, ws["tenant"].id, ws["mkt"].id)
    r = client.post(f"{BASE}/content/{item.id}/hooks/0/choose", json={"version_id": item.current_version_id}, headers=ws["mkt_h"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["current"]["version"] == 2 and body["current"]["payload"]["clips"][0]["caption"] == "COONOOR IN THE RAIN"
    assert body["hook_formula"] == "Nobody Tells You" and body["hook_plan"]["chosen"] == 0
    assert db.query(AuditEvent).filter_by(tenant_id=ws["tenant"].id, action="marketing.content.hook_chosen").count() == 1
    blocked = client.post(f"{BASE}/content/{item.id}/hooks/2/choose", json={"version_id": body["current"]["id"]}, headers=ws["mkt_h"])
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "hook_blocked"


def test_choose_needs_edit_and_stays_in_the_workspace(client, db, ws):
    item = _reel(db, ws["tenant"].id, ws["mkt"].id)
    _, ro_h = make_user(db, ws["tenant"].id, UserRole.READ_ONLY)
    url = f"{BASE}/content/{item.id}/hooks/0/choose"
    assert client.post(url, json={"version_id": item.current_version_id}, headers=ro_h).status_code == 403
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    seed_capabilities(db, other.id)
    enable_module(db, other.id)
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.post(url, json={"version_id": item.current_version_id}, headers=other_h).status_code == 404
    assert client.get(f"{BASE}/content/{item.id}", headers=other_h).status_code == 404
    assert db.query(MarketingContentVersion).filter_by(content_id=item.id).count() == 1
    assert db.query(MarketingContent).filter_by(id=item.id).one().hook_formula is None
