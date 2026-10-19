"""
Shared chat-channel (WhatsApp/Instagram) message metrics -- factored out
so both the dashboard summary (GET /dashboard) and the "response_time"
adaptive widget (widget_service.py) compute the same real number instead
of the widget silently falling back to call-duration p95 (which reads 0
for any tenant with no calls connected yet, misleadingly implying
"instant chat response" rather than "no calls to measure").
"""
from datetime import datetime
from typing import List, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session


def chat_response_p95_seconds(
    db: Session,
    tenant_id: str,
    since: datetime,
    until: Optional[datetime] = None,
    property_ids: Optional[List[str]] = None,
) -> float:
    """
    p95 first-response time (seconds) across WhatsApp/Instagram messages --
    for each inbound message, the gap until the next outbound message in
    the same conversation. Computed via a correlated subquery in Postgres;
    unlike call-duration p95 (which needs a window function specifically
    because Call volume is large), Ratha-scale message volume makes this
    fine as a plain correlated subquery.

    `until`/`property_ids` are optional and default to no-op (matches the
    original signature) -- added so callers needing a bounded window (e.g.
    a previous-period delta) or a property filter, like the owner-daily
    KPI endpoint, can reuse this instead of computing a different metric
    (call-duration p95) under the same "response time" label.

    Message.direction / Conversation.channel are SAEnum columns without
    values_callable, so Postgres stores the Python enum MEMBER NAMES
    ("INBOUND", "WHATSAPP", ...), not their lowercase .value strings --
    this raw SQL matches that stored representation exactly.
    """
    until_clause = "AND m.created_at < :until" if until is not None else ""
    property_clause = (
        "AND c.property_id = ANY(:property_ids)" if property_ids else ""
    )
    params = {"tid": tenant_id, "since": since}
    if until is not None:
        params["until"] = until
    if property_ids:
        params["property_ids"] = property_ids

    result = db.execute(
        text(_response_gap_sql("percentile_cont(0.95) WITHIN GROUP (ORDER BY gap_seconds)",
                               until_clause, property_clause)),
        params,
    ).scalar()
    return float(result) if result is not None else 0.0


def chat_response_avg_seconds(
    db: Session,
    tenant_id: str,
    since: datetime,
    until: Optional[datetime] = None,
    property_ids: Optional[List[str]] = None,
) -> float:
    """
    MEAN first-response time (seconds), same population as
    chat_response_p95_seconds. This is the number to surface as a headline
    "avg response time" -- p95 is a near-worst-case and, over any window
    containing overnight messages, lands in the many-hours range (a real
    tenant read 851m/14h), which tells an owner nothing about how their
    team is actually doing.
    """
    until_clause = "AND m.created_at < :until" if until is not None else ""
    property_clause = "AND c.property_id = ANY(:property_ids)" if property_ids else ""
    params = {"tid": tenant_id, "since": since}
    if until is not None:
        params["until"] = until
    if property_ids:
        params["property_ids"] = property_ids

    result = db.execute(
        text(_response_gap_sql("AVG(gap_seconds)", until_clause, property_clause)),
        params,
    ).scalar()
    return float(result) if result is not None else 0.0


