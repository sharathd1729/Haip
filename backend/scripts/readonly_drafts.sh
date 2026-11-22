# Read-only: which AI drafts / concierge_* model calls landed on read-only sources (personal WhatsApp, lead forms).
# Run on the VPS from anywhere: bash /opt/haip/backend/scripts/readonly_drafts.sh  (one READ ONLY transaction, counts only).
cd /opt/haip && docker compose -f docker-compose.prod.yml exec -T api python - <<'EOF'
# READ-ONLY: one read-only transaction, SELECTs only, prints counts (no guest names, phones or message text).
from sqlalchemy import text
from app.core.database import SessionLocal

db = SessionLocal()
db.execute(text("SET TRANSACTION READ ONLY"))

def show(title, sql):
    print(f"\n== {title}")
    rows = db.execute(text(sql)).fetchall()
    for r in rows:
        print("  " + " | ".join("" if v is None else str(v) for v in r))
    if not rows:
        print("  (none)")

show("1. Threads with a pending AI draft (conversations.ai_draft), by workspace / channel / source", """
    SELECT t.slug, c.channel::text, COALESCE(c.source, 'official') AS source, count(*)
      FROM conversations c JOIN tenants t ON t.id = c.tenant_id
     WHERE c.ai_draft IS NOT NULL
     GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""")

show("2. AI-written messages on read-only threads (all time)", """
    SELECT t.slug, c.channel::text, c.source, count(*), min(m.created_at)::date, max(m.created_at)::date
      FROM messages m JOIN conversations c ON c.id = m.conversation_id JOIN tenants t ON t.id = m.tenant_id
     WHERE c.source IN ('personal_bridge', 'lead_form', 'chat_export') AND m.is_ai_generated
     GROUP BY 1, 2, 3 ORDER BY 1""")

show("3. concierge_* model calls, last 14 days: workspace | thread channel | thread source | answered message came from | path | task | calls | USD", """
    SELECT t.slug,
           COALESCE(c.channel::text, '-') AS channel,
           COALESCE(c.source, CASE WHEN c.id IS NULL THEN '-' ELSE 'official' END) AS conv_source,
           CASE WHEN u.ref_type = 'message' AND m.id IS NULL THEN '-'
                WHEN m.id IS NULL THEN '-'
                ELSE COALESCE(m.channel_metadata::jsonb ->> 'source', 'official') END AS msg_source,
           CASE WHEN u.ref_type = 'message' AND m.id IS NULL THEN 'write-a-draft button (no such message)'
                WHEN u.ref_type = 'message' THEN 'automatic (webhook / reply recovery / automation)'
                ELSE COALESCE(u.ref_type, '-') END AS path,
           u.meta::jsonb ->> 'task' AS task, count(*),
           round(sum(COALESCE((u.meta::jsonb ->> 'cost_usd')::numeric, 0)), 2)
      FROM usage_events u
      JOIN tenants t ON t.id = u.tenant_id
      LEFT JOIN messages m ON u.ref_type = 'message' AND m.id = u.ref_id
      LEFT JOIN conversations c ON c.id = m.conversation_id
     WHERE u.kind = 'llm_call' AND u.meta::jsonb ->> 'task' LIKE 'concierge%'
       AND u.created_at > now() - interval '14 days'
     GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY 1, 7 DESC""")

show("4. Of those, calls answering a read-only thread or message (the ones that should not exist)", """
    SELECT t.slug, c.channel::text, COALESCE(c.source, 'official'), COALESCE(m.channel_metadata::jsonb ->> 'source', 'official'),
           count(*), min(u.created_at), max(u.created_at)
      FROM usage_events u
      JOIN tenants t ON t.id = u.tenant_id
      JOIN messages m ON u.ref_type = 'message' AND m.id = u.ref_id
      JOIN conversations c ON c.id = m.conversation_id
     WHERE u.kind = 'llm_call' AND u.meta::jsonb ->> 'task' LIKE 'concierge%'
       AND u.created_at > now() - interval '14 days'
       AND (c.source IN ('personal_bridge', 'lead_form', 'chat_export')
            OR m.channel_metadata::jsonb ->> 'source' IN ('personal_bridge', 'lead_form', 'chat_export')
            OR c.channel::text NOT IN ('WHATSAPP', 'INSTAGRAM', 'whatsapp', 'instagram'))
     GROUP BY 1, 2, 3, 4 ORDER BY 1""")

show("5. Instagram drafts on COMMENTS vs DMs, last 14 days (calls)", """
    SELECT t.slug, COALESCE(m.channel_metadata::jsonb ->> 'source', 'dm') AS kind, count(*),
           round(sum(COALESCE((u.meta::jsonb ->> 'cost_usd')::numeric, 0)), 2)
      FROM usage_events u
      JOIN tenants t ON t.id = u.tenant_id
      JOIN messages m ON u.ref_type = 'message' AND m.id = u.ref_id
      JOIN conversations c ON c.id = m.conversation_id
     WHERE u.kind = 'llm_call' AND u.meta::jsonb ->> 'task' LIKE 'concierge%'
       AND u.created_at > now() - interval '14 days' AND c.channel::text IN ('INSTAGRAM', 'instagram')
     GROUP BY 1, 2 ORDER BY 1, 3 DESC""")

db.rollback()
db.close()
EOF
