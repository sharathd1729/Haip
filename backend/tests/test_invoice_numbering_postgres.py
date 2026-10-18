"""Invoice numbers under concurrent issuers (PostgreSQL only).

next_number() advances invoice_sequences with one UPDATE ... RETURNING inside the issuing transaction. The row lock is
held until that transaction ends, so concurrent issuers queue and every committed number is unique and gap-free, and a
rolled-back issue hands its number back. SQLite has no concurrent writers, so this is skipped there; CI sets
REQUIRE_POSTGRES_TESTS=1, which turns a missing PostgreSQL into a failure.
"""
import os
import threading
import uuid

import pytest
from sqlalchemy import text

from app.services import invoice_service
from tests.conftest import TestingSessionLocal, engine

IS_POSTGRES = engine.dialect.name == "postgresql"
pytestmark = pytest.mark.skipif(
    not IS_POSTGRES and os.environ.get("REQUIRE_POSTGRES_TESTS") != "1",
    reason="needs PostgreSQL (row locks, concurrent connections). Runs in CI job tenant-isolation-postgres.",
)


def test_postgres_is_available_when_required():
    assert IS_POSTGRES, "REQUIRE_POSTGRES_TESTS=1 but DATABASE_URL is not a PostgreSQL URL"


def _cleanup(tenant_id):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM invoice_sequences WHERE tenant_id = :t"), {"t": tenant_id})


@pytest.mark.parametrize("writers", [8])
def test_concurrent_issuers_never_share_a_number(writers):
    tenant_id = str(uuid.uuid4())
    start = threading.Barrier(writers)
    taken, errors = [], []

    def worker(commit: bool):
        session = TestingSessionLocal()
        try:
            start.wait(timeout=15)
            for _ in range(5):
                number = invoice_service.next_number(session, tenant_id, "2026-27", "INV")
                if commit:
                    session.commit()
                    taken.append(number)
                else:
                    session.rollback()                   # an issue that failed gives its number back
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            errors.append(repr(exc))
        finally:
            session.close()

    try:
        threads = [threading.Thread(target=worker, args=(i % 4 != 3,)) for i in range(writers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert not errors, errors
        assert len(taken) == len(set(taken)), "two issuers got the same invoice number"
        expected = [f"INV/2026-27/{n:04d}" for n in range(1, len(taken) + 1)]
        assert sorted(taken) == expected, "numbers must be gap-free once rolled-back issues are handed back"
    finally:
        _cleanup(tenant_id)
