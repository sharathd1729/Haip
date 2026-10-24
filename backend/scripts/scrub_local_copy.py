"""Scrub every piece of personal data out of a LOCAL copy of the production database, in place, in one transaction.

Run by scripts/local/load_prod_scrubbed.ps1 right after the restore, before the app or anything else connects
(docs/LOCAL_TESTING.md). Refuses any database that is not on localhost.

What changes (structure, ids, timestamps, directions, stages, amounts, sources and counts are kept):
  * guest / staff / lead names -> made-up names; phones -> made-up valid Indian mobiles; emails -> @scrubbed.example.
    The same real value always becomes the same fake value within one run (salted per run, so it cannot be
    reversed by hashing every phone number), so a guest's calls, chats and identities still join up.
  * message bodies, transcripts, summaries, notes, previews -> "[scrubbed] lorem ipsum..." of the same length;
    free JSON (payloads, metadata, AI analyses) -> {} / [] / NULL.
  * credentials, tokens, encrypted blobs, webhook secrets -> NULL or random; sessions/tokens/push subscriptions deleted.
  * every user -> <role><n>@prodcopy.example with ONE new local password (printed once), MFA off.
Business content that is not personal data (properties, packages, knowledge base, templates, the brand's own posts)
is left as is. A final scan reports any phone number or email still found in a text column, for a human to check.

    python scripts/scrub_local_copy.py postgresql://haip:haip@127.0.0.1:55432/haip_prodcopy_raw
"""
import os
import re
import secrets
import sys
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

# Tables that hold the business's own configuration and content, not people: their free text is kept.
BUSINESS_TABLES = {
    "alembic_version", "tenants", "properties", "rooms", "rate_plans", "seasonal_rates", "property_addons",
    "blocked_dates", "pipeline_stages", "modules", "capabilities", "role_capabilities", "workspace_modules",
    "feature_flags", "knowledge_entries", "embeddings", "business_records", "saved_replies", "rubrics",
    "lead_field_definitions", "automation_rules", "wa_templates", "wa_flows", "wa_campaigns", "media_assets",
    "sites", "site_versions", "site_domains", "site_ai_jobs", "ad_entities", "ad_metrics", "instagram_insights_snapshots",
    "instagram_post_snapshots", "instagram_post_metrics_daily", "impact_baselines", "impact_profiles",
    "roi_benchmarks", "sales_targets", "saved_views", "ivr_options", "ivr_configs", "oauth_clients", "invoice_sequences",
    "marketing_ad_drafts", "marketing_approvals", "marketing_audits", "marketing_boost_rules", "marketing_content",
    "marketing_content_versions", "marketing_creative_jobs", "marketing_creative_tags", "marketing_image_jobs",
    "marketing_newsletters", "marketing_ota_copies", "marketing_plans", "marketing_publish_attempts",
    "marketing_research_briefs", "marketing_reviews", "marketing_signals", "marketing_strategy_docs",
    "marketing_swipe_items", "marketing_tasks", "marketing_competitors", "marketing_competitor_snapshots",
    "marketing_competitor_posts", "agent_experiments", "ical_feed_vehicles", "usage_events",
}
# Rows that are only credentials or sessions: deleted outright.
DELETE_TABLES = ["refresh_tokens", "personal_access_tokens", "oauth_grants", "guest_access_tokens", "api_keys",
                 "push_subscriptions", "whatsapp_personal_sessions", "user_invitations"]

