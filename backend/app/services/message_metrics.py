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
        text(
            f"""
            SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY gap_seconds)
            FROM (
                SELECT EXTRACT(EPOCH FROM (
                    (SELECT MIN(o.created_at) FROM messages o
                     WHERE o.conversation_id = m.conversation_id
                       AND o.direction = 'OUTBOUND'
                       AND o.created_at > m.created_at)
                    - m.created_at
                )) AS gap_seconds
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.tenant_id = :tid
                  AND m.direction = 'INBOUND'
                  AND m.created_at >= :since
                  {until_clause}
                  {property_clause}
                  AND c.channel IN ('WHATSAPP', 'INSTAGRAM')
            ) sub
            WHERE gap_seconds IS NOT NULL
            """
        ),
        params,
    ).scalar()
    return float(result) if result is not None else 0.0
