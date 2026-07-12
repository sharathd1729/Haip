from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.config import settings
from app.core.database import Base
import app.models  # noqa — registers all models with Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import text as _text

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # Some PgBouncer session-pooler setups (e.g. Supabase's pooled
        # connection) can hand back a connection left in an aborted
        # transaction state by a prior session. Force a clean slate before
        # doing anything else, regardless of what state we inherited.
        try:
            connection.rollback()
        except Exception as _e:
            print(f"[env.py DEBUG] initial rollback failed: {_e!r}", flush=True)

        # ── Kill stale connections (best-effort — some managed Postgres
        # providers deny permission, e.g. Neon's neondb_owner, or Supabase's
        # pooled connections). A failed statement here leaves the Postgres
        # transaction itself aborted even though the Python exception is
        # caught — every later statement would fail with "current
        # transaction is aborted" unless we explicitly roll back first.
        try:
            connection.execute(_text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE pid != pg_backend_pid() AND datname = current_database()"
            ))
        except Exception as _e:
            print(f"[env.py DEBUG] pg_terminate_backend failed: {_e!r}", flush=True)
            connection.rollback()

        # Fail fast: never wait more than 10s for a lock or 60s per statement.
        try:
            connection.execute(_text("SET lock_timeout = '10s'"))
            connection.execute(_text("SET statement_timeout = '60s'"))
        except Exception as _e:
            print(f"[env.py DEBUG] SET lock_timeout/statement_timeout failed: {_e!r}", flush=True)
            connection.rollback()

        # Even when the SET calls above succeed, SQLAlchemy 2.x auto-begins
        # an implicit transaction on that connection's first execute() and
        # never closes it on its own. If we hand this connection to Alembic
        # while a transaction is still open, context.begin_transaction()
        # below layers on top of it instead of starting cleanly — and the
        # whole migration silently fails to commit even though every step
        # logs as if it succeeded (confirmed by reproducing this exact
        # symptom live: `alembic current` stayed put after a run that logged
        # "Running upgrade ... (head)"). Close it out before handing off.
        if connection.in_transaction():
            connection.rollback()

        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
