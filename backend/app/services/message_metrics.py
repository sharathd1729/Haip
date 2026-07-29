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
