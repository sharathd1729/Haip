"""Unit pins for the sales agent's pieces: the requirement (no extractor of its own), the reply guards, the fact merge, the owner
settings and the model report. The end-to-end behaviour is in tests/workers/test_sales_agent_concierge.py."""
import uuid
from datetime import timedelta

from app.models.guest import Guest
from app.models.tenant import Tenant
from app.services import sales_agent_settings, sales_requirement
from app.services.llm_routing_report import report
from app.services.sales_agent_service import SalesTurn, check_reply, merge_facts
from tests.test_quote_builder_pricing import START, ratha
from tests.test_quotes_api import lead

END = START + timedelta(days=2)


def test_the_requirement_comes_from_the_conversation_and_the_lead(db):
    w = ratha(db)
    inq = lead(db, w.t.id)
    inq.check_in, inq.check_out, inq.adults, inq.route_mentioned = START.isoformat(), END.isoformat(), 5, "Coorg"
    db.commit()
    guest = db.query(Guest).filter_by(id=inq.guest_id).first()
    req = sales_requirement.assemble(db, w.t.id, inq, guest, {}, "")
    assert (req.check_in, req.check_out, req.adults) == (START, END, 5)             # from the lead's own fields
    assert req.package_key == "coorg-48" and req.destination_key == "coorg"         # the one plan made for that route
    stated = sales_requirement.assemble(db, w.t.id, inq, guest, {"adults": 3, "destination": "KRS backwaters"}, "")
    # "KRS Backwaters" is the name of two published routes here (krs, far): the agent asks, it does not pick one or hand off
    assert stated.adults == 3 and stated.destination_key is None and stated.package_key is None and stated.handoff is None
    assert "which plan or route" in stated.missing and stated.key() != req.key()


def test_handoff_reasons_are_detected_not_guessed(db):
    w = ratha(db)
    inq = lead(db, w.t.id)
    assert sales_requirement.assemble(db, w.t.id, inq, None, {}, "I am a travel agent with clients").handoff == "b2b"
    assert sales_requirement.assemble(db, w.t.id, inq, None, {}, "can you do a better price? any discount").handoff == "discount_request"
    assert sales_requirement.assemble(db, w.t.id, inq, None, {"destination": "Ladakh"}, "Ladakh trip").handoff == "custom_route"
    assert sales_requirement.assemble(db, w.t.id, inq, None, {}, "hi").handoff is None


def test_reply_guards_only_apply_in_sales_mode():
    on = SalesTurn(mode="suggest", status="quote_ready")
    assert check_reply("Your trip is booked!", [], on) == "says the trip is booked or confirmed before any payment"
    assert check_reply("Your trip is booked!", [{"tool": "guest_bookings", "result": [{"status": "confirmed"}]}], on) is None
    assert "discount" in check_reply("We can give you 10% off.", [], on)
    assert "link" in check_reply("Pay here: https://rzp.io/i/abc", [], on)
    assert "sent" in check_reply("I've sent you the payment link.", [], on)
    assert check_reply("I've sent you the payment link.", [], SalesTurn(mode="autopilot", status="quote_sending")) is None
    assert check_reply("The team will share the quote and payment link shortly.", [], on) is None
    assert check_reply("Your trip is booked!", [], SalesTurn()) is None                       # mode off: today's behaviour


def test_grounded_packages_leave_only_the_package_engines_figures():
    t = Tenant(brand_config={"price_disclosure": "grounded"})
    facts = [{"tool": "business_data", "result": {"packages": [{"key": "p"}]}},
             {"tool": "check_availability", "args": {"checkin": "2026-11-01"}, "result": [{"property_name": "A", "price_per_night": "9000"}]},
             {"tool": "get_quote", "result": {"total": "18000"}}]
    out = merge_facts(t, facts, SalesTurn())
    assert [f["tool"] for f in out] == ["business_data", "check_availability"] and "9000" not in str(out)
    handoff = merge_facts(Tenant(brand_config={}), facts, SalesTurn())
    assert handoff == facts                                                                   # handoff mode: unchanged here
    cal = {"tool": "check_availability", "source": "calendar", "args": {"checkin": "2026-11-01"}, "result": []}
    mine = merge_facts(Tenant(brand_config={}), facts, SalesTurn(mode="suggest", facts=[cal]))
    assert [f for f in mine if f["tool"] == "check_availability"] == [cal]


def test_settings_default_off_and_changes_are_audited(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"s-{uuid.uuid4().hex[:6]}", plan="growth", brand_config={"brand_voice_guide": "warm"})
    db.add(t)
    db.commit()
    assert sales_agent_settings.mode(t) == "off"
    assert sales_agent_settings.update(db, t, None, sales_agent_mode="autopilot") == {"sales_agent_mode": {"from": "off", "to": "autopilot"}}
    db.commit()
    assert t.brand_config == {"brand_voice_guide": "warm", "sales_agent": {"mode": "autopilot"}}
    t.brand_config = {"sales_agent": {"mode": "yes please"}}
    assert sales_agent_settings.mode(t) == "off"


def test_the_model_report_says_what_answers_guests():
    r = report(Tenant(llm_provider_override="nvidia"))
    assert r["guest_reply"]["provider"] == "gemini" and r["override_applied"] is False and r["tenant_override"] == "nvidia"
    assert {t["task"] for t in r["tasks"]} >= {"concierge_draft", "quick_classify"}
    assert r["keys"]["GEMINI_API_KEY"] in ("present", "absent") and r["keys"]["NVIDIA_API_KEY"] in ("present", "absent")


def test_autopilot_holds_for_a_guest_who_said_stop(db, monkeypatch):
    """A STOP keyword withdraws marketing consent (opt_out_responder). The AI must then never send a quote by itself."""
    from app.models.consent import Consent
    from app.services import sales_agent_service as sas
    monkeypatch.setattr(sas.qss, "readiness", lambda *a, **k: {"blockers": [], "warnings": []})
    w = ratha(db)
    inq = lead(db, w.t.id)
    guest = db.query(Guest).filter_by(id=inq.guest_id).first()
    holds = sas._holds(db, w.t.id, [object()], guest, False, "confirmed", {})
    assert holds == ["Your AI policy says a person approves payment links before they go out."]   # the default policy
    w.t.brand_config = {"agent_policy": {"modes": {"send_payment_link": "autonomous"}}}
    db.commit()
    assert sas._holds(db, w.t.id, [object()], guest, False, "confirmed", {}) == []          # no STOP: nothing holds it back
    db.add(Consent(id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=guest.id, channel="whatsapp", scope="marketing",
                   granted=False, source="user_keyword", recorded_at="2026-10-18T10:00:00+00:00"))
    db.commit()
    holds = sas._holds(db, w.t.id, [object()], guest, False, "confirmed", {})
    assert len(holds) == 1 and "STOP" in holds[0]
    other = ratha(db)                                                                      # another workspace's STOP never counts
    assert sas.guest_said_stop(db, other.t.id, guest.id) is False
