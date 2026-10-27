"""Trip Account Report (ops_trip_report) reproduces the real Saleem report's figures, and the daily file sync (ops_files task)."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.ops_files import OpsFile
from app.models.stay_finance import StayPayment
from app.models.user import UserRole
from app.schemas.ops_files import ExpenseIn
from app.services import ops_money as money
from app.services import ops_trip_report as report
from app.services import ops_trip_service as trips
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop, staff
from tests.test_increment1_defect_specs import _h, _user
from tests.test_ops_files import _actor_u1, TODAY, _green_all_critical, _pay, _ready_file, _stay, _tenant


@pytest.fixture()
def saleem(db):
    t = _tenant(db)
    p = prop(db, t.id, "Ratha 1")
    w = type("W", (), {"t": t, "p": p, "stay": _stay(db, t, p, start=0), "driver": staff(db, t.id, "Suresh", "driver"),
                       "helper": staff(db, t.id, "Raju", "driver")})()
    f = _ready_file(db, w)
    _green_all_critical(db, f)
    _pay(db, w.stay, "126732")
    trips.refresh(db, f)
    trips.dispatch(db, f, 87396, "u1")
    for cat, amt in (("driver", "8750"), ("helper", "1300"), ("fuel", "17620.60")):
        money.add_expense(db, f, ExpenseIn(category=cat, amount=Decimal(amt)), actor_id="u1")
    trips.end_trip(db, f, 88792)
    db.add(StayPayment(tenant_id=t.id, stay_id=w.stay.id, amount=Decimal("12740"), method="upi", paid_on=TODAY + timedelta(days=3)))
    db.flush()
    w.f = f
    return w


def _rows(rep, title):
    s = next(s for s in rep["sections"] if s["title"].startswith(title))
    return {label: value for label, value, _ in s["rows"]}


def test_report_has_the_saleem_figures(db, saleem):
    rep = report.build(db, saleem.f)
    assert [s["title"][:2] for s in rep["sections"]] == ["1.", "2.", "3.", "4.", "5.", "6.", "7."]
    pay = _rows(rep, "2.")
    assert (pay["Package cost"], pay["GST @ 18%"], pay["Original package total"], pay["Advance received"]) == (
        "Rs. 1,07,400", "Rs. 19,332", "Rs. 1,26,732", "Rs. 1,26,732")
    km = _rows(rep, "3.")
    assert (km["Actual distance travelled"], km["Extra kilometres"], km["Extra km charges"]) == ("1,396 km", "196 km", "Rs. 12,740")
    assert km["Extra km rate"] == "Rs. 65/km (including 18% GST)"
    revised = {l: v for l, v, _ in rep["sections"][2]["then"]["rows"]}
    assert (revised["Total trip revenue"], revised["Additional amount received"], revised["Final balance"]) == (
        "Rs. 1,39,472", "Rs. 12,740", "Rs. 0")
    assert _rows(rep, "4.")["Total expenses"] == "Rs. 27,670.60"
    assert [l for l, _, _ in rep["sections"][3]["rows"]][:3] == ["Driver hiring expense", "Helper expense", "Diesel / fuel cost"]
    assert _rows(rep, "5.")["Net cash surplus"] == "Rs. 1,11,801.40"
    gst = _rows(rep, "6.")
    assert (gst["Extra km revenue excluding GST"], gst["Revenue excluding GST"], gst["Net revenue excluding GST"]) == (
        "Rs. 10,796.61", "Rs. 1,18,196.61", "Rs. 90,526.01")
    assert "Extras revenue excluding GST" not in gst
    assert _rows(rep, "7.")["Outstanding balance"] == "Rs. 0"


def test_contact_is_masked_and_draft_until_approved(db, saleem):
    rep = report.build(db, saleem.f)
    phone = saleem.stay.guest.phone
    assert _rows(rep, "1.")["Contact number"] == "xxxxxx" + phone[-4:] and phone not in str(rep)
    assert rep["draft"] is True
    trips.settle(db, saleem.f, "report_approved", "u1")
    assert report.build(db, saleem.f)["draft"] is False


def test_pdf_text_is_safe_for_the_built_in_font():
    assert report._safe("Bangalore → Coorg ₹65 <b>") == "Bangalore -&gt; Coorg Rs. 65 &lt;b&gt;"     # Paragraph markup
    assert report._latin("Rao & family → Café ✓") == "Rao & family -> Café ?"                        # canvas text


def test_render_makes_a_pdf_even_before_the_trip(db):
    t = _tenant(db)
    p = prop(db, t.id)
    f = trips.ensure_file(db, t.id, _stay(db, t, p))
    pdf = report.render(report.build(db, f))
    assert pdf[:5] == b"%PDF-" and len(pdf) > 2000


def test_report_endpoint_roles_and_tenants(client, db, saleem):
    seed_capabilities(db, saleem.t.id)
    db.commit()
    url = f"/api/v1/ops/files/{saleem.f.id}/report.pdf"
    r = client.get(url, headers=_h(_user(db, saleem.t.id, UserRole.MANAGER)))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:5] == b"%PDF-"
    assert "attachment" in r.headers["content-disposition"]
    assert client.get(url, headers=_h(_user(db, saleem.t.id, UserRole.FOH))).status_code == 403
    other = _tenant(db)
    seed_capabilities(db, other.id)
    assert client.get(url, headers=_h(_user(db, other.id, UserRole.MANAGER))).status_code == 404


# ── Daily sync ──────────────────────────────────────────────────────────────

class _NoClose:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *exc):
        return False


def test_daily_job_opens_files_only_for_businesses_with_a_pack(db):
    from app.workers.tasks import ops_files as task
    caravan, hotel = _tenant(db), _tenant(db, "hotel")
    s = _stay(db, caravan, prop(db, caravan.id), start=4)
    with patch.object(task, "SessionLocal", return_value=_NoClose(db)), \
         patch.object(task.sync_files_tenant, "delay") as delay:
        task.sync_files_all.run()
    tenants = {c.args[0] for c in delay.call_args_list}
    assert caravan.id in tenants and hotel.id not in tenants
    with patch.object(task, "SessionLocal", return_value=_NoClose(db)):
        assert task.sync_files_tenant.run(caravan.id)["created"] == 1
        assert task.sync_files_tenant.run(caravan.id)["created"] == 0
    assert db.query(OpsFile).filter_by(stay_id=s.id).count() == 1
