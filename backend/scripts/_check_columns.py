"""Check which columns from migration 022 actually exist in the DB."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.core.database import engine
from sqlalchemy import text

checks = [
    ("tenants", "llm_provider_override"),
    ("transcripts", "script_type"),
    ("guests", "phone"),  # just verify it exists
]

with engine.connect() as conn:
    for table, col in checks:
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ), {"t": table, "c": col})
        exists = result.fetchone() is not None
        print(f"{table}.{col}: {'EXISTS' if exists else 'MISSING'}")

    # Check guests phone unique constraint
    r = conn.execute(text(
        "SELECT constraint_name FROM information_schema.table_constraints "
        "WHERE table_name='guests' AND constraint_type='UNIQUE'"
    ))
    print("guests UNIQUE constraints:", [row[0] for row in r])
