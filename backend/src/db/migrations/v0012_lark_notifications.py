"""Add the encrypted Lark configuration and recoverable notification pipeline."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0012_lark_notifications"

_RULES = (
    ("task.adoption_submitted", 0, None, None, None),
    ("task.waiting_assignment_overdue", 0, 6, 12, 3),
    ("task.upload_overdue", 0, 36, 12, 3),
    ("task.adoption_changed_before_acceptance", 0, None, None, None),
    ("task.adoption_changed_in_progress", 0, None, None, None),
    ("task.delivery_uploaded", 0, None, None, None),
)


def _upgrade(connection: Connection) -> None:
    """Create append-only tables and extend the existing Outbox without data loss."""

    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS lark_channel_configs (
              id VARCHAR(32) PRIMARY KEY,
              enabled BOOLEAN NOT NULL DEFAULT 0,
              group_label VARCHAR(120),
              webhook_ciphertext TEXT,
              signing_enabled BOOLEAN NOT NULL DEFAULT 0,
              signing_secret_ciphertext TEXT,
              last_test_status VARCHAR(24),
              last_tested_at DATETIME,
              last_success_at DATETIME,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS lark_recipients (
              id VARCHAR(64) PRIMARY KEY,
              display_name VARCHAR(100),
              open_id_ciphertext TEXT NOT NULL,
              open_id_digest VARCHAR(64) NOT NULL UNIQUE,
              open_id_masked VARCHAR(64) NOT NULL,
              enabled BOOLEAN NOT NULL DEFAULT 1,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS lark_notification_rules (
              event_type VARCHAR(100) PRIMARY KEY,
              enabled BOOLEAN NOT NULL DEFAULT 0,
              recipient_ids_json TEXT NOT NULL DEFAULT '[]',
              threshold_hours INTEGER,
              repeat_interval_hours INTEGER,
              max_repeat_count INTEGER,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS lark_reminder_snapshots (
              id VARCHAR(64) PRIMARY KEY,
              task_id VARCHAR(64) NOT NULL REFERENCES design_tasks(id) ON DELETE RESTRICT,
              event_type VARCHAR(100) NOT NULL,
              threshold_hours INTEGER NOT NULL,
              repeat_interval_hours INTEGER NOT NULL,
              max_repeat_count INTEGER NOT NULL,
              recipient_snapshot_json TEXT NOT NULL,
              next_due_at DATETIME NOT NULL,
              last_reminder_index INTEGER NOT NULL DEFAULT -1,
              active BOOLEAN NOT NULL DEFAULT 1,
              stopped_reason VARCHAR(40),
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              CONSTRAINT uq_lark_reminder_task_event UNIQUE (task_id, event_type)
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS lark_notification_deliveries (
              id VARCHAR(64) PRIMARY KEY,
              outbox_event_id VARCHAR(64) UNIQUE REFERENCES notification_outbox(event_id) ON DELETE RESTRICT,
              event_type VARCHAR(100) NOT NULL,
              task_id VARCHAR(64),
              reminder_index INTEGER NOT NULL DEFAULT 0,
              notification_mode VARCHAR(24) NOT NULL,
              mention_count INTEGER NOT NULL DEFAULT 0,
              status VARCHAR(24) NOT NULL,
              error_category VARCHAR(80),
              attempt_count INTEGER NOT NULL DEFAULT 0,
              trace_id VARCHAR(64) NOT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              last_attempt_at DATETIME,
              accepted_at DATETIME
            )
            """
        )
    )

    inspector = inspect(connection)
    if inspector.has_table("notification_outbox"):
        columns = {column["name"] for column in inspector.get_columns("notification_outbox")}
        if "idempotency_key" not in columns:
            connection.execute(text("ALTER TABLE notification_outbox ADD COLUMN idempotency_key VARCHAR(220)"))
        if "next_attempt_at" not in columns:
            connection.execute(text("ALTER TABLE notification_outbox ADD COLUMN next_attempt_at DATETIME"))
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_outbox_idempotency "
                "ON notification_outbox (idempotency_key) WHERE idempotency_key IS NOT NULL"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_notification_outbox_retry "
                "ON notification_outbox (status, next_attempt_at)"
            )
        )

    connection.execute(
        text(
            "INSERT OR IGNORE INTO lark_channel_configs "
            "(id, enabled, signing_enabled) VALUES ('default', 0, 0)"
        )
    )
    for event_type, enabled, threshold, repeat_interval, repeat_count in _RULES:
        connection.execute(
            text(
                """
                INSERT OR IGNORE INTO lark_notification_rules
                  (event_type, enabled, recipient_ids_json, threshold_hours,
                   repeat_interval_hours, max_repeat_count)
                VALUES (:event_type, :enabled, '[]', :threshold, :repeat_interval, :repeat_count)
                """
            ),
            {
                "event_type": event_type,
                "enabled": enabled,
                "threshold": threshold,
                "repeat_interval": repeat_interval,
                "repeat_count": repeat_count,
            },
        )


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
