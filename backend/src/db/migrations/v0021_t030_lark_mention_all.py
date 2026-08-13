"""Persist the @all option for Lark rules and immutable reminder snapshots."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0021_t030_lark_mention_all"


def _add_boolean_column(connection: Connection, table_name: str, column_name: str) -> None:
    if not inspect(connection).has_table(table_name):
        return
    columns = {column["name"] for column in inspect(connection).get_columns(table_name)}
    if column_name not in columns:
        connection.execute(
            text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} BOOLEAN NOT NULL DEFAULT 0")
        )


def _upgrade(connection: Connection) -> None:
    _add_boolean_column(connection, "lark_notification_rules", "mention_all")
    _add_boolean_column(connection, "lark_reminder_snapshots", "mention_all")


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
