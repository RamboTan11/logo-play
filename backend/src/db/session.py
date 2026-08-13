"""Application-owned SQLAlchemy runtime based on the PyCore DB template."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from src.config import AppSettings


def backend_root() -> Path:
    """Resolve the backend root without depending on the current working directory."""

    return Path(__file__).resolve().parents[2]


def resolve_backend_path(raw_path: str) -> Path:
    """Resolve a configured path below backend/ and ensure its parent exists."""

    candidate = Path(raw_path)
    path = candidate if candidate.is_absolute() else backend_root() / candidate
    resolved: Path = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


class DatabaseRuntime:
    """Own the project database engine and sessions for one application instance."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.engine: AsyncEngine = create_async_engine(
            f"sqlite+aiosqlite:///{database_path.as_posix()}",
            future=True,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def dispose(self) -> None:
        """Release the application database engine."""

        await self.engine.dispose()


def create_database_runtime(settings: AppSettings) -> DatabaseRuntime:
    """Create a runtime using an absolute database file path."""

    return DatabaseRuntime(resolve_backend_path(settings.database_path))


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Provide an application session to route dependencies."""

    runtime: DatabaseRuntime = request.app.state.database_runtime
    async with runtime.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_context(runtime: DatabaseRuntime) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transaction-aware session for scripts and internal services."""

    async with runtime.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
