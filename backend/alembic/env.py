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
        # ── Kill stale connections (best-effort — Neon may deny permission) ───
        try:
            connection.execute(_text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE pid != pg_backend_pid() AND datname = current_database()"
            ))
        except Exception:
            pass  # neondb_owner lacks pg_signal_backend — skip silently

        # Fail fast: never wait more than 10s for a lock or 60s per statement.
        try:
            connection.execute(_text("SET lock_timeout = '10s'"))
            connection.execute(_text("SET statement_timeout = '60s'"))
        except Exception:
            pass  # Some managed Postgres flavours don't allow SET — skip

        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