def chat_response_by_agent(
    db: Session,
    tenant_id: str,
    since: datetime,
    until: Optional[datetime] = None,
    property_ids: Optional[List[str]] = None,
) -> List[dict]:
    """
    Same population as chat_response_p95_seconds/avg_seconds, but grouped by
    the agent who sent the matching outbound reply -- Phase 2.5 agent-
    accountability instrumentation (HAIP_Agent_Analytics_Dashboard_Plan_1.md).

    The tenant-wide functions above use a correlated scalar subquery that
    only pulls MIN(created_at) of the next outbound message -- it never
    identifies WHICH message that was, so there's no sender_id to group by.
    This uses a LATERAL join instead so we get the actual matched outbound
    row (timestamp AND sender_id together), not just its timestamp.
    """
    until_clause = "AND m.created_at < :until" if until is not None else ""
    property_clause = "AND c.property_id = ANY(:property_ids)" if property_ids else ""
    params = {"tid": tenant_id, "since": since}
    if until is not None:
        params["until"] = until
    if property_ids:
        params["property_ids"] = property_ids

    rows = db.execute(
        text(f"""
            SELECT
                agent_id,
                AVG(gap_seconds) AS avg_seconds,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY gap_seconds) AS p95_seconds,
                COUNT(*) AS response_count
            FROM (
                SELECT
                    nxt.agent_id,
                    EXTRACT(EPOCH FROM (nxt.next_outbound_at - turns.created_at)) AS gap_seconds
                FROM (
                    SELECT
                        m.id,
                        m.conversation_id,
                        m.created_at,
                        m.direction,
                        LAG(m.direction) OVER (
                            PARTITION BY m.conversation_id ORDER BY m.created_at
                        ) AS prev_direction
                    FROM messages m
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE m.tenant_id = :tid
                      AND m.created_at >= :since
                      {until_clause}
                      {property_clause}
                      AND c.channel IN ('WHATSAPP', 'INSTAGRAM')
                ) turns
                CROSS JOIN LATERAL (
                    SELECT o.created_at AS next_outbound_at, o.sender_id AS agent_id
                    FROM messages o
                    WHERE o.conversation_id = turns.conversation_id
                      AND o.direction = 'OUTBOUND'
                      AND o.created_at > turns.created_at
                    ORDER BY o.created_at ASC
                    LIMIT 1
                ) nxt
                WHERE turns.direction = 'INBOUND'
                  AND turns.prev_direction IS DISTINCT FROM 'INBOUND'
                  AND nxt.next_outbound_at IS NOT NULL
                  AND nxt.agent_id IS NOT NULL
            ) sub
            GROUP BY agent_id
            ORDER BY response_count DESC
        """),
        params,
    ).mappings().all()

    return [
        {
            "agent_id": row["agent_id"],
            "avg_seconds": float(row["avg_seconds"]) if row["avg_seconds"] is not None else 0.0,
            "p95_seconds": float(row["p95_seconds"]) if row["p95_seconds"] is not None else 0.0,
            "response_count": row["response_count"],
        }
        for row in rows
    ]


def _response_gap_sql(aggregate: str, until_clause: str, property_clause: str) -> str:
    """
    Shared response-gap query, parameterised by aggregate.

    Counts one gap per guest TURN, not per inbound message. The previous
    version measured every inbound row, so a guest sending three messages
    in a row produced three gaps -- the first carrying the entire wait --
    which inflated every aggregate built on it and contradicted this
    module's own "first-response time" docstring. A turn starts at an
    inbound message whose immediately preceding message in the conversation
    was outbound (or which is the conversation's first message); LAG gives
    us that directly.
    """
    return f"""
        SELECT {aggregate}
        FROM (
            SELECT EXTRACT(EPOCH FROM (next_outbound_at - created_at)) AS gap_seconds
            FROM (
                SELECT
                    m.created_at,
                    m.direction,
                    LAG(m.direction) OVER (
                        PARTITION BY m.conversation_id ORDER BY m.created_at
                    ) AS prev_direction,
                    (SELECT MIN(o.created_at) FROM messages o
                     WHERE o.conversation_id = m.conversation_id
                       AND o.direction = 'OUTBOUND'
                       AND o.created_at > m.created_at) AS next_outbound_at
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.tenant_id = :tid
                  AND m.created_at >= :since
                  {until_clause}
                  {property_clause}
                  AND c.channel IN ('WHATSAPP', 'INSTAGRAM')
            ) turns
            WHERE direction = 'INBOUND'
              AND prev_direction IS DISTINCT FROM 'INBOUND'
              AND next_outbound_at IS NOT NULL
        ) sub
        WHERE gap_seconds IS NOT NULL
    """


# The chat a guest wrote on. Personal = the read-only personal WhatsApp bridge, judged on the conversation
# (Conversation.source) OR on the message itself, because a bridged message can land in a known lead's open Cloud
# thread (one open WhatsApp conversation per guest). Same keys as impact_metrics.CHANNELS.
RESPONSE_SOURCES = ("personal_whatsapp", "whatsapp_cloud", "instagram")

_SOURCE_SQL = """
    CASE
        WHEN c.channel = 'INSTAGRAM' THEN 'instagram'
        WHEN c.source = 'personal_bridge' OR m.channel_metadata->>'source' = 'personal_bridge' THEN 'personal_whatsapp'
        ELSE 'whatsapp_cloud'
    END
"""


