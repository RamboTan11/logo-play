"""Sanitized audit and notification-outbox persistence helpers."""

import json
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import AuditEvent, NotificationOutbox

_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "bot_token",
    "chat_id",
    "credential",
    "password",
    "secret",
    "token",
    "webhook",
}


class EventService:
    """Persist events in the caller's transaction without any delivery worker."""

    async def record_audit(
        self,
        session: AsyncSession,
        *,
        action: str,
        resource_type: str,
        resource_id: str,
        actor_id: str | None,
        trace_id: str,
        summary: Mapping[str, Any],
    ) -> AuditEvent:
        """Record an audit event after recursively redacting sensitive fields."""

        event = AuditEvent(
            event_id=uuid4().hex,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_id=actor_id,
            trace_id=trace_id,
            summary_json=_to_safe_json(summary),
        )
        session.add(event)
        return event

    async def enqueue_notification(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        resource_type: str,
        resource_id: str,
        trace_id: str,
        payload: Mapping[str, Any],
        idempotency_key: str | None = None,
    ) -> NotificationOutbox:
        """Add a pending outbox row without retaining any routing secrets."""

        event = NotificationOutbox(
            event_id=uuid4().hex,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            trace_id=trace_id,
            payload_json=_to_safe_json(payload),
            status="pending",
            attempt_no=0,
            idempotency_key=idempotency_key,
        )
        session.add(event)
        return event


def _to_safe_json(value: Mapping[str, Any]) -> str:
    """Serialize a structured summary while retaining no sensitive source values."""

    return json.dumps(_redact(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _redact(value: Any) -> Any:
    """Recursively redact known credential and routing fields from event details."""

    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]" if str(key).lower() in _SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact(item) for item in value]
    return value
