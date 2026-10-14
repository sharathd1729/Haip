"""K-5: the knowledge test box runs the code a real reply runs, shows sources and versions, and flags missing or contradictory data.

Retrieval of descriptive text is replaced by a recording fake (vector search needs PostgreSQL; it is covered by its own suite); the
structured side, pricing, availability, flags and permissions are real.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest

from app.models.property import Property
from app.services import knowledge_service, sales_gateway
from app.services.knowledge_service import SearchOutcome
from tests.test_business_data import coorg, package
from tests.test_increment1_defect_specs import _h
from tests.test_business_data import TODAY, _workspace
from tests.test_package_pricing import CI, CO, publish, rates, vehicle
from tests.workers.test_concierge_operational_data import Scripted, _avail, _conversation, _run, _tenant, _property

URL = "/api/v1/knowledge/test"


@pytest.fixture()
def w(db):
    return _workspace(db)


@pytest.fixture()
def pub(db, w):
    vehicle(db, w)
    publish(db, w, "coorg", coorg(), kind="destination")
    publish(db, w, "coorg-signature", package(destination_keys=["coorg"], rates=[rates()]))
    return w


def hit(content, id_="aaaaaaaa-1111"):
    return {"id": id_, "category": "faq", "question": "Q", "content": content, "source": "manual", "property_id": None, "score": 0.9}


def body(**over):
    return {"query": "Coorg trip price?", "details": {"destination": "Coorg", "check_in": CI.isoformat(), "check_out": CO.isoformat(), "adults": 2}, **over}


def test_shows_knowledge_structured_data_a_quote_and_where_each_came_from(client, pub):
    with patch.object(knowledge_service, "search_detailed", return_value=SearchOutcome(hits=[hit("Coffee estates nearby.")])):
        r = client.post(URL, json=body(), headers=_h(pub.owner))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["kb"]["hits"][0]["content"] == "Coffee estates nearby." and j["kb"]["status"] == "ok"
    assert j["structured"]["matched_package"] == "coorg-signature"
    assert j["structured"]["quote"]["total"] == "40320.00" and j["structured"]["quote_sources"][0] == {"kind": "package", "key": "coorg-signature", "version": 1}
    assert {(s["kind"], s["key"], s["version"]) for s in j["structured"]["sources"]} >= {("package", "coorg-signature", 1), ("destination", "coorg", 1)}
    assert j["structured"]["descriptive"]["packages"][0]["name"] == "Signature Caravan - Coorg"
    assert j["ai_sees_prices"] is False and any(f["code"] == "price_mode_handoff" for f in j["flags"])           # default workspace: hand-off
    refs = [(s["kind"], s["key"], s["version"]) for s in j["structured"]["sources"]]
    assert len(refs) == len(set(refs))                                                                           # each source listed once
    assert all(not f["message"].endswith("..") for f in j["flags"])


def test_it_calls_exactly_the_functions_a_real_reply_calls_with_the_same_arguments(db, client, pub):
    calls = {"gateway": [], "search": []}
    real_gw, real_search = sales_gateway.concierge_business_facts, knowledge_service.search_detailed

    def spy_gw(db_, tenant_id, details=None):
        calls["gateway"].append((tenant_id, dict(details or {})))
        return real_gw(db_, tenant_id, details)

    def spy_search(db_, tenant_id, query, **kw):
        calls["search"].append((tenant_id, kw.get("property_id")))
        return real_search(db_, tenant_id, query, **kw)

    with patch.object(sales_gateway, "concierge_business_facts", spy_gw), patch.object(knowledge_service, "search_detailed", spy_search):
        assert client.post(URL, json=body(), headers=_h(pub.owner)).status_code == 200
        box_gateway, box_search = list(calls["gateway"]), list(calls["search"])

        calls["gateway"].clear(), calls["search"].clear()
        t = _tenant(db, mode="autonomous")
        _property(db, t)
        _, conv, (msg,) = _conversation(db, t, "Coorg trip price?")
        _run(db, t, conv, msg, Scripted(_avail({"intent": "price_quote", "destination": "Coorg"})))
    assert box_gateway and calls["gateway"] and box_search and calls["search"]                                   # both paths used both functions
    assert calls["gateway"][0][1].get("destination") == "Coorg"                                                  # the reply path hands over what the guest said


def test_missing_data_is_flagged_and_gives_no_price(db, client, w):
    with patch.object(knowledge_service, "search_detailed", return_value=SearchOutcome(status="no_match")):
        j = client.post(URL, json=body(), headers=_h(w.owner)).json()
    codes = {f["code"]: f for f in j["flags"]}
    assert "no_business_data" in codes and "kb_no_match" in codes and j["structured"]["quote"] is None and j["structured"]["matched_package"] is None


def test_a_quote_that_cannot_be_given_is_flagged_as_blocking_without_a_figure(client, pub):
    with patch.object(knowledge_service, "search_detailed", return_value=SearchOutcome()):
        j = client.post(URL, json=body(details={"destination": "Coorg", "check_in": CI.isoformat(), "check_out": CO.isoformat(), "adults": 9}), headers=_h(pub.owner)).json()
    flag = next(f for f in j["flags"] if f["code"].startswith("quote_refused"))
    assert flag["code"] == "quote_refused:over_capacity" and flag["severity"] == "block"
    assert "total" not in j["structured"]["quote"]


def test_a_package_without_dates_asks_for_them_instead_of_guessing(client, pub):
    with patch.object(knowledge_service, "search_detailed", return_value=SearchOutcome()):
        j = client.post(URL, json={"query": "Coorg?", "details": {"destination": "Coorg"}}, headers=_h(pub.owner)).json()
    assert j["structured"]["matched_package"] == "coorg-signature" and j["structured"]["quote"] is None
    assert any(f["code"] == "quote_needs_details" and "dates" in f["message"] for f in j["flags"])


def test_a_price_in_prose_that_disagrees_with_the_published_rate_is_flagged(client, pub):
    old = hit("Our Coorg trip is Rs 15,000 per night.")
    ok = hit("The Coorg caravan rate is Rs 18,000 per night.", id_="bbbbbbbb-2222")
    with patch.object(knowledge_service, "search_detailed", return_value=SearchOutcome(hits=[old, ok])):
        j = client.post(URL, json=body(), headers=_h(pub.owner)).json()
    texts = [f["message"] for f in j["flags"] if f["code"] == "kb_price_in_text"]
    assert len(texts) == 2 and "15000" in texts[0] and "do not match any published rate" in texts[0] and "match a published rate" in texts[1] and "do not match" not in texts[1]


def test_unpublished_or_contradictory_records_are_flagged_in_plain_words(db, client, pub):
    from app.models.business_record import BusinessRecord
    db.query(BusinessRecord).filter_by(tenant_id=pub.t.id, kind="destination").update({"status": "inactive"})
    db.commit()
    with patch.object(knowledge_service, "search_detailed", return_value=SearchOutcome()):
        j = client.post(URL, json=body(), headers=_h(pub.owner)).json()
    assert any("Destination 'coorg' is referenced but not published" in f["message"] for f in j["flags"])


def test_drafts_are_never_previewed(db, client, pub):
    from app.services import business_data_service as bds
    bds.create_draft(db, pub.t.id, "package", "coorg-signature", package(destination_keys=["coorg"], rates=[rates("99999")]), pub.owner.id)
    with patch.object(knowledge_service, "search_detailed", return_value=SearchOutcome()):
        j = client.post(URL, json=body(), headers=_h(pub.owner)).json()
    assert j["structured"]["quote"]["total"] == "40320.00"


def test_grounded_workspaces_report_that_the_ai_sees_prices(db, client, pub):
    pub.t.brand_config = {"price_disclosure": "grounded"}
    db.commit()
    with patch.object(knowledge_service, "search_detailed", return_value=SearchOutcome()):
        j = client.post(URL, json=body(), headers=_h(pub.owner)).json()
    assert j["ai_sees_prices"] is True and not any(f["code"] == "price_mode_handoff" for f in j["flags"])


def test_only_people_who_manage_settings_may_use_it_and_tenants_stay_apart(db, client, pub):
    assert client.post(URL, json=body(), headers=_h(pub.ro)).status_code == 403
    other = _workspace(db)
    with patch.object(knowledge_service, "search_detailed", return_value=SearchOutcome()):
        j = client.post(URL, json=body(), headers=_h(other.owner)).json()
    assert j["structured"]["matched_package"] is None and j["structured"]["sources"] == []
    r = client.post(URL, json=body(property_id="not-mine"), headers=_h(pub.owner))
    assert r.status_code == 422
    assert client.post(URL, json=body(conversation_id="nope"), headers=_h(pub.owner)).status_code == 404