def chat_response_by_agent_source(
    db: Session,
    tenant_id: str,
    since: datetime,
    until: Optional[datetime] = None,
    property_ids: Optional[List[str]] = None,
    include_history: bool = False,
) -> dict:
    """
    chat_response_by_agent split by SOURCE (where the guest wrote: personal
    WhatsApp bridge, the official Cloud WhatsApp number, Instagram), plus the
    per-source and overall totals, from one GROUPING SETS query.

    Same turn rule and the same "human reply" rule (the matched outbound row
    has a sender_id) as chat_response_by_agent, with two exclusions that only
    ever hit the personal bridge:
      * group chats (message channel_metadata.chat_type = 'group') are not
        guest turns and their messages are not replies;
      * messages mirrored from the phone's history sync (channel_metadata.
        history = true: text only, at most 200 per chat, so gaps are not
        reliable) are skipped, unless ``include_history`` -- the "Since HAIP"
        card uses it on both of its windows, because that history is the only
        record of reply times from before go-live.

    Returns {"by_agent": [{agent_id, source, avg_seconds, p95_seconds,
    response_count}], "by_source": {source: {...} | None}, "all": {...} | None}.
    None means no answered turn (unknown), never 0 seconds.
    """
    until_clause = "AND m.created_at < :until" if until is not None else ""
    property_clause = "AND c.property_id = ANY(:property_ids)" if property_ids else ""
    history_clause = "" if include_history else "AND COALESCE(m.channel_metadata->>'history', '') <> 'true'"
    reply_history_clause = "" if include_history else "AND COALESCE(o.channel_metadata->>'history', '') <> 'true'"
    params = {"tid": tenant_id, "since": since}
    if until is not None:
        params["until"] = until
    if property_ids:
        params["property_ids"] = property_ids

    rows = db.execute(
        text(f"""
            SELECT
                agent_id,
                source,
                GROUPING(agent_id) AS all_agents,
                GROUPING(source) AS all_sources,
                AVG(gap_seconds) AS avg_seconds,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY gap_seconds) AS p95_seconds,
                COUNT(*) AS response_count
            FROM (
                SELECT
                    nxt.agent_id,
                    turns.source,
                    EXTRACT(EPOCH FROM (nxt.next_outbound_at - turns.created_at)) AS gap_seconds
                FROM (
                    SELECT
                        m.id,
                        m.conversation_id,
                        m.created_at,
                        m.direction,
                        {_SOURCE_SQL} AS source,
                        LAG(m.direction) OVER (
                            PARTITION BY m.conversation_id ORDER BY m.created_at
                        ) AS prev_direction
                    FROM messages m
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE m.tenant_id = :tid
                      AND c.tenant_id = :tid
                      AND m.created_at >= :since
                      {until_clause}
                      {property_clause}
                      AND c.channel IN ('WHATSAPP', 'INSTAGRAM')
                      AND COALESCE(m.channel_metadata->>'chat_type', '') <> 'group'
                      {history_clause}
                ) turns
                CROSS JOIN LATERAL (
                    SELECT o.created_at AS next_outbound_at, o.sender_id AS agent_id
                    FROM messages o
                    WHERE o.conversation_id = turns.conversation_id
                      AND o.tenant_id = :tid
                      AND o.direction = 'OUTBOUND'
                      AND o.created_at > turns.created_at
                      AND COALESCE(o.channel_metadata->>'chat_type', '') <> 'group'
                      {reply_history_clause}
                    ORDER BY o.created_at ASC
                    LIMIT 1
                ) nxt
                WHERE turns.direction = 'INBOUND'
                  AND turns.prev_direction IS DISTINCT FROM 'INBOUND'
                  AND nxt.next_outbound_at IS NOT NULL
                  AND nxt.agent_id IS NOT NULL
            ) sub
            GROUP BY GROUPING SETS ((agent_id, source), (source), ())
        """),
        params,
    ).mappings().all()

    def _figures(row) -> dict:
        return {
            "avg_seconds": float(row["avg_seconds"]) if row["avg_seconds"] is not None else None,
            "p95_seconds": float(row["p95_seconds"]) if row["p95_seconds"] is not None else None,
            "response_count": int(row["response_count"]),
        }

    by_agent, by_source, overall = [], {s: None for s in RESPONSE_SOURCES}, None
    for row in rows:
        if not row["response_count"]:
            continue                  # the () grouping set returns one empty row when nothing was answered
        if row["all_sources"]:
            overall = _figures(row)
        elif row["all_agents"]:
            by_source[row["source"]] = _figures(row)
        else:
            by_agent.append({"agent_id": row["agent_id"], "source": row["source"], **_figures(row)})
    by_agent.sort(key=lambda r: -r["response_count"])
    return {"by_agent": by_agent, "by_source": by_source, "all": overall}
