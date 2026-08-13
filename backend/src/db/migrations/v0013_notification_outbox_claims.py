"""Add recoverable delivery claims to the existing notification Outbox."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0013_notification_outbox_claims"


def _upgrade(connection: Connection) -> None:
    """Append claim columns without rewriting or dropping existing Outbox rows."""

    inspector = inspect(connection)
    if not inspector.has_table("notification_outbox"):
        return
    columns = {column["name"] for column in inspector.get_columns("notification_outbox")}
    if "claimed_by" not in columns:
        connection.execute(
            text("ALTER TABLE notification_outbox ADD COLUMN claimed_by VARCHAR(64)")
        )
    if "claim_expires_at" not in columns:
        connection.execute(
            text("ALTER TABLE notification_outbox ADD COLUMN claim_expires_at DATETIME")
        )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_notification_outbox_claim "
            "ON notification_outbox (status, claim_expires_at, next_attempt_at)"
        )
    )


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
