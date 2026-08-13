"""Add reversible model-connection retirement without changing historical snapshots."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0022_model_connection_retirement"


def _upgrade(connection: Connection) -> None:
    inspector = inspect(connection)
    if not inspector.has_table("model_connections"):
        return
    columns = {column["name"] for column in inspector.get_columns("model_connections")}
    if "retired_at" not in columns:
        connection.execute(text("ALTER TABLE model_connections ADD COLUMN retired_at DATETIME"))
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_model_connections_retired_at "
                "ON model_connections (retired_at)"
            )
        )


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
