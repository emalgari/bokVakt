"""Alembic environment for Firmabok."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import config as appconfig
from app.db import Base
import app.models  # noqa: F401 — register all models on Base.metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Always use the app's configured database URL unless one was passed in.
if not config.get_main_option("sqlalchemy.url") or config.attributes.get("firmabok_use_app_url", True):
    config.set_main_option("sqlalchemy.url", appconfig.DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"},
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
