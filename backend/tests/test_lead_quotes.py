"""Staff quotes on a lead (endpoints/lead_quotes.py) and staff custom lines (package_pricing_service.custom_lines).

What these pin:
  * a custom line is priced and taxed like any line, marked custom, and changes the quote's identity (params_hash);
  * only the staff path can add custom lines: the AI's gateway has no way to pass them;
  * issuing is audited, returns WhatsApp-ready text in lakh format and the official WhatsApp thread, never a personal-WhatsApp mirror;
  * read_only cannot issue, other tenants and other agents' leads are not found, a refused quote stores nothing;
  * an issued quote keeps its amounts after a later price change.
"""
import inspect
import uuid
from decimal import Decimal

from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.inquiry_360 import InquiryQuote
from app.models.user import UserRole
from app.services import quote_service as qs
from app.services import sales_gateway
from tests.test_business_data import _workspace, package
from tests.test_increment1_defect_specs import _h, _user
from tests.test_package_pricing import CI, CO, publish, q, rates, vehicle, ws  # noqa: F401  (ws is a fixture)
from tests.test_business_data import w  # noqa: F401  (fixture)

BODY = {"package_key": "coorg", "check_in": CI.isoformat(), "check_out": CO.isoformat(), "adults": 2}


def _lead(db, tenant_id, assigned_to=None):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Asha Rao", phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id, source=InquirySource.WA_DIRECT, assigned_to=assigned_to)
    db.add(inq)
    db.commit()
    return inq


def _conv(db, inq, source=None):
    c = Conversation(id=str(uuid.uuid4()), tenant_id=inq.tenant_id, guest_id=inq.guest_id, inquiry_id=inq.id,
                     channel=ChannelType.WHATSAPP, is_open=True, source=source)
    db.add(c)
    db.commit()
    return c


# ─── service: custom lines ────────────────────────────────────────────────────────────────────────────────

def test_a_custom_line_is_priced_taxed_marked_and_part_of_the_quotes_identity(ws, db):
    plain = q(db, ws)
    r = q(db, ws, custom_lines=[{"label": "Birthday decoration", "amount": "2500", "reason": "guest asked"}])
    assert r.ok and r.subtotal == Decimal("38500.00") and r.gst == Decimal("4620") and r.total == Decimal("43120.00")
    assert (r.lines[-1].label, r.lines[-1].amount, r.lines[-1].custom) == ("Birthday decoration", Decimal("2500.00"), True)
    snap = r.to_snapshot()
    assert snap["has_custom_lines"] is True and snap["lines"][-1]["custom"] is True and snap["lines"][0]["custom"] is False
    assert r.params_hash() != plain.params_hash() and "custom_lines" not in plain.inputs


def test_a_zero_or_negative_custom_line_is_refused_without_a_price(ws, db):
    for amount in ("0", "-500", "abc"):
        r = q(db, ws, custom_lines=[{"label": "Odd", "amount": amount}])
        assert not r.ok and r.reason == "invalid_custom_line" and r.total is None


def test_the_ai_gateway_cannot_add_custom_lines():
    assert "custom_lines" not in inspect.signature(sales_gateway.quote_package).parameters


def test_rupees_are_written_in_lakh_format():
    assert [qs.inr(Decimal(v)) for v in ("999", "125000", "12500000.50", "-1500")] == ["₹999", "₹1,25,000", "₹1,25,00,000.50", "-₹1,500"]


