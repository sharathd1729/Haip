"""AI tags on leads (services/lead_tags.py, written by generate_ai_summary, leads360-summary-v11): only the fixed
vocabulary, a person's tags survive every summary, and GET /leads?tag= filters on them (list and stage chips agree)."""
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from app.core.prompt_versions import get_version
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.tenant import Tenant
from app.services import lead_tags
from app.workers.tasks import generate_ai_summary as gas


def test_clean_keeps_only_the_vocabulary_in_its_own_spelling():
    assert lead_tags.clean(["Anniversary", "anniversary", "VIP", "ready to book", 3, None, "kids"]) == [
        "anniversary", "ready to book", "kids"]
    assert lead_tags.clean("anniversary") == [] and len(lead_tags.clean(list(lead_tags.ALL_TAGS))) == lead_tags.MAX_TAGS


def test_merge_replaces_only_what_the_ai_wrote_last_time():
    assert lead_tags.merge(["VIP", "couple"], ["couple"], ["family", "kids"]) == ["VIP", "family", "kids"]
    assert lead_tags.merge(None, None, ["couple"]) == ["couple"]
    assert lead_tags.merge(["VIP"], ["couple"], ["VIP"]) == ["VIP"]


def test_prompt_lists_the_vocabulary_and_is_versioned():
    assert '"tags"' in gas.SYSTEM_PROMPT and "price sensitive" in gas.SYSTEM_PROMPT and "__TAGS__" not in gas.SYSTEM_PROMPT
    assert get_version("leads360_summary") == "leads360-summary-v11"


def _lead(db, tags=None):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"lt-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Asha", phone="+919800000041", lead_identified_at=datetime.now(UTC))
    db.add(g)
    db.flush()
    i = Inquiry(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, source=InquirySource.WA_DIRECT, tags=tags or [])
    db.add(i)
    db.commit()
    return t.id, i.id


def _summarise(db, tenant_id, inquiry_id, tags):
    payload = {"summary": "A couple wants a caravan trip for their anniversary. No budget yet. Call to confirm dates.",
               "analysis": {"tags": tags}, "extracted": {}}

    class _LLM:
        async def complete(self, **kwargs):
            return {"content": json.dumps(payload), "model": "fake"}

    with patch("app.workers.tasks.generate_ai_summary.get_llm", lambda task: _LLM()), \
         patch("app.workers.tasks.generate_ai_summary.SessionLocal", return_value=db), patch.object(db, "close"):
        gas.generate_ai_summary.run(inquiry_id=inquiry_id, tenant_id=tenant_id, force=True)
    db.expire_all()
    return db.get(Inquiry, inquiry_id)


def test_summary_writes_ai_tags_and_keeps_a_persons(db):
    tid, iid = _lead(db, tags=["VIP"])
    inq = _summarise(db, tid, iid, ["couple", "Anniversary", "made up tag"])
    assert inq.tags == ["VIP", "couple", "anniversary"] and inq.ai_analysis["ai_tags"] == ["couple", "anniversary"]
    inq = _summarise(db, tid, iid, ["family"])            # the guest said more: the AI's own tags change, VIP stays
    assert inq.tags == ["VIP", "family"]


def test_leads_list_filters_by_tag_and_rejects_unknown_tags(client, db, tenant_and_user):
    t = tenant_and_user["tenant"]
    tid = t["id"] if isinstance(t, dict) else t.id
    h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="A", phone="+919800000042", lead_identified_at=datetime.now(UTC))
    db.add(g)
    db.flush()
    for tags in (["anniversary", "couple"], ["birthday"], []):
        db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, source=InquirySource.WA_DIRECT, tags=tags))
    db.commit()
    r = client.get("/api/v1/leads", params={"tag": "Anniversary", "page_size": 50}, headers=h)
    assert r.status_code == 200
    assert [lead["tags"] for lead in r.json()["leads"]] == [["anniversary", "couple"]]
    assert client.get("/api/v1/leads", params={"tag": "nope"}, headers=h).status_code == 422
    groups = client.get("/api/v1/leads/tags", headers=h).json()["groups"]
    assert any("anniversary" in grp["tags"] for grp in groups)
