"""Declare the verified nine-image capacity for connections created before T-027."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0019_backfill_model_input_image_capacity"


def _upgrade(connection: Connection) -> None:
    if not inspect(connection).has_table("model_connections"):
        return
    connection.execute(
        text(
            "UPDATE model_connections "
            "SET max_input_images = 9 "
            "WHERE max_input_images IS NULL"
        )
    )


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
