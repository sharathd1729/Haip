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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # NOTE: this function previously ran two "best-effort" setup
        # statements here before the real migration transaction:
        #   1. pg_terminate_backend(...) — always denied on Neon's
        #      neondb_owner role (lacks pg_signal_backend).
        #   2. SET lock_timeout / SET statement_timeout — apparently also
        #      rejected on Supabase's session pooler in this project.
        # Both were wrapped in `except: pass`, which hid the failure — but a
        # failed statement on a Postgres connection poisons that connection's
        # transaction, so context.begin_transaction() below would silently
        # begin (and later commit) an already-aborted transaction: every
        # migration step logs as if it ran, but nothing is ever persisted and
        # alembic_version never advances. This was the actual cause of two
        # separate incidents (Neon stuck at 028, Supabase stuck at 033) where
        # `alembic upgrade head` reported full success with zero effect.
        # Removed both — neither is essential, and "fails loudly if broken"
        # beats "silently pretends to work" for a migration runner.

        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
