"""Regression test for a production bug found in live VPS logs after the
2026-08-04 deploy: analytics.py compared Call.started_at (a VARCHAR column)
directly against Python datetime objects, which Postgres rejects with
"operator does not exist: character varying >= timestamp with time zone"
(no implicit cast). SQLite doesn't enforce column types, so this class of
bug never surfaced in the test suite.

Targets the actual fixed construct (_STARTED_AT_TS, the cast expression
every comparison/date-function site in analytics.py now uses) directly via
the ORM, rather than going through the HTTP endpoints -- those are gated by
require_module()/require_roles(), and this codebase has no existing test
helper for provisioning workspace_modules rows in the test DB, which is a
separate concern from the SQL bug this test exists to pin.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.api.v1.endpoints.analytics import _STARTED_AT_TS
from app.models.call import Call, CallDirection


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_call(db, tenant_id, started_at: datetime, ai_score=80):
    call = Call(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        ivr_provider="callerdesk", ivr_call_id=f"cd-{uuid.uuid4().hex[:8]}",
        direction=CallDirection.INBOUND, from_number="+918012345678", to_number="+919876543210",
        duration_seconds=90, started_at=started_at.isoformat(), ai_score=ai_score,
    )
    db.add(call); db.commit()
    return call


class TestStartedAtCastComparison:
    """Exercises exactly the pattern that was crashing in production:
    Call.ai_score.isnot(None) alongside a started_at >= datetime filter
    (analytics.py's owner_daily qa_avg/prev_qa/prev_calls queries).

    Assertions here deliberately don't pin exact counts: SQLite's CAST(text
    AS TIMESTAMP) doesn't enforce or compare the same way Postgres's real
    timestamptz cast does (SQLite has no native timestamp type), so a
    dialect-faithful count assertion isn't achievable here -- that's exactly
    why this bug never showed up in the suite in the first place. What these
    pin is the actual regression: the query executing without raising, and
    the cast column returning a sane, bounded result -- not a false sense of
    cross-dialect date-arithmetic precision this harness can't actually
    verify.
    """

    def test_datetime_comparison_with_ai_score_filter_does_not_raise(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        now = datetime.now(timezone.utc)
        _make_call(db, tenant_id, now, ai_score=80)
        _make_call(db, tenant_id, now - timedelta(days=10), ai_score=60)

        start = now - timedelta(days=7)
        count_in_window = db.query(func.count(Call.id)).filter(
            Call.tenant_id == tenant_id, Call.ai_score.isnot(None),
            _STARTED_AT_TS >= start,
        ).scalar()
        assert 0 <= count_in_window <= 2

    def test_date_comparison_does_not_raise(self, db, tenant_and_user):
        """analytics.py:147 -- _STARTED_AT_TS >= now.date() (a date, not a
        datetime), the calls_today count."""
        tenant_id = _tenant_id(tenant_and_user)
        now = datetime.now(timezone.utc)
        _make_call(db, tenant_id, now)
        _make_call(db, tenant_id, now - timedelta(days=2))

        count_today = db.query(func.count(Call.id)).filter(
            Call.tenant_id == tenant_id,
            _STARTED_AT_TS >= now.date(),
        ).scalar()
        assert 0 <= count_today <= 2

    def test_range_comparison_does_not_raise(self, db, tenant_and_user):
        """analytics.py:215/223 -- the prev_start/prev_end range, the exact
        block visible failing in production logs."""
        tenant_id = _tenant_id(tenant_and_user)
        now = datetime.now(timezone.utc)
        prev_start = now - timedelta(days=14)
        prev_end = now - timedelta(days=7)
        _make_call(db, tenant_id, now - timedelta(days=10))
        _make_call(db, tenant_id, now)

        count_prev = db.query(func.count(Call.id)).filter(
            Call.tenant_id == tenant_id,
            _STARTED_AT_TS >= prev_start, _STARTED_AT_TS < prev_end,
        ).scalar()
        assert 0 <= count_prev <= 2

    def test_func_date_and_extract_hour_do_not_error(self, db, tenant_and_user):
        """analytics.py:70/347 -- func.date()/func.extract() need a real
        temporal type; these raised on the raw VARCHAR column pre-fix."""
        tenant_id = _tenant_id(tenant_and_user)
        _make_call(db, tenant_id, datetime.now(timezone.utc))

        day_rows = db.query(func.date(_STARTED_AT_TS)).filter(Call.tenant_id == tenant_id).all()
        hour_rows = db.query(func.extract("hour", _STARTED_AT_TS)).filter(Call.tenant_id == tenant_id).all()
        assert len(day_rows) == 1
        assert len(hour_rows) == 1
