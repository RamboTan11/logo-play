"""Add shared admin authentication and the customer access-link lifecycle."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection
from src.db.models import AdminSession, CustomerAccessLink, CustomerSession, SharedAdministrator

VERSION = "0008_auth_customer_access"


def _upgrade(connection: Connection) -> None:
    existing = {column["name"] for column in inspect(connection).get_columns("customers")}
    additions = {
        "access_state": "VARCHAR(24) NOT NULL DEFAULT 'unstarted'",
        "initial_validity_days": "INTEGER NOT NULL DEFAULT 3",
        "access_expires_at": "DATETIME",
        "updated_at": "DATETIME NOT NULL DEFAULT '1970-01-01 00:00:00'",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(text(f"ALTER TABLE customers ADD COLUMN {name} {definition}"))
    timestamp_source = (
        "COALESCE(created_at, CURRENT_TIMESTAMP)" if "created_at" in existing else "CURRENT_TIMESTAMP"
    )
    connection.execute(
        text(
            "UPDATE customers SET updated_at = "
            f"CASE WHEN updated_at = '1970-01-01 00:00:00' THEN {timestamp_source} "
            "ELSE updated_at END"
        )
    )
    for table in (
        SharedAdministrator.__table__,
        CustomerAccessLink.__table__,
        AdminSession.__table__,
        CustomerSession.__table__,
    ):
        table.create(connection, checkfirst=True)


async def upgrade(connection: AsyncConnection) -> None:
    """Apply the additive T-009 schema without changing historical rows."""

    await connection.run_sync(_upgrade)
