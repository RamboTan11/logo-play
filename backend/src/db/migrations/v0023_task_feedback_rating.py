"""Store the latest customer feedback and delivery rating on design tasks."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0023_task_feedback_rating"


def _upgrade(connection: Connection) -> None:
    inspector = inspect(connection)
    if not inspector.has_table("design_tasks"):
        return
    columns = {column["name"] for column in inspector.get_columns("design_tasks")}
    if "customer_feedback" not in columns:
        connection.execute(text("ALTER TABLE design_tasks ADD COLUMN customer_feedback TEXT"))
    if "rating" not in columns:
        connection.execute(text("ALTER TABLE design_tasks ADD COLUMN rating INTEGER"))
    connection.execute(
        text(
            "INSERT OR IGNORE INTO lark_notification_rules "
            "(event_type, enabled, recipient_ids_json) VALUES "
            "('task.customer_feedback_submitted', 0, '[]')"
        )
    )


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
