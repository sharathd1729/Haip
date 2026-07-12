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

    # ── Setup phase: run on its own autocommit connection, then discard it.
    # Doing this on the same connection Alembic later uses left that
    # connection sitting in an implicitly-autobegun transaction before
    # context.begin_transaction() ever ran, which meant the migrations'
    # eventual commit didn't reliably apply. Isolating setup here guarantees
    # Alembic gets a completely fresh connection with no pending transaction.
    with connectable.connect().execution_options(isolation_level="AUTOCOMMIT") as setup_conn:
        try:
            setup_conn.execute(_text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE pid != pg_backend_pid() AND datname = current_database()"
            ))
        except Exception as _e:
            print(f"[env.py DEBUG] pg_terminate_backend failed: {_e!r}", flush=True)

    with connectable.connect() as connection:
        connection.execute(_text("SET lock_timeout = '10s'"))
        connection.execute(_text("SET statement_timeout = '60s'"))
        connection.commit()  # closes the implicit autobegin transaction before Alembic starts its own

        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()
        print("[env.py DEBUG] migrations committed", flush=True)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
