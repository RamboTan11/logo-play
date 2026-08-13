"""Add immutable single-image-edit policy versions and their active-state pointer."""

from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncConnection
from src.db.models import SingleImageEditPolicyState, SingleImageEditPolicyVersion

VERSION = "0004_single_image_edit_policy"


def _upgrade(connection: Connection) -> None:
    """Create only the additive T-012 policy tables."""

    for table in (SingleImageEditPolicyVersion.__table__, SingleImageEditPolicyState.__table__):
        table.create(connection, checkfirst=True)


async def upgrade(connection: AsyncConnection) -> None:
    """Apply the T-012 migration without changing existing policy versions."""

    await connection.run_sync(_upgrade)
