"""Add the immutable delivery-image reference to customer design tasks."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0010_task_delivery_image"


def _upgrade(connection: Connection) -> None:
    """Append the nullable delivery asset reference without changing existing tasks."""

    inspector = inspect(connection)
    if not inspector.has_table("design_tasks"):
        return
    existing = {column["name"] for column in inspector.get_columns("design_tasks")}
    if "delivery_asset_id" not in existing:
        connection.execute(
            text(
                "ALTER TABLE design_tasks ADD COLUMN delivery_asset_id "
                "VARCHAR(64) REFERENCES asset_records(asset_id) ON DELETE RESTRICT"
            )
        )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_design_tasks_delivery_asset "
            "ON design_tasks (delivery_asset_id) WHERE delivery_asset_id IS NOT NULL"
        )
    )


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
