"""Add immutable batch-generation policy versions and reference asset filenames."""

from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection
from src.db.models import (
    BatchGenerationPolicyState,
    BatchGenerationPolicyVersion,
    BatchGenerationStyleRotationCursor,
)

VERSION = "0003_batch_generation_policy"


def _upgrade(connection: Connection) -> None:
    """Apply additive policy storage without replacing prior infrastructure records."""

    asset_columns = {column["name"] for column in inspect(connection).get_columns("asset_records")}
    if "original_filename" not in asset_columns:
        connection.execute(text("ALTER TABLE asset_records ADD COLUMN original_filename VARCHAR(255)"))
    for table in (
        BatchGenerationPolicyVersion.__table__,
        BatchGenerationPolicyState.__table__,
        BatchGenerationStyleRotationCursor.__table__,
    ):
        table.create(connection, checkfirst=True)


async def upgrade(connection: AsyncConnection) -> None:
    """Create T-011 tables without mutating any published snapshot."""

    await connection.run_sync(_upgrade)
