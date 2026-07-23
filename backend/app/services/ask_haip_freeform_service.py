"""
Ask HAIP — free-form analyst.

Answers ad-hoc questions that fall outside the 10 pre-built domain agents
(ask_haip_agents.py) by generating SQL from natural language, rather than
requiring every possible question to be hand-coded in advance.

SECURITY MODEL — three independent layers, because an LLM prompt is
advisory, not a boundary:
  1. Prompt constraints (this file)        — cheap, catches the common case
  2. SQL validator + AST rewrite (this file) — the real server-side boundary:
     single-table SELECT only, table must be in ALLOWED_TABLES, tenant_id
     predicate is force-injected via AST rewrite regardless of what the LLM
     wrote (never trusts the LLM's own WHERE clause for tenant scoping)
  3. haip_analyst_ro Postgres role (migration 052) — SELECT-only grants on
     the same table allowlist, 5s statement_timeout. Even if (1) and (2)
     both had bugs, this role cannot write and cannot read any table
     outside the grant list.

V1 limitation: single-table queries only (no JOINs). Multi-table questions
get a clear "try simplifying" response rather than a half-validated JOIN
query -- expand this once the single-table path has real production usage
to learn from.
"""
from __future__ import annotations

import json
import time
import structlog
from typing import Optional

import sqlglot
from sqlglot import exp
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.adapters.llm import get_llm
from app.models.ask_haip import AskHaipFreeformQuery
from app.models.base import gen_uuid

log = structlog.get_logger()

MAX_ROWS = 500
QUERY_TIMEOUT_S = 5

# Kept in sync manually with migration 052's ANALYST_READABLE_TABLES --
# this list is what the LLM is told exists; the DB role grants are the
# actual enforcement, but keeping these two lists identical means a
# validator bug still fails closed at the DB layer instead of silently
# returning "permission denied" as a confusing runtime error.
ALLOWED_TABLES: dict[str, str] = {
    "inquiries": "Leads360 pipeline entries. Columns include: id, tenant_id, guest_id, "
                 "stage_id, source, check_in, check_out, adults, children, budget, "
                 "quoted_amount, created_at, current_stage_entered_at, ai_summary.",
    "guests": "Guest profiles. Columns: id, tenant_id, name, phone, email, city, "
              "vip_tier, total_stays, total_inquiries, lifetime_value, created_at.",
    "calls": "Phone call records. Columns: id, tenant_id, guest_id, direction, "
             "duration_seconds, disposition, created_at.",
    "stays": "Confirmed bookings. Columns: id, tenant_id, guest_id, property_id, "
             "check_in, check_out, adults, children, status, total_amount, "
             "channel_source, created_at.",
    "conversations": "WhatsApp/Instagram conversation threads. Columns: id, tenant_id, "
                      "guest_id, channel, is_open, ai_mode, last_message_at, created_at.",
    "messages": "Individual chat messages. Columns: id, tenant_id, conversation_id, "
                "direction, channel, body, created_at.",
    "properties": "Bookable units (villas/caravans/rooms). Columns: id, tenant_id, "
                  "name, type, city, price_per_day, is_active.",
    "pipeline_stages": "Tenant's Leads360 stage taxonomy. Columns: id, tenant_id, key, "
                        "label, category, is_closed_won, is_closed_lost.",
}

SQL_SYSTEM_PROMPT = f"""You are a SQL generator for a hospitality CRM. Given a
question, write ONE read-only PostgreSQL SELECT statement that answers it.

Available tables (query ONE of these only -- no JOINs):
{chr(10).join(f"- {t}: {desc}" for t, desc in ALLOWED_TABLES.items())}

Rules:
- SELECT statements only. Never write INSERT/UPDATE/DELETE/DROP/ALTER/CREATE.
- Query exactly one table -- no JOINs, no subqueries against other tables.
- Never write a WHERE clause referencing tenant_id yourself -- it is added
  automatically after you respond. Do not mention tenant_id at all.
- Always include a LIMIT (max 500).
- Return ONLY the SQL statement, no markdown fences, no explanation.
"""

SUMMARY_SYSTEM_PROMPT = """You are a data analyst. Given a question and the
resulting rows (as JSON), respond with JSON:
{"narrative": "<2-3 sentence plain-English answer, cite real numbers>",
 "chart": {"type": "bar|line|pie|<empty string if not chartable>",
           "label": "<short chart title>",
           "series": [<subset of the rows suitable for plotting, or []>]}}
Return ONLY the JSON object."""


class FreeformRejected(Exception):
    """The generated SQL failed validation -- never reaches the DB."""


