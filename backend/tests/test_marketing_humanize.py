"""Instagram toolkit phase 1: humanizer + caption checks (pure), the AI text gate, Undo and its endpoint rules."""
import uuid
from unittest.mock import patch

from app.models.marketing import MarketingContentVersion
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import marketing_ai_service as ai
from app.services import marketing_caption_lint as lint
from app.services import marketing_content_service as svc
from app.services import marketing_humanize as human
from tests.conftest import seed_capabilities
from tests.test_marketing_studio_content import BASE, enable_module, make_user, ws  # noqa: F401  (fixture)

RAW = {"model": "openai/gpt-oss-20b", "input_tokens": 10, "output_tokens": 10}
AI_POST = {"kind": "post", "caption": "Rain on the roof, chai on the deck—our monsoon weekends open in July. "
                                      "Unlock two nights in Coonoor.​ DM us “MONSOON”.",
           "hashtags": ["#coonoor", "#monsoonstay"], "media": {"alt_text": "the deck in the rain"}}


# ── Humanizer (pure) ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_em_dash_curly_quotes_and_invisible_characters_are_fixed_and_recorded():
    out, changes = human.clean("Chai on the deck—then the hills.​ “DM us” today…")
    assert out == 'Chai on the deck, then the hills. "DM us" today...'
    kinds = {c["kind"] for c in changes}
    assert kinds == {"dash", "quote", "invisible", "ellipsis"}


def test_stock_words_swap_with_capitals_and_urls_stay_intact():
    out, changes = human.clean("Unlock a seamless stay. ELEVATE it at https://nila.example/unlock-seamless now.")
    assert out == "Get a clean stay. IMPROVE it at https://nila.example/unlock-seamless now."
    assert {c["from"] for c in changes} == {"unlock", "seamless", "elevate"}


def test_keep_list_words_are_never_swapped():
    out, changes = human.clean("Our curated breakfasts. Unlock the hills.", keep_words=["curated"])
    assert out == "Our curated breakfasts. Get the hills." and [c["from"] for c in changes] == ["unlock"]
    assert "curated" not in human.score("Our curated breakfasts.", ["curated"])["checks"][2]["detail"]


def test_emoji_joiner_is_kept_and_clean_text_is_untouched():
    family = "Family \U0001F468‍\U0001F469‍\U0001F467 weekend in Coorg."
    assert human.clean(family) == (family, [])


def test_deleted_phrase_leaves_tidy_capitalised_text():
    out, _ = human.clean("We have a pool. Let that sink in. look no further, the hills are here.")
    assert out == "We have a pool. The hills are here."


def test_score_is_higher_for_human_text():
    slop = ("Elevate your stay. Unlock a seamless, transformative experience. Discover our innovative and robust offers. "
            "Moreover, it is a testament to excellence. Furthermore, our meticulous team is vital to everything.")
    person = ("We drove up at 6 am. Coonoor was still in fog, so we waited with chai at the gate. It cleared by eight. "
              "Then the tea estates showed up, row after row, all the way to Lamb's Rock. You'll want a jacket.")
    assert human.score(person)["score"] > 70 > human.score(slop)["score"]
    assert human.score("")["score"] is None


def test_payload_clean_and_undo_round_trip_skips_hashtags_and_alt_text():
    payload = {"caption": "Look no further—the hills.", "hashtags": ["#hiddengem"],
               "slides": [{"headline": "A haven of calm", "media": {"asset_id": None, "alt_text": "stunning view"}}]}
    cleaned, record = human.clean_payload(payload)
    assert cleaned["caption"] == "The hills." and cleaned["slides"][0]["headline"] == "A place of calm"
    assert cleaned["hashtags"] == ["#hiddengem"] and cleaned["slides"][0]["media"]["alt_text"] == "stunning view"
    cleaned["slides"][0]["headline"] = "Edited by a person"
    restored, n = human.undo_payload(cleaned, record)
    assert n == 1 and restored["caption"] == payload["caption"] and restored["slides"][0]["headline"] == "Edited by a person"


# ── Caption checks (pure) ────────────────────────────────────────────────────────────────────────────────────────────

def _check(result, key):
    return next(c for c in result["checks"] if c["key"] == key)


def test_visible_window_cuts_at_125_and_flags_a_long_first_line():
    long = "A" * 130 + " rest"
    r = lint.check_caption(long)
    assert r["visible"] == "A" * 125 and r["truncated"] and _check(r, "visible_line")["status"] == "warn"
    short = lint.check_caption("Rain on the roof in Coonoor.\nDM us for dates.")
    assert not short["truncated"] and _check(short, "visible_line")["value"] == "28 / 125"


def test_hashtag_cap_counts_list_and_inline_tags():
    r = lint.check_caption("Hills #coonoor", ["#a", "#b", "#c", "#d", "#e"])
    assert _check(r, "hashtags")["status"] == "bad" and _check(r, "hashtags")["value"] == "6 / 5"
    assert _check(lint.check_caption("Hills", ["#a", "#b"]), "hashtags")["status"] == "ok"


def test_exactly_one_ask_and_search_words():
    one = lint.check_caption('Rain in Coonoor. Comment MONSOON for dates.', keywords=["Coonoor"])
    assert _check(one, "one_ask")["status"] == "ok" and _check(one, "search_words")["status"] == "ok"
    two = lint.check_caption("DM us for dates. Link in bio. Save this.", keywords=["Ooty"])
    assert _check(two, "one_ask")["status"] == "warn" and _check(two, "search_words")["status"] == "warn"
    assert _check(lint.check_caption("Rain on the roof."), "one_ask")["value"] == "None"


