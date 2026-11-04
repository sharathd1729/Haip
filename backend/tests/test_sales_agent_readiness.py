"""The AI sales agent's readiness checklist (sales_agent_readiness.checklist, GET /ai/sales-agent "checklist")."""

from app.services import sales_agent_readiness as sar
from tests.test_increment1_defect_specs import _h
from tests.test_quote_builder_pricing import ratha
from tests.test_quote_send import approve_quote_template, connect_razorpay

S = "/api/v1/ai/sales-agent"


def _rows(out):
    return {r["key"]: r for r in out["rows"]}


def _set(db, w, **cfg):
    w.t.brand_config = {**(w.t.brand_config or {}), **cfg}
    db.commit()


def test_defaults_say_what_is_missing_and_where_to_fix_it(db):
    w = ratha(db)
    out = sar.checklist(db, w.t)
    rows = _rows(out)
    assert out["mode"] == "off" and out["suggest_ready"] is False and out["autopilot_ready"] is False
    assert rows["agent_on"]["ok"] is False and rows["agent_on"]["fix"]["href"] == "#sales-agent"
    assert rows["prices"]["ok"] is False
    assert rows["packages"]["ok"] is True and rows["packages"]["fix"] is None
    assert rows["payment_terms"]["ok"] is True and "50" in rows["payment_terms"]["detail"]
    assert rows["razorpay"]["ok"] is False and rows["razorpay"]["fix"]["href"] == "/dashboard/settings/payments"
    assert rows["quote_template"]["ok"] is False
    assert rows["link_policy"]["ok"] is False and rows["link_policy"]["fix"]["href"] == "#agent-policy"
    assert {r["group"] for r in out["rows"]} == {"suggest", "autopilot", "after"}


def test_suggest_is_ready_once_its_rows_are_green(db):
    w = ratha(db)
    _set(db, w, price_disclosure="grounded", sales_agent={"mode": "suggest"})
    connect_razorpay(db, w.t.id)
    approve_quote_template(db, w.t.id)
    out = sar.checklist(db, w.t)
    assert out["suggest_ready"] is True and out["autopilot_ready"] is False


def test_the_learning_cap_is_named_and_has_no_false_fix(db):
    w = ratha(db)
    _set(db, w, agent_policy={"modes": {"send_payment_link": "autonomous"}}, learning={})
    row = _rows(sar.checklist(db, w.t))["link_policy"]
    assert row["ok"] is False and row["fix"] is None and "learning" in row["detail"]
    w.t.brand_config = {k: v for k, v in w.t.brand_config.items() if k != "learning"}
    db.commit()
    assert _rows(sar.checklist(db, w.t))["link_policy"]["ok"] is True


def test_another_workspaces_razorpay_does_not_count(db):
    mine, other = ratha(db), ratha(db)
    connect_razorpay(db, other.t.id)
    assert _rows(sar.checklist(db, mine.t))["razorpay"]["ok"] is False


def test_the_settings_endpoint_returns_the_checklist_to_owner_and_manager(client, db):
    w = ratha(db)
    for user in (w.owner, w.mgr):
        body = client.get(S, headers=_h(user)).json()
        assert {r["key"] for r in body["checklist"]["rows"]} >= {
            "agent_on",
            "prices",
            "packages",
            "razorpay",
            "link_policy",
        }
    assert client.get(S, headers=_h(w.ro)).status_code == 403