def _validate_and_scope(sql: str, tenant_id: str) -> str:
    """
    Parse the LLM's SQL, enforce the single-table+allowlist constraint, and
    force-inject the tenant_id predicate via AST rewrite. Raises
    FreeformRejected on any violation -- never falls back to executing an
    unvalidated query.
    """
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except Exception as exc:
        raise FreeformRejected(f"Could not parse generated SQL: {exc}")

    if not isinstance(tree, exp.Select):
        raise FreeformRejected("Only SELECT statements are allowed")

    # Reject any nested statement type sneaking in via a CTE/subquery
    for node in tree.walk():
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create)):
            raise FreeformRejected("Only SELECT statements are allowed")

    tables = list(tree.find_all(exp.Table))
    table_names = {t.name for t in tables}
    if len(table_names) != 1:
        raise FreeformRejected(
            "This version only supports single-table questions (no joins). "
            "Try asking about one thing at a time."
        )
    table_name = next(iter(table_names))
    if table_name not in ALLOWED_TABLES:
        raise FreeformRejected(f"Table '{table_name}' is not queryable by this feature")

    # Force-inject tenant scoping -- never trust the LLM's own WHERE clause
    # for this. Uses a bound parameter, not a string-interpolated tenant_id.
    tenant_pred = exp.condition("tenant_id = :tenant_id")
    existing_where = tree.args.get("where")
    if existing_where:
        tree.set("where", exp.Where(this=exp.and_(existing_where.this, tenant_pred)))
    else:
        tree.set("where", exp.Where(this=tenant_pred))

    # Force/cap LIMIT
    existing_limit = tree.args.get("limit")
    if not existing_limit:
        tree.set("limit", exp.Limit(expression=exp.Literal.number(MAX_ROWS)))
    else:
        try:
            n = int(existing_limit.expression.this)
            if n > MAX_ROWS:
                tree.set("limit", exp.Limit(expression=exp.Literal.number(MAX_ROWS)))
        except (ValueError, AttributeError):
            tree.set("limit", exp.Limit(expression=exp.Literal.number(MAX_ROWS)))

    return tree.sql(dialect="postgres")


_ro_engine = None


def _get_ro_engine():
    global _ro_engine
    if not settings.ANALYST_RO_DATABASE_URL:
        raise FreeformRejected(
            "The free-form analyst isn't configured yet -- ANALYST_RO_DATABASE_URL "
            "is not set (see migration 052's docstring for setup steps)."
        )
    if _ro_engine is None:
        _ro_engine = create_engine(
            settings.ANALYST_RO_DATABASE_URL,
            pool_size=3, max_overflow=2, pool_pre_ping=True,
        )
    return _ro_engine


async def answer_freeform_question(
    db: Session,
    tenant_id: str,
    user_id: str,
    question: str,
) -> dict:
    """
    Full pipeline: NL -> SQL -> validate/scope -> execute (read-only role,
    short timeout) -> summarize into narrative + chart. Every attempt is
    audited to ask_haip_freeform_queries, including rejections.
    """
    start = time.monotonic()
    audit = AskHaipFreeformQuery(
        id=gen_uuid(), tenant_id=tenant_id, user_id=user_id,
        question=question, status="error",
    )

    try:
        sql_llm = get_llm("ask_haip_freeform_sql")
        gen = await sql_llm.complete(
            system_prompt=SQL_SYSTEM_PROMPT, user_message=question, max_tokens=400,
        )
        raw_sql = gen.get("content", "").strip().strip("`").removeprefix("sql\n").strip()
        audit.generated_sql = raw_sql

        scoped_sql = _validate_and_scope(raw_sql, tenant_id)
        audit.generated_sql = scoped_sql

        engine = _get_ro_engine()
        with engine.connect() as conn:
            conn.execute(text(f"SET LOCAL statement_timeout = '{QUERY_TIMEOUT_S}s'"))
            result = conn.execute(text(scoped_sql), {"tenant_id": tenant_id})
            rows = [dict(r._mapping) for r in result.fetchall()]

        audit.row_count = len(rows)

        summary_llm = get_llm("ask_haip_freeform_summary")
        summary_resp = await summary_llm.complete(
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            user_message=json.dumps({"question": question, "rows": rows[:100]}, default=str),
            max_tokens=800,
        )
        content = summary_resp.get("content", "").strip()
        s, e = content.find("{"), content.rfind("}") + 1
        parsed = json.loads(content[s:e]) if s >= 0 and e > s else {"narrative": "", "chart": None}

        audit.status = "ok"
        audit.chart_spec = parsed.get("chart")
        return {
            "narrative": parsed.get("narrative", ""),
            "chart": parsed.get("chart") if parsed.get("chart", {}).get("type") else None,
            "rows": rows[:50],
            "row_count": len(rows),
            "sql": scoped_sql,
        }

    except FreeformRejected as exc:
        audit.status = "rejected"
        audit.reject_reason = str(exc)
        log.warning("ask_haip_freeform_rejected", tenant_id=tenant_id, reason=str(exc))
        return {"narrative": None, "error": str(exc), "chart": None, "rows": [], "row_count": 0, "sql": None}

    except Exception as exc:
        audit.status = "error"
        audit.reject_reason = str(exc)[:500]
        log.error("ask_haip_freeform_error", tenant_id=tenant_id, error=str(exc))
        return {
            "narrative": None,
            "error": "Something went wrong answering that question. Please try rephrasing it.",
            "chart": None, "rows": [], "row_count": 0, "sql": None,
        }

    finally:
        audit.duration_ms = int((time.monotonic() - start) * 1000)
        db.add(audit)
        db.commit()
