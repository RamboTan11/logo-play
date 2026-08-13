"""Application-scoped recoverable scanner and Lark Outbox consumer."""

import asyncio
from contextlib import suppress

from src.config import AppSettings
from src.db.session import DatabaseRuntime
from src.services.lark_notification_service import LarkNotificationService

from pycore.core import get_logger

logger = get_logger()


class LarkWorker:
    """Periodically scan due reminders and deliver committed Outbox events."""

    def __init__(self, runtime: DatabaseRuntime, settings: AppSettings) -> None:
        self._runtime = runtime
        self._settings = settings
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="lark-notification-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                service = LarkNotificationService(self._settings)
                async with self._runtime.session_factory() as session:
                    await service.scan_due_reminders(session)
                    await service.process_outbox(session)
                    await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Lark notification worker cycle failed safely")
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=max(1, self._settings.lark_worker_interval_seconds),
                )
