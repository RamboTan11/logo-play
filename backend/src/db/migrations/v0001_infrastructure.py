"""Initial shared infrastructure tables for T-008."""

from sqlalchemy import Connection, Table
from sqlalchemy.ext.asyncio import AsyncConnection
from src.db.models import (
    AssetRecord,
    AuditEvent,
    Customer,
    ModelConnection,
    NotificationOutbox,
)

VERSION = "0001_infrastructure"
INFRASTRUCTURE_TABLES: tuple[Table, ...] = (
    Customer.__table__,
    ModelConnection.__table__,
    AssetRecord.__table__,
    AuditEvent.__table__,
    NotificationOutbox.__table__,
)


def _create_infrastructure_tables(connection: Connection) -> None:
    """Create only T-008 business tables; the ledger is created by the runner."""

    for table in INFRASTRUCTURE_TABLES:
        table.create(connection, checkfirst=True)


async def upgrade(connection: AsyncConnection) -> None:
    """Create only the initial infrastructure tables, preserving existing data."""

    await connection.run_sync(_create_infrastructure_tables)
