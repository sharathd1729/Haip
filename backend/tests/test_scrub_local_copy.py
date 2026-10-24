"""scripts/scrub_local_copy.py: refuses non-local databases, classifies columns, and really replaces PII (PostgreSQL)."""
import os
import sys
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import scrub_local_copy as scrub  # noqa: E402


@pytest.mark.parametrize("url", ["postgresql://u:p@db.supabase.co:5432/postgres", "postgresql://u:p@10.0.0.5/haip",
                                 "", "postgresql:///haip"])
def test_refuses_non_local_host(url):
    with pytest.raises(SystemExit, match="Refusing to scrub"):
        scrub.assert_local_target(url)


def test_accepts_localhost():
    scrub.assert_local_target("postgresql://haip:haip@127.0.0.1:55432/haip_prodcopy_raw")
    scrub.assert_local_target("postgresql://haip:haip@localhost/x")


def test_plan_classifies_columns():
    cols = {
        ("guests", "phone"): ("character varying", "varchar", False),
        ("messages", "body"): ("text", "text", True),
        ("guest_events", "preview"): ("text", "text", True),
        ("guest_events", "payload"): ("jsonb", "jsonb", False),
        ("integrations", "credentials_kms_blob"): ("bytea", "bytea", True),
        ("webhook_endpoints", "secret_enc"): ("bytea", "bytea", False),
        ("properties", "description"): ("text", "text", True),     # business content: kept
        ("inquiries", "source"): ("character varying", "varchar", True),  # analytics: kept
        ("inquiries", "lost_note"): ("text", "text", True),
        ("refresh_tokens", "token_hash"): ("character varying", "varchar", False),  # table is deleted instead
    }
    planned = {(t, c): e for t, c, e in scrub.plan(cols)}
    assert "fake_phone" in planned[("guests", "phone")]
    assert "scrub_text" in planned[("messages", "body")]
    assert "scrub_text" in planned[("guest_events", "preview")]
    assert "jsonb_typeof" in planned[("guest_events", "payload")]
    assert planned[("integrations", "credentials_kms_blob")] == "NULL"
    assert "random" in planned[("webhook_endpoints", "secret_enc")]
    assert "scrub_text" in planned[("inquiries", "lost_note")]
    for kept in [("properties", "description"), ("inquiries", "source"), ("refresh_tokens", "token_hash")]:
        assert kept not in planned


base_url = os.environ.get("DATABASE_URL", "")


@pytest.mark.skipif(not base_url.startswith("postgresql"), reason="needs PostgreSQL (runs with scripts/local/test.ps1)")
def test_scrub_replaces_pii_in_a_scratch_database():
    url = make_url(base_url)
    if (url.host or "") not in scrub.LOCAL_HOSTS:
        pytest.skip("scratch database is only created on a local PostgreSQL")
    name = f"scrub_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    target = url.set(database=name).render_as_string(hide_password=False)
    try:
        eng = create_engine(target)
        with eng.begin() as c:
            c.exec_driver_sql("""
                CREATE TABLE guests (id text primary key, name text, phone varchar(20) not null, email text);
                CREATE TABLE calls (id text primary key, from_number varchar(20) not null, transcript jsonb);
                CREATE TABLE messages (id text primary key, body text, direction text, created_at timestamptz);
                CREATE TABLE integrations (id text primary key, credentials_kms_blob bytea, config jsonb);
                CREATE TABLE properties (id text primary key, description text);
                CREATE TABLE refresh_tokens (id text primary key, token_hash text not null);
                CREATE TABLE users (id text primary key, tenant_id text, email text, hashed_password text,
                                    role text, is_mfa_enabled boolean, name text, created_at timestamptz);
                INSERT INTO guests VALUES ('g1', 'Priya Real', '+919876543210', 'priya.real@gmail.com');
                INSERT INTO calls VALUES ('c1', '919876543210', '[{"speaker":"guest","text":"I am Priya, call me on 9876543210","start":1}]');
                INSERT INTO messages VALUES ('m1', 'Hi, this is Priya, my number is 9876543210', 'inbound', now());
                INSERT INTO integrations VALUES ('i1', 'secret-bytes', '{"phone_number_id":"123","access_token":"EAAB"}');
                INSERT INTO properties VALUES ('p1', 'Our caravan sleeps four.');
                INSERT INTO refresh_tokens VALUES ('r1', 'abc');
                INSERT INTO users VALUES ('u1', 't1', 'owner@realbrand.in', 'x', 'owner', true, 'Real Owner', now());
            """)
        report = scrub.scrub(target, "local-pass-123")
        with eng.connect() as c:
            g = c.execute(text("SELECT name, phone, email FROM guests")).one()
            assert g.name != "Priya Real" and g.phone != "+919876543210" and g.email.endswith("@scrubbed.example")
            assert g.phone.startswith("+919") and len(g.phone) == 13
            call = c.execute(text("SELECT from_number, transcript FROM calls")).one()
            assert call.from_number == g.phone.lstrip("+")  # same person, same fake number
            assert call.transcript[0]["speaker"] == "guest" and "Priya" not in call.transcript[0]["text"]
            msg = c.execute(text("SELECT body, direction FROM messages")).one()
            assert msg.body.startswith("[scrubbed]") and len(msg.body) == len("Hi, this is Priya, my number is 9876543210")
            assert msg.direction == "inbound"
            integ = c.execute(text("SELECT credentials_kms_blob, config FROM integrations")).one()
            assert integ.credentials_kms_blob is None and integ.config == {"phone_number_id": "123"}
            assert c.execute(text("SELECT description FROM properties")).scalar() == "Our caravan sleeps four."
            assert c.execute(text("SELECT count(*) FROM refresh_tokens")).scalar() == 0
            u = c.execute(text("SELECT email, is_mfa_enabled, name FROM users")).one()
            assert u.email == "owner1@prodcopy.example" and u.is_mfa_enabled is False and u.name != "Real Owner"
        assert report["guests.phone"] == 1
        assert scrub.residual_scan(target) == []
        eng.dispose()
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
