"""Enforce one customer-level active task and repair conflicting historical rows."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0011_customer_task_exclusivity"


def _upgrade(connection: Connection) -> None:
    """Cancel invalid open rows before adding the customer-level unique index."""

    if not inspect(connection).has_table("design_tasks"):
        return

    connection.execute(text("DROP INDEX IF EXISTS uq_design_tasks_customer_domain_open"))
    connection.execute(
        text(
            """
            UPDATE design_tasks AS task
            SET status = 'canceled', updated_at = CURRENT_TIMESTAMP
            WHERE task.status IN ('waiting_assignment', 'in_progress')
              AND EXISTS (
                SELECT 1
                FROM design_tasks AS completed
                WHERE completed.customer_id = task.customer_id
                  AND completed.status = 'completed'
              )
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE design_tasks AS task
            SET status = 'canceled', updated_at = CURRENT_TIMESTAMP
            WHERE task.status IN ('waiting_assignment', 'in_progress')
              AND EXISTS (
                SELECT 1
                FROM design_tasks AS newer
                WHERE newer.customer_id = task.customer_id
                  AND newer.status IN ('waiting_assignment', 'in_progress')
                  AND (
                    newer.submitted_at > task.submitted_at
                    OR (newer.submitted_at = task.submitted_at AND newer.id > task.id)
                  )
              )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_design_tasks_customer_open
            ON design_tasks (customer_id)
            WHERE status IN ('waiting_assignment', 'in_progress')
            """
        )
    )


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
