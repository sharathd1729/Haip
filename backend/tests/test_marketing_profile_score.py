"""Instagram toolkit phase 3: the 12-item profile score, its SOP steps and checks, and GET /profile-score."""
import uuid
from unittest.mock import patch

from app.models.integration import Integration
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.schemas.sops import StartIn
from app.services import marketing_profile_score as profile
from app.services.sops import catalogue, generate
from app.services.sops import service as sop_svc
from tests.conftest import seed_capabilities
from tests.test_marketing_studio_content import BASE, enable_module, make_user, ws  # noqa: F401  (fixture)

FIELDS = {"name": "Nila Stays | Pool villas, Coonoor", "username": "nilastays", "website": "https://nila.example",
          "biography": "Pool villas in Coonoor for families who want slow mornings.\nRated 4.9 by 300 guests. DM us for dates."}


def test_rubric_is_twelve_items_worth_100_and_each_is_a_checklist_step():
    assert len(profile.RUBRIC["items"]) == 12 and sum(i["points"] for i in profile.RUBRIC["items"]) == 100
    steps = {s.key: s for s in catalogue.BY_KEY["instagram_profile"].steps}
    for item in profile.RUBRIC["items"]:
        assert all(k in steps for k in item["steps"]), item["id"]
        assert steps[item["steps"][0]].points == item["points"], item["id"]
    assert sum(s.points for s in steps.values()) == 100


def test_measured_items_judge_the_profile_fields():
    assert profile.name_points(FIELDS["name"], "Nila Stays")[0] == 12
    assert profile.name_points("Nila Stays", "Nila Stays")[0] == 4
    assert profile.bio_line_points(FIELDS["biography"], "Coonoor")[0] == 12
    assert profile.bio_line_points("Travel | Food | Life")[0] == 4
    assert profile.bio_body_points(FIELDS["biography"])[0] == 8 and profile.bio_body_points("Villas.")[0] == 0
    assert profile.link_points("")[0] == 0 and profile.handle_points("nila__stays_2")[0] == 3


def _start(db, tenant, owner_id):
    inst = sop_svc.start(db, tenant, StartIn(template_key="instagram_profile"), owner_id)
    generate.make_version(db, tenant, inst, reason="first", actor_id=owner_id, use_ai=False)
    db.commit()
    return inst


def test_score_reads_checks_and_ticked_steps(db, ws):
    t, owner = ws["tenant"], ws["owner"]
    assert profile.score(db, t)["score"] == 0 and profile.score(db, t)["started"] is False
    inst = _start(db, t, owner.id)
    db.add(Integration(tenant_id=t.id, kind="instagram", status="active", config={}))
    db.flush()
    with patch("app.services.sops.checks._ig_fields", return_value=FIELDS):
        sop_svc.run_checks(db, t, inst)
    sop_svc.mark(db, inst, "pinned", "done", owner.id)
    db.commit()
    got = profile.score(db, t)
    by = {i["id"]: i for i in got["items"]}
    assert by["name_field"]["points"] == 12 and by["name_field"]["source"] == "measured"
    assert by["link"]["points"] == 8 and by["pinned_three"]["points"] == 10 and by["pinned_three"]["fix"] is None
    assert by["recent_activity"]["points"] == 0 and by["recent_activity"]["fix"]          # no posts in 30 days
    assert by["category_contact"]["points"] == 0                                         # needs both steps ticked
    assert got["score"] == 12 + 12 + 8 + 8 + 6 + 10 and got["items"][0]["max"] - got["items"][0]["points"] >= 6


def test_profile_score_endpoint_roles_and_tenants(client, db, ws):
    inst = _start(db, ws["tenant"], ws["owner"].id)
    sop_svc.mark(db, inst, "pinned", "done", ws["owner"].id)
    db.commit()
    r = client.get(f"{BASE}/profile-score", headers=ws["mkt_h"])
    assert r.status_code == 200 and r.json()["score"] == 10 and r.json()["sop_id"] == inst.id
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.get(f"{BASE}/profile-score", headers=foh_h).status_code == 403
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    seed_capabilities(db, other.id)
    enable_module(db, other.id)
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    theirs = client.get(f"{BASE}/profile-score", headers=other_h).json()
    assert theirs["score"] == 0 and theirs["sop_id"] is None and theirs["started"] is False