PHONE = "pg_temp.fake_phone({c})"
EMAIL = "pg_temp.fake_email({c})"
NAME = "pg_temp.fake_name({c})"
TEXT = "pg_temp.scrub_text({c})"
HASH = "'scrubbed-' || substr(md5(pg_temp.salt() || {c}), 1, 16)"
# Explicit rules for identity columns (free text and secrets are also caught by the sweeps below).
RULES = [
    ("guests", "name", NAME), ("guests", "phone", PHONE), ("guests", "alt_phone", PHONE), ("guests", "email", EMAIL),
    ("guest_identities", "identity_value",
     "CASE WHEN identity_type IN ('phone','whatsapp_number') THEN pg_temp.fake_phone({c}) "
     "WHEN identity_type = 'email' THEN pg_temp.fake_email({c}) ELSE identity_type || ':' || "
     "substr(md5(pg_temp.salt() || {c}), 1, 16) END"),
    ("conversations", "channel_conversation_id", HASH),
    ("calls", "from_number", PHONE), ("calls", "to_number", PHONE), ("calls", "recording_url_ivr", "NULL"),
    ("calls", "recording_s3_key", "NULL"), ("calls", "transcript", "pg_temp.scrub_turns({c}::text)::jsonb"),
    ("transcripts", "turns", "pg_temp.scrub_turns({c})"), ("transcripts", "embedding", "NULL"),
    ("messages", "sender_name", NAME), ("messages", "media_url", "NULL"),
    ("users", "name", NAME), ("users", "phone", PHONE), ("users", "mfa_secret", "NULL"), ("users", "avatar_s3_key", "NULL"),
    ("users", "google_id", "NULL"), ("users", "microsoft_id", "NULL"),
    ("platform_leads", "name", NAME), ("platform_leads", "email", EMAIL), ("platform_leads", "phone", PHONE),
    ("platform_leads", "company", TEXT), ("platform_leads", "user_agent", "NULL"), ("platform_leads", "ip_hash", "NULL"),
    ("grievances", "name", NAME), ("grievances", "email", EMAIL), ("grievances", "phone", PHONE),
    ("wa_campaign_recipients", "name", NAME), ("wa_campaign_recipients", "phone", PHONE),
    ("wa_subscribers", "name", NAME), ("wa_subscribers", "phone", PHONE),
    ("marketing_newsletter_recipients", "email", EMAIL), ("marketing_guest_reviews", "reviewer", NAME),
    ("marketing_creators", "name", NAME), ("marketing_creators", "handle", HASH),
    ("consents", "proof_ip", "NULL"), ("consents", "proof_user_agent", "NULL"), ("consent_log", "ip_address", "NULL"),
    ("ivr_call_logs", "caller_phone_token", HASH), ("lead_evidence_imports", "filename", "'scrubbed'"),
    ("inquiries", "quote_pdf_url", "NULL"), ("inquiry_quotes", "pdf_url", "NULL"), ("booking_holds", "payment_url", "NULL"),
    ("stay_payment_links", "short_url", "'https://scrubbed.example/pay'"), ("lead_attribution", "raw_referral", "NULL"),
    ("tenants", "whatsapp_config", "pg_temp.strip_secrets({c}::jsonb)"),
    ("tenants", "ivr_config", "pg_temp.strip_secrets({c}::jsonb)"),
    ("tenants", "brand_config", "pg_temp.strip_secrets({c}::jsonb)"),
    ("integrations", "config", "pg_temp.strip_secrets({c}::jsonb)"), ("integrations", "credentials_kms_blob", "NULL"),
    ("ical_feeds", "export_token", "md5(random()::text)"), ("site_domains", "verify_token", "md5(random()::text)"),
]
FREE_TEXT = re.compile(r"(preview|body|text|message|note|notes|comment|summary|transcript|caption|content|reply|"
                       r"draft|answer|question|description|request|narrative|special_requests|address|"
                       r"next_action|lead_analysis|insight|signal|feedback|error)", re.I)
FREE_JSON = re.compile(r"(payload|context|metadata|raw|details|assessment|meta|result|summary|facts|actions|analysis|"
                       r"insights|preferences|custom_fields|hold_reasons|special_requests|answer|sql|rows|data)", re.I)
SECRET = re.compile(r"(_enc$|secret|password|^token$|_token$|token_hash|api_key|credential|kms_blob)", re.I)
KEEP = re.compile(r"(^id$|_id$|_at$|status|^kind$|type$|^source|channel|direction|stage|currency|role|mode|_key$|^key$|"
                  r"slug|category|version|language|intent|disposition|_sha$|_hash$|reason_code)", re.I)

