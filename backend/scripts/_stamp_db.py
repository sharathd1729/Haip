"""Force-stamp the alembic version to 021 so upgrade can proceed from there."""
from app.core.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    conn.execute(text("UPDATE alembic_version SET version_num = '021'"))
    conn.commit()
    result = conn.execute(text("SELECT version_num FROM alembic_version"))
    for row in result:
        print("Version now:", row[0])
