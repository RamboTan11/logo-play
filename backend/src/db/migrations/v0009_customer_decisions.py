"""Add saved Logos, endpoint idempotency, and customer task snapshots."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection
from src.db.models import EndpointIdempotencyRecord, SavedLogo

VERSION = "0009_customer_decisions"


def _upgrade(connection: Connection) -> None:
    """Apply the additive T-015 schema while preserving every historical task row."""

    for table in (SavedLogo.__table__, EndpointIdempotencyRecord.__table__):
        table.create(connection, checkfirst=True)

    inspector = inspect(connection)
    if not inspector.has_table("design_tasks"):
        return
    existing = {column["name"] for column in inspector.get_columns("design_tasks")}
    additions = {
        "adoption_suggestion": "TEXT",
        "adopted_logo_version_id": (
            "VARCHAR(64) REFERENCES logo_versions(id) ON DELETE RESTRICT"
        ),
        "adopted_asset_id": (
            "VARCHAR(64) REFERENCES asset_records(asset_id) ON DELETE RESTRICT"
        ),
        "initial_logo_version_id": (
            "VARCHAR(64) REFERENCES logo_versions(id) ON DELETE RESTRICT"
        ),
        "initial_asset_id": (
            "VARCHAR(64) REFERENCES asset_records(asset_id) ON DELETE RESTRICT"
        ),
        "ai_edit_inputs_json": "TEXT NOT NULL DEFAULT '[]'",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(
                text(f"ALTER TABLE design_tasks ADD COLUMN {name} {definition}")
            )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_design_tasks_customer_domain "
            "ON design_tasks (customer_id, domain)"
        )
    )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_design_tasks_customer_domain_open "
            "ON design_tasks (customer_id, domain) "
            "WHERE status IN ('waiting_assignment', 'in_progress')"
        )
    )


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
