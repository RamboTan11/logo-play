"""Add the persistent customer batch generation runtime."""

from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncConnection
from src.db.models import (
    DesignTask,
    GenerationCandidateJob,
    GenerationRequest,
    LogoVersion,
)

VERSION = "0005_batch_generation_runtime"


def _upgrade(connection: Connection) -> None:
    for table in (
        DesignTask.__table__,
        GenerationRequest.__table__,
        GenerationCandidateJob.__table__,
        LogoVersion.__table__,
    ):
        table.create(connection, checkfirst=True)


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
