"""Add secure connection secrets and model connection runtime metadata."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection
from src.db.models import ModelConnectionSecret

VERSION = "0002_model_connection_secrets"


def _upgrade(connection: Connection) -> None:
    inspector = inspect(connection)
    existing = {column["name"] for column in inspector.get_columns("model_connections")}
    additions = {
        "verified_capabilities_json": "TEXT NOT NULL DEFAULT '[]'",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(text(f"ALTER TABLE model_connections ADD COLUMN {name} {definition}"))
    ModelConnectionSecret.__table__.create(connection, checkfirst=True)


async def upgrade(connection: AsyncConnection) -> None:
    """Apply the additive T-010 schema change without touching existing rows."""

    await connection.run_sync(_upgrade)
