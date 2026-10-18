"""Public property assessment: free estimate, lead capture for the full report (via POST /public/leads), report +
PDF behind a token, versioned benchmarks for HAIP admins, and the optional AI write-up's number guard."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core.security import create_access_token
from app.models.audit_event import AuditEvent
from app.models.inquiry import Inquiry
from app.models.platform_lead import PlatformLead
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import assessment_benchmarks, assessment_narrative

ANSWERS = {"plot_size": 30000, "plot_unit": "sqft", "rooms": 12, "property_type": "hotel", "amenities": ["pool"],
           "experiences": ["trekking"], "city": "Madikeri", "district": "Kodagu", "landmark": "tourist_spot",
           "landmark_km": 8, "seasonality": "hill_coffee", "competitor_density": "medium"}
SEED = assessment_benchmarks.seed()["version"]


@pytest.fixture(autouse=True)
def _quiet():
    with patch("app.middleware.rate_limit._check_limit", return_value=(True, 0)), \
         patch("app.workers.tasks.platform_leads.notify_owners.delay"), \
         patch("app.workers.tasks.assessment_narrative.write_narrative.delay") as narrative:
        yield narrative


@pytest.fixture()
def sales_ws(db, tenant_and_user, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_LEADS_TENANT_SLUG", tenant_and_user["tenant"].slug)
    return tenant_and_user


def _auth(ctx):
    return {"Authorization": f"Bearer {ctx['access_token']}"}


def _user(db, tenant_id, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name="U", email=f"u-{uuid.uuid4().hex[:6]}@x.com",
             hashed_password="x", role=role, is_active=True)
    db.add(u)
    db.commit()
    return {"Authorization": "Bearer " + create_access_token({"sub": u.id, "tenant_id": tenant_id, "role": role.value})}


def lead_body(**over):
    body = {"kind": "assessment", "submission_id": uuid.uuid4().hex, "name": "Kiran", "phone": "9845012345",
            "company": "Kiran Estates", "consent": True, "assessment": dict(ANSWERS)}
    body.update(over)
    return body


def test_options_come_from_the_active_benchmarks(client):
    r = client.get("/api/v1/public/assessment/options")
    assert r.status_code == 200
    assert r.json()["benchmark_version"] == SEED and {"key": "pool", "label": "Swimming pool"} in r.json()["amenities"]


def test_estimate_returns_only_the_summary(client, db):
    r = client.post("/api/v1/public/assessment/estimate", json=ANSWERS)
    assert r.status_code == 200, r.text
    s = r.json()["summary"]
    assert s["benchmark_version"] == SEED and s["segment"] == "medium"
    assert "monthly" not in s and "zoning" not in s
    assert db.query(PlatformLead).count() == 0                       # an estimate writes nothing


@pytest.mark.parametrize("over", [{"rooms": 500}, {"plot_size": 10}, {"amenities": ["helipad"]},
                                  {"seasonality": "Bad Key"}, {"landmark": "moon"}])
def test_estimate_rejects_bad_answers(client, over):
    assert client.post("/api/v1/public/assessment/estimate", json={**ANSWERS, **over}).status_code == 422


def test_full_report_needs_a_lead_and_is_stored_once(client, db, sales_ws, _quiet):
    body = lead_body(report={"yearly": "forged"})                    # a page-sent result is ignored
    first = client.post("/api/v1/public/leads", json=body)
    assert first.status_code == 201, first.text
    data = first.json()
    assert data["report"]["benchmark_version"] == SEED and len(data["report"]["monthly"]) == 12
    assert data["report"]["zoning"]["zones"] and data["report_token"]
    again = client.post("/api/v1/public/leads", json=body)
    assert again.status_code == 200 and again.json()["report_token"] == data["report_token"]
    assert again.json()["report"] == data["report"]
    assert db.query(PlatformLead).filter_by(submission_id=body["submission_id"]).count() == 1

    lead = db.query(PlatformLead).filter_by(id=data["id"]).one()
    assert lead.assessment["input"]["city"] == "Madikeri" and lead.narrative_status == "pending"
    _quiet.assert_called_once_with(lead.id)
    inquiry = db.query(Inquiry).filter_by(id=lead.workspace_inquiry_id).one()
    assert inquiry.custom_fields["assessment"]["benchmark_version"] == SEED


def test_full_report_needs_a_phone(client, sales_ws):
    r = client.post("/api/v1/public/leads", json=lead_body(phone=None, email="k@x.in"))
    assert r.status_code == 422


def test_honeypot_assessment_gets_no_report(client, db, sales_ws):
    r = client.post("/api/v1/public/leads", json=lead_body(website="x"))
    assert r.status_code == 201 and r.json()["report"] is None and r.json()["report_token"] is None


def test_report_and_pdf_open_only_with_the_token(client, sales_ws):
    data = client.post("/api/v1/public/leads", json=lead_body()).json()
    url = f"/api/v1/public/assessment/{data['id']}/report"
    ok = client.get(url, params={"token": data["report_token"]})
    assert ok.status_code == 200 and ok.json()["report"]["benchmark_version"] == SEED
    assert client.get(url, params={"token": "x" * 32}).status_code == 404
    other = client.post("/api/v1/public/leads", json=lead_body()).json()
    assert client.get(url, params={"token": other["report_token"]}).status_code == 404     # another report's token
    pdf = client.get(url + ".pdf", params={"token": data["report_token"]})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF") and len(pdf.content) > 3000


def test_pdf_renders_with_a_narrative_and_warnings():
    from app.schemas.assessment import AssessmentInput
    from app.services import assessment_engine, assessment_pdf
    result = assessment_engine.project(assessment_benchmarks.seed(),
                                       AssessmentInput(**{**ANSWERS, "rooms": 80, "plot_size": 6000}))
    assert result["warnings"]
    assert assessment_pdf.render(result, narrative="A short note.", prepared_for="Kiran").startswith(b"%PDF")


# ── Versioned benchmarks ─────────────────────────────────────────────────────

def _new_version(name="ka-2026-11-v2"):
    data = assessment_benchmarks.seed()
    data["version"], data["label"], data["sample"] = name, "Karnataka, owner figures", False
    data["property_types"]["hotel"]["adr"]["medium"] = 8400                   # double the sample rate
    return {"data": data, "notes": "Owner's first numbers"}


def test_new_version_is_inactive_until_activated_and_old_reports_never_change(client, db, sales_ws):
    before = client.post("/api/v1/public/leads", json=lead_body()).json()
    created = client.post("/api/v1/roi-benchmarks", json=_new_version(), headers=_auth(sales_ws))
    assert created.status_code == 201 and created.json()["is_active"] is False
    assert client.post("/api/v1/public/assessment/estimate", json=ANSWERS).json()["summary"]["benchmark_version"] == SEED

    assert client.post("/api/v1/roi-benchmarks/ka-2026-11-v2/activate", headers=_auth(sales_ws)).status_code == 200
    s = client.post("/api/v1/public/assessment/estimate", json=ANSWERS).json()["summary"]
    assert s["benchmark_version"] == "ka-2026-11-v2" and s["benchmark_sample"] is False
    old = client.get(f"/api/v1/public/assessment/{before['id']}/report", params={"token": before["report_token"]}).json()
    assert old["report"] == before["report"] and old["report"]["benchmark_version"] == SEED
    assert s["yearly_revenue"]["likely"] > before["report"]["yearly"]["likely"]["revenue"]

    listed = client.get("/api/v1/roi-benchmarks", headers=_auth(sales_ws)).json()
    assert listed["active"] == "ka-2026-11-v2" and {i["version"] for i in listed["items"]} == {"ka-2026-11-v2", SEED}
    actions = {a.action for a in db.query(AuditEvent).filter_by(tenant_id=sales_ws["tenant"].id).all()}
    assert {"roi_benchmarks.created", "roi_benchmarks.activated"} <= actions

    assert client.post(f"/api/v1/roi-benchmarks/{SEED}/activate", headers=_auth(sales_ws)).status_code == 200
    assert client.post("/api/v1/public/assessment/estimate", json=ANSWERS).json()["summary"]["benchmark_version"] == SEED


def test_a_version_is_never_overwritten(client, sales_ws):
    assert client.post("/api/v1/roi-benchmarks", json=_new_version(), headers=_auth(sales_ws)).status_code == 201
    assert client.post("/api/v1/roi-benchmarks", json=_new_version(), headers=_auth(sales_ws)).status_code == 409
    assert client.post("/api/v1/roi-benchmarks", json=_new_version(SEED), headers=_auth(sales_ws)).status_code == 409


def test_invalid_benchmarks_are_refused(client, sales_ws):
    body = _new_version()
    body["data"]["scenarios"]["low"]["occ_mult"] = 2.0
    assert client.post("/api/v1/roi-benchmarks", json=body, headers=_auth(sales_ws)).status_code == 422
    assert client.post("/api/v1/roi-benchmarks/nope/activate", headers=_auth(sales_ws)).status_code == 404


def test_benchmarks_forbidden_for_a_manager(client, db, sales_ws):
    headers = _user(db, sales_ws["tenant"].id, UserRole.MANAGER)
    assert client.get("/api/v1/roi-benchmarks", headers=headers).status_code == 403
    assert client.post("/api/v1/roi-benchmarks", json=_new_version(), headers=headers).status_code == 403


def test_benchmarks_forbidden_for_another_workspaces_owner(client, db, sales_ws):
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    headers = _user(db, other.id, UserRole.OWNER)
    assert client.post("/api/v1/roi-benchmarks", json=_new_version(), headers=headers).status_code == 403
    assert client.post(f"/api/v1/roi-benchmarks/{SEED}/activate", headers=headers).status_code == 403


# ── AI write-up: may only restate computed numbers ───────────────────────────

def _assessment_lead(client):
    return client.post("/api/v1/public/leads", json=lead_body()).json()


def test_narrative_with_only_computed_numbers_is_kept(client, db, sales_ws):
    import re
    lead_id = _assessment_lead(client)["id"]
    lead = db.query(PlatformLead).filter_by(id=lead_id).one()
    facts = assessment_narrative.facts(lead.assessment["result"])
    likely = re.search(r"likely (₹[0-9,]+)", facts).group(1)
    payback = re.search(r"Payback \(likely\): ([0-9]+) months", facts).group(1)
    reply = f"Estimates from sample benchmarks: about {likely} a year, paying back in {payback} months."
    with patch.object(assessment_narrative, "_complete", new=AsyncMock(return_value=reply)):
        assert assessment_narrative.write(db, lead_id)["status"] == "done"
    assert db.query(PlatformLead).filter_by(id=lead_id).one().narrative == reply
    report = client.get(f"/api/v1/public/assessment/{lead_id}/report", params={"token": _token_for(lead_id)}).json()
    assert report["narrative"] == reply


def _token_for(lead_id):
    from app.services.platform_lead_service import report_token
    return report_token(lead_id)


@pytest.mark.parametrize("reply", ["It could earn about 5.4 crore a year.", "Payback in 7 months.", ""])
def test_narrative_with_an_invented_number_is_rejected(client, db, sales_ws, reply):
    lead_id = _assessment_lead(client)["id"]
    with patch.object(assessment_narrative, "_complete", new=AsyncMock(return_value=reply)):
        assert assessment_narrative.write(db, lead_id)["status"] == "rejected"
    lead = db.query(PlatformLead).filter_by(id=lead_id).one()
    assert lead.narrative is None and lead.narrative_prompt_version == "assessment-narrative-v1"


def test_narrative_provider_failure_is_recorded(client, db, sales_ws):
    lead_id = _assessment_lead(client)["id"]
    with patch.object(assessment_narrative, "_complete", new=AsyncMock(side_effect=TimeoutError())):
        assert assessment_narrative.write(db, lead_id)["status"] == "failed"


def test_narrative_can_be_switched_off(client, db, sales_ws, monkeypatch, _quiet):
    monkeypatch.setattr("app.core.config.settings.ASSESSMENT_NARRATIVE_ENABLED", False)
    lead_id = _assessment_lead(client)["id"]
    assert db.query(PlatformLead).filter_by(id=lead_id).one().narrative_status == "off"
    _quiet.assert_not_called()


def test_number_guard_unit():
    facts = "Yearly revenue: likely ₹5,37,41,372. Payback (likely): 30 months. OTA share: 45%."
    assert assessment_narrative.check_numbers(facts, "About ₹5,37,41,372 a year; payback 30 months; 45% via OTAs.") is None
    assert assessment_narrative.check_numbers(facts, "About 5.37 crore") is not None
    assert assessment_narrative.check_numbers(facts, "payback 31 months") is not None


def test_narrative_route_is_the_internal_tier():
    from app.adapters.llm import _GEMINI_FALLBACK_TASKS, _TASK_ROUTES
    assert _TASK_ROUTES["assessment_narrative"] == ("nvidia", "openai/gpt-oss-20b")
    assert "assessment_narrative" in _GEMINI_FALLBACK_TASKS
