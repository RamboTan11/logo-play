"""Add idempotent pause boundaries for customer-gated timeout reminders."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0020_t028_reminder_pause"


def _upgrade(connection: Connection) -> None:
    if not inspect(connection).has_table("lark_reminder_snapshots"):
        return
    columns = {column["name"] for column in inspect(connection).get_columns("lark_reminder_snapshots")}
    if "paused_at" not in columns:
        connection.execute(text("ALTER TABLE lark_reminder_snapshots ADD COLUMN paused_at DATETIME"))
    if "paused_next_due_at" not in columns:
        connection.execute(
            text("ALTER TABLE lark_reminder_snapshots ADD COLUMN paused_next_due_at DATETIME")
        )


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
