"""Persist the internal batch strategy draft independently from published versions."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0016_batch_generation_policy_draft"


def _upgrade(connection: Connection) -> None:
    inspector = inspect(connection)
    if not inspector.has_table("batch_generation_policy_state"):
        return
    columns = {column["name"] for column in inspector.get_columns("batch_generation_policy_state")}
    if "draft_payload_json" not in columns:
        connection.execute(text("ALTER TABLE batch_generation_policy_state ADD COLUMN draft_payload_json TEXT"))
    if "draft_updated_at" not in columns:
        connection.execute(
            text("ALTER TABLE batch_generation_policy_state ADD COLUMN draft_updated_at DATETIME")
        )


async def upgrade(connection: AsyncConnection) -> None:
    """Add nullable draft columns without changing any active pointer or version."""

    await connection.run_sync(_upgrade)
