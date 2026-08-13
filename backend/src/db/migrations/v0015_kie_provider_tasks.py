"""Persist asynchronous provider task identifiers for restart recovery."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0015_kie_provider_tasks"


def _add_provider_task_columns(connection: Connection, table_name: str) -> None:
    inspector = inspect(connection)
    if not inspector.has_table(table_name):
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "provider_task_id" not in columns:
        connection.execute(
            text(f"ALTER TABLE {table_name} ADD COLUMN provider_task_id VARCHAR(255)")
        )
    if "provider_submission_state" not in columns:
        connection.execute(
            text(f"ALTER TABLE {table_name} ADD COLUMN provider_submission_state VARCHAR(24)")
        )


def _upgrade(connection: Connection) -> None:
    _add_provider_task_columns(connection, "generation_candidate_jobs")
    _add_provider_task_columns(connection, "single_image_edit_requests")


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