FUNCTIONS = """
CREATE FUNCTION pg_temp.salt() RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT '{salt}'::text $$;
CREATE FUNCTION pg_temp.fake_phone(v text) RETURNS text LANGUAGE sql AS $$
  SELECT CASE WHEN v IS NULL OR regexp_replace(v, '\\D', '', 'g') = '' THEN v ELSE
    (CASE WHEN v LIKE '+%' THEN '+91' WHEN length(regexp_replace(v, '\\D', '', 'g')) > 10 THEN '91' ELSE '' END)
    || '9' || lpad((('x' || substr(md5(pg_temp.salt() || right(regexp_replace(v, '\\D', '', 'g'), 10)), 1, 8))::bit(32)::bigint
                    % 1000000000)::text, 9, '0') END $$;
CREATE FUNCTION pg_temp.fake_email(v text) RETURNS text LANGUAGE sql AS $$
  SELECT CASE WHEN v IS NULL OR v = '' THEN v ELSE
    'guest-' || substr(md5(pg_temp.salt() || lower(trim(v))), 1, 10) || '@scrubbed.example' END $$;
CREATE FUNCTION pg_temp.fake_name(v text) RETURNS text LANGUAGE sql AS $$
  SELECT CASE WHEN v IS NULL OR v = '' THEN v ELSE
    (ARRAY['Aarav','Diya','Kabir','Meera','Rohan','Anaya','Vihaan','Isha','Arjun','Tara','Neel','Zoya','Dev','Riya',
           'Kiran','Naina','Yash','Sara','Om','Leela'])[1 + ('x' || substr(md5(pg_temp.salt() || lower(v)), 1, 6))::bit(24)::int % 20]
    || ' ' ||
    (ARRAY['Rao','Iyer','Menon','Shah','Kapoor','Das','Gill','Bose','Nair','Joshi','Kulkarni','Pillai','Sethi','Varma',
           'Bhat','Chopra','Mehra','Sen','Reddy','Paul'])[1 + ('x' || substr(md5(lower(v) || pg_temp.salt()), 1, 6))::bit(24)::int % 20]
  END $$;
CREATE FUNCTION pg_temp.scrub_text(v text) RETURNS text LANGUAGE sql AS $$
  SELECT CASE WHEN v IS NULL OR v = '' THEN v ELSE rpad('[scrubbed] ', length(v), 'lorem ipsum dolor sit amet ') END $$;
CREATE FUNCTION pg_temp.scrub_turns(v text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE j jsonb;
BEGIN
  IF v IS NULL THEN RETURN NULL; END IF;
  j := v::jsonb;
  IF jsonb_typeof(j) <> 'array' THEN RETURN pg_temp.scrub_text(v); END IF;
  RETURN (SELECT coalesce(jsonb_agg(CASE WHEN jsonb_typeof(e) = 'object' AND e ? 'text'
            THEN jsonb_set(e, '{text}', to_jsonb(pg_temp.scrub_text(e->>'text'))) ELSE '{}'::jsonb END), '[]'::jsonb)
          FROM jsonb_array_elements(j) e)::text;
EXCEPTION WHEN others THEN RETURN pg_temp.scrub_text(v);
END $$;
CREATE FUNCTION pg_temp.strip_secrets(v jsonb) RETURNS jsonb LANGUAGE sql AS $$
  SELECT CASE WHEN v IS NULL OR jsonb_typeof(v) <> 'object' THEN v ELSE
    (SELECT coalesce(jsonb_object_agg(k, x), '{}'::jsonb) FROM jsonb_each(v) AS t(k, x)
     WHERE k !~* '(token|secret|key|password|credential|webhook)') END $$;
"""


def assert_local_target(database_url: str) -> None:
    host = (urlparse(database_url or "").hostname or "").lower()
    if host not in LOCAL_HOSTS:
        raise SystemExit(f"Refusing to scrub: database host {host or '(none)'!r} is not localhost.")


def _columns(conn):
    from sqlalchemy import text
    rows = conn.execute(text(
        "SELECT c.table_name, c.column_name, c.data_type, c.udt_name, c.is_nullable = 'YES' FROM information_schema.columns c "
        "JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
        "WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'")).all()
    cols = {}
    for table, col, dtype, udt, nullable in rows:
        cols[(table, col)] = (dtype, udt, nullable)
    return cols


def _empty_for(dtype: str, nullable: bool, c: str) -> str:
    if nullable:
        return "NULL"
    if dtype in ("json", "jsonb"):
        return f"CASE {dtype}_typeof({c}) WHEN 'array' THEN '[]'::{dtype} ELSE '{{}}'::{dtype} END"
    if dtype == "bytea":
        return "decode(md5(random()::text), 'hex')"
    return "md5(random()::text)"