# ─── API ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_issue_with_a_custom_line_is_audited_and_returns_text_and_the_official_thread(ws, db, client):
    inq = _lead(db, ws.t.id)
    _conv(db, inq, source="personal_bridge")                             # a read-only mirror is never offered as the send thread
    official = _conv(db, inq)
    body = {**BODY, "custom_lines": [{"label": "Birthday decoration", "amount": "2500"}]}
    pre = client.post(f"/api/v1/leads/{inq.id}/quotes/preview", json=body, headers=_h(ws.owner))
    assert pre.status_code == 200 and pre.json()["ok"] and pre.json()["quote"]["total"] == "43120.00"
    assert db.query(InquiryQuote).filter_by(inquiry_id=inq.id).count() == 0     # a preview stores nothing

    r = client.post(f"/api/v1/leads/{inq.id}/quotes", json=body, headers=_h(ws.owner))
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["quote"]["amount"] == "43120.00" and out["conversation_id"] == official.id
    assert "₹43,120" in out["message_text"] and "Birthday decoration: ₹2,500" in out["message_text"] and "Asha" in out["message_text"]
    ev = db.query(AuditEvent).filter_by(tenant_id=ws.t.id, action="quote.issued").one()
    assert ev.payload["custom_lines"] == [["Birthday decoration", "2500.00"]] and ev.actor_user_id == ws.owner.id


def test_the_list_keeps_the_issued_amount_after_a_price_change_and_flags_it(ws, db, client):
    inq = _lead(db, ws.t.id)
    assert client.post(f"/api/v1/leads/{inq.id}/quotes", json=BODY, headers=_h(ws.owner)).status_code == 201
    publish(db, ws, "coorg", package(rates=[rates("20000")]))           # price goes up after the guest was quoted
    lst = client.get(f"/api/v1/leads/{inq.id}/quotes", headers=_h(ws.owner)).json()
    assert len(lst["quotes"]) == 1 and lst["quotes"][0]["amount"] == "40320.00"
    assert lst["quotes"][0]["validity"]["valid"] is False and lst["quotes"][0]["validity"]["terms_changed"]
    assert lst["conversation_id"] is None                                # no official thread yet: the UI offers copy only


def test_packages_picker_lists_published_packages_for_the_party(ws, db, client):
    inq = _lead(db, ws.t.id)
    r = client.get(f"/api/v1/leads/{inq.id}/quotes/packages?guests=2&nights=2", headers=_h(ws.owner)).json()
    assert r["ok"] and [p["key"] for p in r["data"]] == ["coorg"]
    assert client.get(f"/api/v1/leads/{inq.id}/quotes/packages?guests=9", headers=_h(ws.owner)).json()["data"] == []


def test_a_refused_quote_is_422_and_stores_nothing(ws, db, client):
    inq = _lead(db, ws.t.id)
    r = client.post(f"/api/v1/leads/{inq.id}/quotes", json={**BODY, "adults": 9}, headers=_h(ws.owner))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "over_capacity"
    assert db.query(InquiryQuote).filter_by(inquiry_id=inq.id).count() == 0


def test_read_only_can_see_quotes_but_cannot_issue(ws, db, client):
    inq = _lead(db, ws.t.id)
    assert client.post(f"/api/v1/leads/{inq.id}/quotes", json=BODY, headers=_h(ws.ro)).status_code == 403
    assert client.post(f"/api/v1/leads/{inq.id}/quotes/preview", json=BODY, headers=_h(ws.ro)).status_code == 403
    assert client.get(f"/api/v1/leads/{inq.id}/quotes", headers=_h(ws.ro)).status_code == 200


def test_another_tenants_lead_and_another_agents_lead_are_not_found(ws, db, client):
    other = _workspace(db)
    foreign = _lead(db, other.t.id)
    assert client.post(f"/api/v1/leads/{foreign.id}/quotes", json=BODY, headers=_h(ws.owner)).status_code == 404
    assert client.get(f"/api/v1/leads/{foreign.id}/quotes", headers=_h(ws.owner)).status_code == 404

    agent, colleague = _user(db, ws.t.id, UserRole.CONCIERGE), _user(db, ws.t.id, UserRole.CONCIERGE)
    theirs = _lead(db, ws.t.id, assigned_to=colleague.id)
    assert client.post(f"/api/v1/leads/{theirs.id}/quotes", json=BODY, headers=_h(agent)).status_code == 404
    mine = _lead(db, ws.t.id, assigned_to=agent.id)
    assert client.post(f"/api/v1/leads/{mine.id}/quotes", json=BODY, headers=_h(agent)).status_code == 201