def test_price_check_follows_policy():
    assert lint.price_check("handoff", ["Two nights for Rs 12,000"])["status"] == "bad"
    assert lint.price_check("handoff", ["Two nights in the hills"])["status"] == "ok"
    assert lint.price_check("grounded", ["Rs 12,000"])["status"] == "ok"


# ── Text gate (AI generation) ────────────────────────────────────────────────────────────────────────────────────────

def _generate(db, tenant_id, actor_id, data=AI_POST):
    item = svc.create_item(db, tenant_id, kind="post", title="Monsoon", actor_id=actor_id)
    db.commit()
    with patch.object(ai, "_call", return_value=(dict(data), RAW, "nvidia")):
        ai.run_content(db, tenant_id, item.id, actor_id, None)
    db.commit()
    db.refresh(item)
    assert item.generation_status != "failed", item.generation_error
    return item, db.query(MarketingContentVersion).filter_by(content_id=item.id).one()


def test_ai_draft_is_cleaned_before_it_is_stored_and_the_original_is_kept(db, ws):
    item, v = _generate(db, ws["tenant"].id, ws["mkt"].id)
    assert "—" not in v.payload["caption"] and "​" not in v.payload["caption"] and "Get two nights" in v.payload["caption"]
    assert v.humanize["fields"][0]["before"] == AI_POST["caption"]
    assert v.sha256 == svc.sha_of(v.payload)          # approval binds to the CLEANED payload
    checks = svc.text_checks(db, ws["tenant"].id, item, v)
    assert checks["fixed"]["undoable"] == 1 and "dash" in checks["fixed"]["summary"]


def test_keep_list_applies_per_workspace(db, ws):
    t = ws["tenant"]
    human.set_keep_words(db, t, ["Unlock", "unlock", "  "], ws["owner"].id)
    assert human.keep_words(t) == ["Unlock"]
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    _, mine = _generate(db, t.id, ws["mkt"].id)
    _, theirs = _generate(db, other.id, None)
    assert "Unlock two nights" in mine.payload["caption"] and "Get two nights" in theirs.payload["caption"]
    assert human.keep_words(other) == []


def test_a_fix_that_would_break_the_format_stores_the_draft_as_written(db, ws):
    _, v = _generate(db, ws["tenant"].id, ws["mkt"].id, {**AI_POST, "caption": "Follow for more"})
    assert v.payload["caption"] == "Follow for more" and v.humanize is None


# ── Endpoints ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_undo_restores_the_original_as_a_new_version_and_is_audited(client, db, ws):
    from app.models.audit_event import AuditEvent as Log

    item, v = _generate(db, ws["tenant"].id, ws["mkt"].id)
    got = client.get(f"{BASE}/content/{item.id}", headers=ws["mkt_h"]).json()
    assert got["text_checks"]["fixed"]["undoable"] == 1 and got["text_checks"]["caption"]["visible"]
    assert {c["key"] for c in got["text_checks"]["caption"]["checks"]} >= {"visible_line", "one_ask", "hashtags", "price"}
    r = client.post(f"{BASE}/content/{item.id}/undo-humanize", json={"version_id": v.id}, headers=ws["mkt_h"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["current"]["version"] == 2 and body["current"]["origin"] == "human"
    assert body["current"]["payload"]["caption"] == AI_POST["caption"] and body["text_checks"]["fixed"] is None
    assert db.query(Log).filter_by(tenant_id=ws["tenant"].id, action="marketing.content.humanize_undone").count() == 1
    again = client.post(f"{BASE}/content/{item.id}/undo-humanize", json={"version_id": body["current"]["id"]}, headers=ws["mkt_h"])
    assert again.status_code == 409 and again.json()["detail"]["code"] == "nothing_to_undo"


def test_undo_needs_marketing_edit(client, db, ws):
    item, v = _generate(db, ws["tenant"].id, ws["mkt"].id)
    _, ro_h = make_user(db, ws["tenant"].id, UserRole.READ_ONLY)
    assert client.post(f"{BASE}/content/{item.id}/undo-humanize", json={"version_id": v.id}, headers=ro_h).status_code == 403
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.post(f"{BASE}/content/{item.id}/undo-humanize", json={"version_id": v.id}, headers=foh_h).status_code == 403


def test_other_workspace_cannot_undo(client, db, ws):
    item, v = _generate(db, ws["tenant"].id, ws["mkt"].id)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    seed_capabilities(db, other.id)
    enable_module(db, other.id)
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.post(f"{BASE}/content/{item.id}/undo-humanize", json={"version_id": v.id}, headers=other_h).status_code == 404
    assert db.query(MarketingContentVersion).filter_by(content_id=item.id).count() == 1


def test_keep_words_setting_is_owner_only(client, ws):
    r = client.put(f"{BASE}/settings", json={"keep_words": ["unwind", "stay"]}, headers=ws["owner_h"])
    assert r.status_code == 200 and r.json()["keep_words"] == ["unwind", "stay"]
    assert client.put(f"{BASE}/settings", json={"keep_words": ["x"]}, headers=ws["mkt_h"]).status_code == 403
    assert client.get(f"{BASE}/settings", headers=ws["mkt_h"]).json()["keep_words"] == ["unwind", "stay"]