def plan(cols) -> list[tuple[str, str, str]]:
    """(table, column, SQL expression) for every column that will be rewritten. Pure; tested."""
    out, done = [], set()
    for table, col, expr in RULES:
        if (table, col) in cols:
            out.append((table, col, expr.format(c=f'"{col}"')))
            done.add((table, col))
    for (table, col), (dtype, udt, nullable) in sorted(cols.items()):
        if (table, col) in done or table in DELETE_TABLES:
            continue
        c = f'"{col}"'
        if SECRET.search(col) and not col.endswith("_at"):
            out.append((table, col, _empty_for(dtype, nullable, c)))
        elif table in BUSINESS_TABLES or KEEP.search(col):
            continue
        elif dtype in ("text", "character varying") and FREE_TEXT.search(col):
            out.append((table, col, f"pg_temp.scrub_text({c})"))
        elif dtype in ("json", "jsonb") and FREE_JSON.search(col):
            out.append((table, col, _empty_for(dtype, nullable, c)))
    return out


def scrub(database_url: str, password: str) -> dict:
    from sqlalchemy import create_engine, text
    from passlib.context import CryptContext  # same scheme as app.core.security, without importing app settings
    report = {}
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text("SET session_replication_role = replica"))  # no triggers/FK checks while rewriting
        # Raw DBAPI cursor, same transaction: the SQL has literal % signs that driver-level formatting would choke on.
        conn.connection.cursor().execute(FUNCTIONS.replace("{salt}", secrets.token_hex(16)))
        cols = _columns(conn)
        tables = {t for t, _ in cols}
        for table in DELETE_TABLES:
            if table in tables:
                report[f"{table} (rows deleted)"] = conn.execute(text(f'DELETE FROM "{table}"')).rowcount
        for table, col, expr in plan(cols):
            n = conn.execute(text(f'UPDATE "{table}" SET "{col}" = {expr} WHERE "{col}" IS NOT NULL')).rowcount
            if n:
                report[f"{table}.{col}"] = n
        if "users" in tables:
            pw_hash = CryptContext(schemes=["bcrypt"], deprecated="auto").hash(password)
            users = conn.execute(text("SELECT id, lower(role::text) FROM users ORDER BY tenant_id, created_at")).all()
            for n, (uid, role) in enumerate(users, 1):
                conn.execute(text("UPDATE users SET email = :e, hashed_password = :p, is_mfa_enabled = false WHERE id = :i"),
                             {"e": f"{role}{n}@prodcopy.example", "p": pw_hash, "i": uid})
            report["users (local email + password)"] = len(users)
        conn.execute(text("SET session_replication_role = origin"))
    return report


def residual_scan(database_url: str) -> list[tuple[str, int]]:
    """Text columns that still contain something shaped like a phone number or an email address (counts only)."""
    from sqlalchemy import create_engine, text
    pattern = r"(\+?91[ -]?)?[6-9][0-9]{4}[ -]?[0-9]{5}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    fake = {(t, c) for t, c, _ in RULES}
    found = []
    engine = create_engine(database_url)
    with engine.connect() as conn:
        for (table, col), (dtype, _, _) in sorted(_columns(conn).items()):
            if (dtype not in ("text", "character varying", "json", "jsonb") or (table, col) in fake or table == "users"
                    or re.search(r"(^id$|_id$|hash|sha)", col)):  # numeric ids and hashes look like phone numbers
                continue
            n = conn.execute(text(
                f'SELECT count(*) FROM "{table}" WHERE "{col}"::text ~ :p '
                f"AND \"{col}\"::text !~ '@([a-z0-9-]+[.])*example([^a-z]|$)'"), {"p": pattern}).scalar()
            if n:
                found.append((f"{table}.{col}", n))
    return found


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DATABASE_URL", "")
    assert_local_target(url)
    password = os.environ.get("LOCAL_PASSWORD") or secrets.token_urlsafe(9)
    report = scrub(url, password)
    print("\nScrubbed (column: rows changed)")
    for key, n in sorted(report.items()):
        print(f"  {key}: {n}")
    leftovers = residual_scan(url)
    print("\nStill shaped like a phone/email (business content such as the brand's own number is expected here;"
          " anything about a guest is a gap to fix in scrub_local_copy.py):")
    for key, n in leftovers or [("(none)", 0)]:
        print(f"  {key}: {n}")
    print("\nEvery user now signs in as <role><n>@prodcopy.example, e.g. owner1@prodcopy.example")
    print(f"Local password for all users (shown once): {password}")


if __name__ == "__main__":
    main()
