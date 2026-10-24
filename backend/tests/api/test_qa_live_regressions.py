"""Two 5xx found by the local live smoke test: the dashboard agent leaderboard read a User column that does not exist,
and the Meta quality page 503'd on a fresh database because its inline table was only imported lazily."""
import uuid
from datetime import datetime, timezone

import pytest

from app.core.database import Base, engine
from app.models.call import Call, CallDirection
from app.models.module import Module, WorkspaceModule


def _auth(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


# The leaderboard filters on CAST(started_at AS TIMESTAMP); SQLite turns that cast into a number, so only PostgreSQL
# (production) can return the row.
@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="the started_at timestamp cast needs PostgreSQL")
def test_agent_leaderboard_names_the_agent(client, db, tenant_and_user):
    tu = tenant_and_user
    m = db.query(Module).filter_by(code="calls").first() or Module(id=str(uuid.uuid4()), code="calls", name="Calls")
    db.add(m); db.flush()
    db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=tu["tenant"].id, module_id=m.id, enabled=True))
    db.add(Call(id=str(uuid.uuid4()), tenant_id=tu["tenant"].id, ivr_provider="vobiz", ivr_call_id="lb-1",
                direction=CallDirection.INBOUND, from_number="+918012345678", to_number="+919876543210",
                agent_id=tu["user"].id, ai_score=80, duration_seconds=60,
                started_at=datetime.now(timezone.utc).isoformat()))
    db.commit()
    res = client.get("/api/v1/analytics/agent-leaderboard", headers=_auth(tu))
    assert res.status_code == 200, res.text
    assert res.json()["agents"][0]["name"] == "Test Owner"


def test_meta_quality_table_is_registered_at_app_import():
    import app.api.v1.endpoints.integrations  # noqa: F401
    assert "meta_quality_snapshots" in Base.metadata.tables


def test_meta_quality_endpoint_empty_is_200(client, tenant_and_user):
    res = client.get("/api/v1/integrations/meta/quality", headers=_auth(tenant_and_user))
    assert res.status_code == 200, res.text
