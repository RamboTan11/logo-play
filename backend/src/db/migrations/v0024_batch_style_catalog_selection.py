"""Persist immutable batch style selections without changing historical requests."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0024_batch_style_catalog_selection"


def _upgrade(connection: Connection) -> None:
    inspector = inspect(connection)
    if not inspector.has_table("generation_requests"):
        return
    columns = {column["name"] for column in inspector.get_columns("generation_requests")}
    if "selected_style_ids_json" not in columns:
        connection.execute(
            text(
                "ALTER TABLE generation_requests ADD COLUMN selected_style_ids_json "
                "TEXT NOT NULL DEFAULT '[]'"
            )
        )
    if "style_allocation_json" not in columns:
        connection.execute(
            text(
                "ALTER TABLE generation_requests ADD COLUMN style_allocation_json "
                "TEXT NOT NULL DEFAULT '{}'"
            )
        )


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
