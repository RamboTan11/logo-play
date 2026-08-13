"""Fixed-group Lark configuration, cards, reminders, and recoverable delivery."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, cast
from urllib.parse import quote, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from src.config import AppSettings
from src.db.models import (
    AuditEvent,
    Customer,
    DesignTask,
    LarkChannelConfig,
    LarkNotificationDelivery,
    LarkNotificationRule,
    LarkRecipient,
    LarkReminderSnapshot,
    NotificationOutbox,
)
from src.models.lark_notification import (
    GROUP_ONLY_EVENT,
    LARK_EVENT_TYPES,
    TIMED_EVENTS,
    LarkChannelDto,
    LarkChannelUpdate,
    LarkNotificationRuleBatchUpdate,
    LarkNotificationRuleDto,
    LarkNotificationRuleUpdate,
    LarkRecentDeliveryDto,
    LarkRecentDeliveryListDto,
    LarkRecipientCreate,
    LarkRecipientDto,
    LarkRecipientUpdate,
    LarkTestRequest,
    LarkTestResultDto,
)
from src.services.event_service import EventService
from src.services.lark_secret_service import LarkSecretConfigurationError, LarkSecretService

LARK_EVENTS = LARK_EVENT_TYPES
EVENT_COPY = {
    "task.adoption_submitted": ("新任务提醒", "客户已提交采用方案，等待接单"),
    "task.waiting_assignment_overdue": ("待接单提醒", "任务提交已超过 {elapsed_hours} 小时，仍未接单"),
    "task.upload_overdue": ("上传图片提醒", "任务接单已超过 {elapsed_hours} 小时，尚未上传交付图片"),
    "task.adoption_changed_before_acceptance": ("方案变更通知", "客户已修改采用方案"),
    "task.adoption_changed_in_progress": ("方案变更通知", "客户已修改采用方案"),
    "task.delivery_uploaded": ("图片上传成功", "交付图片已上传，任务已完成"),
}
EXPECTED_STATUS = {
    "task.waiting_assignment_overdue": "waiting_assignment",
    "task.upload_overdue": "in_progress",
}
_CHANNEL_ID = "default"
_MAX_CARD_BYTES = 20 * 1024
_BEIJING_TZ = ZoneInfo("Asia/Shanghai")
_SAFE_ERRORS = {
    "configuration_unavailable": "通知配置不可用",
    "network_error": "网络连接失败",
    "provider_timeout": "Lark 响应超时",
    "rate_limited": "Lark 请求受限",
    "provider_temporary": "Lark 服务暂时不可用",
    "provider_rejected": "Lark 拒绝了消息",
    "invalid_task": "任务状态已变化",
}


def _reminder_elapsed_hours(
    threshold_hours: int, repeat_interval_hours: int, reminder_index: int
) -> int:
    return threshold_hours + max(0, reminder_index) * repeat_interval_hours


def _customer_access_status(customer: Customer, now: datetime) -> str:
    if customer.access_state == "unstarted":
        return "unstarted"
    expires_at = customer.access_expires_at
    if expires_at is None:
        return "expired"
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return "expired" if expires_at <= now else ("stopped" if customer.access_state == "stopped" else "active")


def _access_pause_boundary(customer: Customer, now: datetime) -> datetime:
    """Use explicit stop time, or the natural expiration instant, as the boundary."""

    if customer.access_state == "active" and customer.access_expires_at is not None:
        expires_at = customer.access_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at if expires_at <= now else now
    return now


class LarkNotificationError(RuntimeError):
    """A stable administrator-safe notification error."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class CustomerAccessUnavailableError(RuntimeError):
    """A timed delivery was claimed while its customer became unavailable."""


@dataclass(frozen=True, slots=True)
class MentionTarget:
    id: str
    display_name: str | None
    open_id: str
    open_id_masked: str


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    accepted: bool
    retryable: bool
    error_category: str | None = None


class LarkWebhookClient:
    """Minimal direct-HTTP custom-bot adapter with no environment inheritance."""

    async def send(self, webhook: str, payload: dict[str, Any]) -> DeliveryAttempt:
        try:
            async with httpx.AsyncClient(
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(
                    connect=5.0,
                    write=5.0,
                    read=10.0,
                    pool=5.0,
                ),
            ) as client:
                response = await client.post(webhook, json=payload)
        except httpx.TimeoutException:
            return DeliveryAttempt(False, True, "provider_timeout")
        except httpx.HTTPError:
            return DeliveryAttempt(False, True, "network_error")

        if response.status_code == 429:
            return DeliveryAttempt(False, True, "rate_limited")
        if response.status_code >= 500:
            return DeliveryAttempt(False, True, "provider_temporary")
        if response.status_code >= 400:
            return DeliveryAttempt(False, False, "provider_rejected")
        try:
            body = response.json()
        except ValueError:
            return DeliveryAttempt(False, False, "provider_rejected")
        code = body.get("code") if isinstance(body, dict) else None
        if code == 0:
            return DeliveryAttempt(True, False)
        if code in {11232, 90013}:
            return DeliveryAttempt(False, True, "rate_limited")
        return DeliveryAttempt(False, False, "provider_rejected")


class LarkWorkflowService:
    """Write notification intent and timer snapshots inside business transactions."""

    def __init__(self, events: EventService | None = None) -> None:
        self._events = events or EventService()

    async def enqueue_immediate(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        task_id: str,
        trace_id: str,
        payload: dict[str, Any] | None = None,
    ) -> NotificationOutbox | None:
        channel = await session.get(LarkChannelConfig, _CHANNEL_ID)
        if channel is None or not channel.enabled or channel.webhook_ciphertext is None:
            return None
        rule = await session.get(LarkNotificationRule, event_type)
        if rule is None or not rule.enabled:
            return None
        return await self._events.enqueue_notification(
            session,
            event_type=event_type,
            resource_type="design_task",
            resource_id=task_id,
            trace_id=trace_id,
            payload={"task_id": task_id, **(payload or {})},
            idempotency_key=f"{event_type}:{task_id}:0",
        )

    async def snapshot_stage(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        event_type: str,
        entered_at: datetime,
    ) -> LarkReminderSnapshot | None:
        if event_type not in TIMED_EVENTS:
            raise ValueError("Only timed rules can be snapshotted")
        channel = await session.get(LarkChannelConfig, _CHANNEL_ID)
        if channel is None or not channel.enabled or channel.webhook_ciphertext is None:
            return None
        rule = await session.get(LarkNotificationRule, event_type)
        if rule is None or not rule.enabled:
            return None
        if None in (rule.threshold_hours, rule.repeat_interval_hours, rule.max_repeat_count):
            return None
        recipients = await _enabled_recipients(session, _json_ids(rule.recipient_ids_json))
        if not rule.mention_all and not recipients:
            return None
        snapshot_payload = [
            {
                "id": item.id,
                "display_name": item.display_name,
                "open_id_masked": item.open_id_masked,
                "open_id_ciphertext": item.open_id_ciphertext,
            }
            for item in recipients
        ]
        existing = await session.scalar(
            select(LarkReminderSnapshot).where(
                LarkReminderSnapshot.task_id == task_id,
                LarkReminderSnapshot.event_type == event_type,
            )
        )
        if existing is not None:
            return existing
        threshold = cast(int, rule.threshold_hours)
        snapshot = LarkReminderSnapshot(
            id=uuid4().hex,
            task_id=task_id,
            event_type=event_type,
            threshold_hours=threshold,
            repeat_interval_hours=cast(int, rule.repeat_interval_hours),
            max_repeat_count=cast(int, rule.max_repeat_count),
            mention_all=rule.mention_all,
            recipient_snapshot_json=json.dumps(snapshot_payload, ensure_ascii=True, separators=(",", ":")),
            next_due_at=entered_at + timedelta(hours=threshold),
            last_reminder_index=-1,
            active=True,
            updated_at=entered_at,
        )
        session.add(snapshot)
        return snapshot

    async def stop_task(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        reason: str,
        event_type: str | None = None,
        now: datetime | None = None,
    ) -> None:
        statement = update(LarkReminderSnapshot).where(
            LarkReminderSnapshot.task_id == task_id,
            LarkReminderSnapshot.active.is_(True),
        )
        if event_type is not None:
            statement = statement.where(LarkReminderSnapshot.event_type == event_type)
        await session.execute(
            statement.values(
                active=False,
                stopped_reason=reason,
                updated_at=now or datetime.now(UTC),
            )
        )

    async def pause_customer(
        self,
        session: AsyncSession,
        customer_id: str,
        *,
        now: datetime,
        reason: str,
    ) -> None:
        """Freeze active timeout snapshots at one durable customer boundary."""

        rows = list(
            (
                await session.scalars(
                    select(LarkReminderSnapshot)
                    .join(DesignTask, DesignTask.id == LarkReminderSnapshot.task_id)
                    .where(
                        DesignTask.customer_id == customer_id,
                        LarkReminderSnapshot.active.is_(True),
                        LarkReminderSnapshot.paused_at.is_(None),
                    )
                )
            ).all()
        )
        for snapshot in rows:
            snapshot.paused_at = now
            snapshot.paused_next_due_at = snapshot.next_due_at
            snapshot.stopped_reason = reason
            snapshot.updated_at = now

    async def resume_customer(
        self, session: AsyncSession, customer_id: str, *, now: datetime
    ) -> None:
        """Resume paused timeout snapshots without catch-up reminders."""

        rows = list(
            (
                await session.scalars(
                    select(LarkReminderSnapshot)
                    .join(DesignTask, DesignTask.id == LarkReminderSnapshot.task_id)
                    .where(
                        DesignTask.customer_id == customer_id,
                        LarkReminderSnapshot.active.is_(True),
                        LarkReminderSnapshot.paused_at.is_not(None),
                    )
                )
            ).all()
        )
        for snapshot in rows:
            paused_at = snapshot.paused_at or now
            original_due = snapshot.paused_next_due_at or snapshot.next_due_at
            remaining = max((original_due - paused_at).total_seconds(), 0)
            snapshot.next_due_at = now + timedelta(seconds=remaining)
            snapshot.paused_at = None
            snapshot.paused_next_due_at = None
            snapshot.stopped_reason = None
            snapshot.updated_at = now


class LarkNotificationService:
    """Manage safe configuration and execute the Lark delivery pipeline."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        client: LarkWebhookClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or LarkWebhookClient()
        self._secrets = LarkSecretService(settings.lark_config_encryption_key)
        self._admin_base_url = _validate_admin_base(settings.admin_frontend_base_url)

    async def get_channel(self, session: AsyncSession) -> LarkChannelDto:
        return _channel_dto(await self._channel(session))

    async def update_channel(
        self,
        session: AsyncSession,
        payload: LarkChannelUpdate,
        actor_id: str,
    ) -> LarkChannelDto:
        channel = await self._channel(session)
        if channel.webhook_ciphertext is None and payload.webhook is None:
            raise LarkNotificationError("webhook_required", "首次配置必须填写 Webhook 地址", 422)
        if payload.signing_enabled and channel.signing_secret_ciphertext is None and payload.signing_secret is None:
            raise LarkNotificationError("signing_secret_required", "启用签名时必须填写签名密钥", 422)
        if payload.webhook is not None:
            parsed = urlsplit(payload.webhook)
            if parsed.scheme == "http" and self._settings.app_env.strip().lower() != "development":
                raise LarkNotificationError("webhook_invalid", "生产环境仅允许国际版 Lark HTTPS Webhook", 422)
        now = datetime.now(UTC)
        channel.enabled = payload.enabled
        channel.group_label = payload.group_label
        channel.signing_enabled = payload.signing_enabled
        if payload.webhook is not None:
            channel.webhook_ciphertext = self._secrets.encrypt(payload.webhook)
        if payload.signing_secret is not None:
            channel.signing_secret_ciphertext = self._secrets.encrypt(payload.signing_secret)
        channel.updated_at = now
        await _audit(
            session,
            action="lark.channel.updated",
            resource_type="lark_channel",
            resource_id=channel.id,
            actor_id=actor_id,
            summary={
                "enabled": channel.enabled,
                "group_label_configured": channel.group_label is not None,
                "webhook_replaced": payload.webhook is not None,
                "signing_enabled": channel.signing_enabled,
                "signing_secret_replaced": payload.signing_secret is not None,
            },
        )
        return _channel_dto(channel)

    async def list_recipients(self, session: AsyncSession) -> list[LarkRecipientDto]:
        recipients = list(
            (await session.scalars(select(LarkRecipient).order_by(LarkRecipient.created_at))).all()
        )
        return [_recipient_dto(item) for item in recipients]

    async def create_recipient(
        self,
        session: AsyncSession,
        payload: LarkRecipientCreate,
        actor_id: str,
    ) -> LarkRecipientDto:
        digest = sha256(payload.open_id.encode("utf-8")).hexdigest()
        if await session.scalar(select(LarkRecipient.id).where(LarkRecipient.open_id_digest == digest)):
            raise LarkNotificationError("recipient_exists", "该 open_id 已存在", 409)
        now = datetime.now(UTC)
        recipient = LarkRecipient(
            id=uuid4().hex,
            display_name=payload.display_name,
            open_id_ciphertext=self._secrets.encrypt(payload.open_id),
            open_id_digest=digest,
            open_id_masked=_mask_open_id(payload.open_id),
            enabled=payload.enabled,
            created_at=now,
            updated_at=now,
        )
        session.add(recipient)
        await session.flush()
        await _audit(
            session,
            action="lark.recipient.created",
            resource_type="lark_recipient",
            resource_id=recipient.id,
            actor_id=actor_id,
            summary={"enabled": recipient.enabled, "has_display_name": recipient.display_name is not None},
        )
        return _recipient_dto(recipient)

    async def update_recipient(
        self,
        session: AsyncSession,
        recipient_id: str,
        payload: LarkRecipientUpdate,
        actor_id: str,
    ) -> LarkRecipientDto:
        recipient = await session.get(LarkRecipient, recipient_id)
        if recipient is None:
            raise LarkNotificationError("recipient_not_found", "通知人员不存在", 404)
        fields = payload.model_fields_set
        if payload.enabled is False:
            await _validate_enabled_rules(session, disabled_recipient_id=recipient.id)
        if "display_name" in fields:
            recipient.display_name = payload.display_name
        if "open_id" in fields and payload.open_id is not None:
            digest = sha256(payload.open_id.encode("utf-8")).hexdigest()
            duplicate = await session.scalar(
                select(LarkRecipient.id).where(
                    LarkRecipient.open_id_digest == digest,
                    LarkRecipient.id != recipient.id,
                )
            )
            if duplicate:
                raise LarkNotificationError("recipient_exists", "该 open_id 已存在", 409)
            recipient.open_id_ciphertext = self._secrets.encrypt(payload.open_id)
            recipient.open_id_digest = digest
            recipient.open_id_masked = _mask_open_id(payload.open_id)
        if payload.enabled is not None:
            recipient.enabled = payload.enabled
        recipient.updated_at = datetime.now(UTC)
        await _audit(
            session,
            action="lark.recipient.updated",
            resource_type="lark_recipient",
            resource_id=recipient.id,
            actor_id=actor_id,
            summary={
                "enabled": recipient.enabled,
                "display_name_changed": "display_name" in fields,
                "open_id_replaced": "open_id" in fields and payload.open_id is not None,
            },
        )
        return _recipient_dto(recipient)

    async def delete_recipient(
        self, session: AsyncSession, recipient_id: str, actor_id: str
    ) -> None:
        recipient = await session.get(LarkRecipient, recipient_id)
        if recipient is None:
            raise LarkNotificationError("recipient_not_found", "通知人员不存在", 404)
        rules = (await session.scalars(select(LarkNotificationRule))).all()
        referenced = any(recipient_id in _json_ids(rule.recipient_ids_json) for rule in rules)
        snapshots = await session.scalar(
            select(func.count()).select_from(LarkReminderSnapshot).where(
                LarkReminderSnapshot.recipient_snapshot_json.contains(f'"id":"{recipient_id}"')
            )
        )
        if referenced or int(snapshots or 0) > 0:
            raise LarkNotificationError("recipient_in_use", "通知人员已被规则或任务快照引用，请改为停用", 409)
        await session.execute(delete(LarkRecipient).where(LarkRecipient.id == recipient_id))
        await _audit(
            session,
            action="lark.recipient.deleted",
            resource_type="lark_recipient",
            resource_id=recipient_id,
            actor_id=actor_id,
            summary={"deleted": True},
        )

    async def list_rules(self, session: AsyncSession) -> list[LarkNotificationRuleDto]:
        rules = {rule.event_type: rule for rule in (await session.scalars(select(LarkNotificationRule))).all()}
        return [_rule_dto(rules[event]) for event in LARK_EVENTS if event in rules]

    async def update_rule(
        self,
        session: AsyncSession,
        event_type: str,
        payload: LarkNotificationRuleUpdate,
        actor_id: str,
    ) -> LarkNotificationRuleDto:
        await self._validate_rule_update(session, event_type, payload)
        return await self._apply_rule_update(session, event_type, payload, actor_id)

    async def update_rules(
        self,
        session: AsyncSession,
        payload: LarkNotificationRuleBatchUpdate,
        actor_id: str,
    ) -> list[LarkNotificationRuleDto]:
        updates = {item.event_type: item for item in payload.rules}
        for event_type in LARK_EVENTS:
            await self._validate_rule_update(session, event_type, updates[event_type])
        updated_at = datetime.now(UTC)
        return [
            await self._apply_rule_update(
                session,
                event_type,
                updates[event_type],
                actor_id,
                updated_at=updated_at,
            )
            for event_type in LARK_EVENTS
        ]

    async def _validate_rule_update(
        self,
        session: AsyncSession,
        event_type: str,
        payload: LarkNotificationRuleUpdate,
    ) -> None:
        if event_type not in LARK_EVENTS:
            raise LarkNotificationError("invalid_event_type", "通知规则不存在", 404)
        timed = event_type in TIMED_EVENTS
        if timed and None in (
            payload.threshold_hours,
            payload.repeat_interval_hours,
            payload.max_repeat_count,
        ):
            raise LarkNotificationError("timing_required", "超时规则必须填写阈值、间隔和最大重复次数", 422)
        if not timed and any(
            value is not None
            for value in (payload.threshold_hours, payload.repeat_interval_hours, payload.max_repeat_count)
        ):
            raise LarkNotificationError("timing_not_allowed", "即时通知不接受超时参数", 422)
        if event_type == GROUP_ONLY_EVENT and (payload.mention_all or payload.recipient_ids):
            raise LarkNotificationError("recipients_not_allowed", "图片上传成功仅发送群通知", 422)
        if event_type != GROUP_ONLY_EVENT and payload.enabled:
            enabled = await _enabled_recipients(session, payload.recipient_ids)
            if len(enabled) != len(payload.recipient_ids) or (not payload.mention_all and not enabled):
                raise LarkNotificationError(
                    "notification_target_required", "启用规则至少选择一种通知目标", 422
                )
        if await session.get(LarkNotificationRule, event_type) is None:
            raise LarkNotificationError("invalid_event_type", "通知规则不存在", 404)

    async def _apply_rule_update(
        self,
        session: AsyncSession,
        event_type: str,
        payload: LarkNotificationRuleUpdate,
        actor_id: str,
        *,
        updated_at: datetime | None = None,
    ) -> LarkNotificationRuleDto:
        timed = event_type in TIMED_EVENTS
        rule = await session.get(LarkNotificationRule, event_type)
        if rule is None:
            raise LarkNotificationError("invalid_event_type", "通知规则不存在", 404)
        rule.enabled = payload.enabled
        rule.mention_all = False if event_type == GROUP_ONLY_EVENT else payload.mention_all
        rule.recipient_ids_json = json.dumps(payload.recipient_ids, separators=(",", ":"))
        rule.threshold_hours = payload.threshold_hours if timed else None
        rule.repeat_interval_hours = payload.repeat_interval_hours if timed else None
        rule.max_repeat_count = payload.max_repeat_count if timed else None
        rule.updated_at = updated_at or datetime.now(UTC)
        await _audit(
            session,
            action="lark.rule.updated",
            resource_type="lark_rule",
            resource_id=event_type,
            actor_id=actor_id,
            summary={
                "enabled": rule.enabled,
                "mention_all": rule.mention_all,
                "recipient_count": len(payload.recipient_ids),
                "threshold_hours": rule.threshold_hours,
                "repeat_interval_hours": rule.repeat_interval_hours,
                "max_repeat_count": rule.max_repeat_count,
            },
        )
        return _rule_dto(rule)

    async def test_channel(
        self,
        session: AsyncSession,
        payload: LarkTestRequest,
        actor_id: str,
        *,
        now: datetime | None = None,
    ) -> LarkTestResultDto:
        tested_at = now or datetime.now(UTC)
        channel = await self._ready_channel(session)
        mentions = await self._mention_targets(session, payload.recipient_ids) if payload.mention_enabled else []
        if payload.mention_enabled and len(mentions) != len(payload.recipient_ids):
            raise LarkNotificationError("active_recipient_required", "测试 @ 只能选择已启用人员", 422)
        webhook, signing_secret = self._channel_secrets(channel)
        card = build_lark_card(
            title="测试通知",
            subtitle="Lark 通知通道测试",
            mentions=mentions,
            customer_name="测试客户",
            domain="example.com",
            submitted_at=tested_at,
            task_url=f"{self._admin_base_url}/admin/tasks",
        )
        trace_id = uuid4().hex
        attempt = await self._send_with_bounded_retries(webhook, card, signing_secret, tested_at)
        status = "accepted" if attempt.accepted else "failed"
        channel.last_test_status = status
        channel.last_tested_at = tested_at
        if attempt.accepted:
            channel.last_success_at = tested_at
        delivery = LarkNotificationDelivery(
            id=uuid4().hex,
            event_type="lark.test",
            task_id=None,
            reminder_index=0,
            notification_mode="mention" if mentions else "group_only",
            mention_count=len(mentions),
            status=status,
            error_category=attempt.error_category,
            attempt_count=self._settings.lark_delivery_max_attempts if not attempt.accepted and attempt.retryable else 1,
            trace_id=trace_id,
            created_at=tested_at,
            last_attempt_at=tested_at,
            accepted_at=tested_at if attempt.accepted else None,
        )
        session.add(delivery)
        await _audit(
            session,
            action="lark.channel.tested",
            resource_type="lark_channel",
            resource_id=channel.id,
            actor_id=actor_id,
            summary={"status": status, "mention_count": len(mentions)},
            trace_id=trace_id,
        )
        return LarkTestResultDto(accepted=attempt.accepted, status=status, tested_at=tested_at, trace_id=trace_id)

    async def recent_deliveries(
        self,
        session: AsyncSession,
        *,
        status: str,
        limit: int,
    ) -> LarkRecentDeliveryListDto:
        statement = select(LarkNotificationDelivery)
        if status != "all":
            statement = statement.where(LarkNotificationDelivery.status == status)
        deliveries = list(
            (
                await session.scalars(
                    statement.order_by(LarkNotificationDelivery.created_at.desc()).limit(limit)
                )
            ).all()
        )
        return LarkRecentDeliveryListDto(
            items=[
                LarkRecentDeliveryDto(
                    id=item.id,
                    created_at=item.created_at,
                    event_type=item.event_type,
                    task_id=item.task_id,
                    task_url=(
                        self._task_login_url(item.task_id)
                        if item.task_id
                        else None
                    ),
                    notification_mode=cast(Any, item.notification_mode),
                    reminder_index=item.reminder_index,
                    status=cast(Any, item.status),
                    error_summary=_SAFE_ERRORS.get(item.error_category or "") if item.error_category else None,
                )
                for item in deliveries
            ]
        )

    async def scan_due_reminders(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
    ) -> int:
        current = now or datetime.now(UTC)
        # Natural expiration must pause snapshots even when their next reminder
        # is still in the future; otherwise a later edit could lose the pause boundary.
        all_active = list(
            (
                await session.scalars(
                    select(LarkReminderSnapshot).where(
                        LarkReminderSnapshot.active.is_(True),
                        LarkReminderSnapshot.paused_at.is_(None),
                    )
                )
            ).all()
        )
        for snapshot in all_active:
            task = await session.get(DesignTask, snapshot.task_id)
            customer = await session.get(Customer, task.customer_id) if task else None
            if customer is not None and _customer_access_status(customer, current) != "active":
                boundary = _access_pause_boundary(customer, current)
                snapshot.paused_at = boundary
                snapshot.paused_next_due_at = snapshot.next_due_at
                snapshot.stopped_reason = "customer_access_unavailable"
                snapshot.updated_at = current

        snapshots = list(
            (
                await session.scalars(
                    select(LarkReminderSnapshot)
                    .where(
                        LarkReminderSnapshot.active.is_(True),
                        LarkReminderSnapshot.paused_at.is_(None),
                        LarkReminderSnapshot.next_due_at <= current,
                    )
                    .order_by(LarkReminderSnapshot.next_due_at, LarkReminderSnapshot.id)
                )
            ).all()
        )
        created = 0
        for snapshot in snapshots:
            task = await session.get(DesignTask, snapshot.task_id)
            if task is None or task.status != EXPECTED_STATUS.get(snapshot.event_type):
                snapshot.active = False
                snapshot.stopped_reason = "state_changed"
                snapshot.updated_at = current
                continue
            reminder_index = snapshot.last_reminder_index + 1
            if reminder_index > snapshot.max_repeat_count:
                snapshot.active = False
                snapshot.stopped_reason = "repeat_limit_reached"
                snapshot.updated_at = current
                continue
            key = f"{snapshot.event_type}:{snapshot.task_id}:{reminder_index}"
            result = await session.execute(
                sqlite_insert(NotificationOutbox)
                .values(
                    event_id=uuid4().hex,
                    event_type=snapshot.event_type,
                    resource_type="design_task",
                    resource_id=snapshot.task_id,
                    trace_id=uuid4().hex,
                    payload_json=json.dumps(
                        {"task_id": snapshot.task_id, "reminder_index": reminder_index},
                        separators=(",", ":"),
                    ),
                    status="pending",
                    attempt_no=0,
                    idempotency_key=key,
                    created_at=current,
                )
                .prefix_with("OR IGNORE")
            )
            if getattr(result, "rowcount", 0) != 1:
                continue
            snapshot.last_reminder_index = reminder_index
            if reminder_index >= snapshot.max_repeat_count:
                snapshot.active = False
                snapshot.stopped_reason = "repeat_limit_reached"
            else:
                snapshot.next_due_at = snapshot.next_due_at + timedelta(
                    hours=snapshot.repeat_interval_hours
                )
            snapshot.updated_at = current
            created += 1
        await session.flush()
        return created

    async def process_outbox(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
        limit: int = 50,
    ) -> int:
        current = now or datetime.now(UTC)
        claim_token = uuid4().hex
        claim_expires_at = current + timedelta(
            seconds=max(15, self._settings.lark_claim_lease_seconds)
        )
        eligible = (
            select(NotificationOutbox.event_id)
            .where(
                NotificationOutbox.event_type.in_(LARK_EVENTS),
                NotificationOutbox.status.in_(("pending", "retrying")),
                (
                    NotificationOutbox.next_attempt_at.is_(None)
                    | (NotificationOutbox.next_attempt_at <= current)
                ),
                (
                    NotificationOutbox.claimed_by.is_(None)
                    | (NotificationOutbox.claim_expires_at <= current)
                ),
            )
            .where(
                or_(
                    NotificationOutbox.event_type.not_in(TIMED_EVENTS),
                    select(DesignTask.id)
                    .join(Customer, Customer.id == DesignTask.customer_id)
                    .where(
                        DesignTask.id == NotificationOutbox.resource_id,
                        Customer.access_state == "active",
                        Customer.access_expires_at.is_not(None),
                        Customer.access_expires_at > current,
                    )
                    .exists(),
                )
            )
            .order_by(NotificationOutbox.created_at, NotificationOutbox.event_id)
            .limit(limit)
        )
        claimed_ids = list(
            (
                await session.scalars(
                    update(NotificationOutbox)
                    .where(NotificationOutbox.event_id.in_(eligible))
                    .values(claimed_by=claim_token, claim_expires_at=claim_expires_at)
                    .returning(NotificationOutbox.event_id)
                )
            ).all()
        )
        # The claim must be durable before any external POST can happen.
        await session.commit()
        if not claimed_ids:
            return 0
        rows = list(
            (
                await session.scalars(
                    select(NotificationOutbox)
                    .where(
                        NotificationOutbox.event_id.in_(claimed_ids),
                        NotificationOutbox.claimed_by == claim_token,
                    )
                    .order_by(NotificationOutbox.created_at, NotificationOutbox.event_id)
                )
            ).all()
        )
        processed = 0
        for outbox in rows:
            try:
                await self._process_one(session, outbox, current)
                outbox.claimed_by = None
                outbox.claim_expires_at = None
                await session.commit()
            except CustomerAccessUnavailableError:
                await session.rollback()
                await session.execute(
                    update(NotificationOutbox)
                    .where(
                        NotificationOutbox.event_id == outbox.event_id,
                        NotificationOutbox.claimed_by == claim_token,
                    )
                    .values(claimed_by=None, claim_expires_at=None)
                )
                await session.commit()
            except Exception:
                await session.rollback()
                await session.execute(
                    update(NotificationOutbox)
                    .where(
                        NotificationOutbox.event_id == outbox.event_id,
                        NotificationOutbox.claimed_by == claim_token,
                    )
                    .values(
                        status="retrying",
                        next_attempt_at=current + timedelta(seconds=2),
                        claimed_by=None,
                        claim_expires_at=None,
                    )
                )
                await session.commit()
            processed += 1
        return processed

    async def _process_one(
        self, session: AsyncSession, outbox: NotificationOutbox, now: datetime
    ) -> None:
        task = await session.get(DesignTask, outbox.resource_id)
        reminder_index = int(_safe_payload(outbox.payload_json).get("reminder_index", 0))
        delivery = await session.scalar(
            select(LarkNotificationDelivery).where(
                LarkNotificationDelivery.outbox_event_id == outbox.event_id
            )
        )
        if task is None or (
            outbox.event_type in EXPECTED_STATUS and task.status != EXPECTED_STATUS[outbox.event_type]
        ):
            outbox.status = "skipped"
            if delivery is not None:
                delivery.status = "failed"
                delivery.error_category = "invalid_task"
                delivery.last_attempt_at = now
            return
        if outbox.event_type in TIMED_EVENTS:
            customer = await session.get(Customer, task.customer_id)
            if customer is None or _customer_access_status(customer, now) != "active":
                raise CustomerAccessUnavailableError
        try:
            channel = await self._ready_channel(session)
            mention_all, mentions, elapsed_hours = await self._delivery_context(
                session, outbox.event_type, task.id, reminder_index
            )
            webhook, signing_secret = self._channel_secrets(channel)
            customer_name = await session.scalar(
                select(Customer.name).where(Customer.id == task.customer_id)
            )
            if customer_name is None:
                raise LarkNotificationError("task_not_found", "任务不存在", 404)
            title, subtitle_template = EVENT_COPY[outbox.event_type]
            subtitle = subtitle_template.format(elapsed_hours=elapsed_hours)
            card = build_lark_card(
                title=title,
                subtitle=subtitle,
                mention_all=mention_all,
                mentions=mentions,
                customer_name=customer_name,
                domain=task.domain,
                submitted_at=task.submitted_at,
                task_url=self._task_login_url(task.id),
            )
            attempt = await self._client.send(
                webhook, _with_signature(card, signing_secret, now)
            )
        except (LarkNotificationError, LarkSecretConfigurationError):
            mention_all = False
            mentions = []
            attempt = DeliveryAttempt(False, True, "configuration_unavailable")
        if delivery is None:
            delivery = LarkNotificationDelivery(
                id=uuid4().hex,
                outbox_event_id=outbox.event_id,
                event_type=outbox.event_type,
                task_id=task.id,
                reminder_index=reminder_index,
                notification_mode="group_only" if outbox.event_type == GROUP_ONLY_EVENT else "mention",
                mention_count=len(mentions) + int(mention_all),
                status="retrying",
                trace_id=outbox.trace_id,
                created_at=now,
            )
            session.add(delivery)
        outbox.attempt_no += 1
        delivery.attempt_count = outbox.attempt_no
        delivery.last_attempt_at = now
        delivery.error_category = attempt.error_category
        if attempt.accepted:
            outbox.status = "sent"
            outbox.next_attempt_at = None
            delivery.status = "accepted"
            delivery.accepted_at = now
            channel = await session.get(LarkChannelConfig, _CHANNEL_ID)
            if channel is not None:
                channel.last_success_at = now
            return
        if attempt.retryable and outbox.attempt_no < self._settings.lark_delivery_max_attempts:
            outbox.status = "retrying"
            outbox.next_attempt_at = now + timedelta(seconds=2 ** outbox.attempt_no)
            delivery.status = "retrying"
            return
        outbox.status = "failed"
        outbox.next_attempt_at = None
        delivery.status = "failed"

    async def _channel(self, session: AsyncSession) -> LarkChannelConfig:
        channel = await session.get(LarkChannelConfig, _CHANNEL_ID)
        if channel is None:
            channel = LarkChannelConfig(id=_CHANNEL_ID, enabled=False, signing_enabled=False)
            session.add(channel)
            await session.flush()
        return channel

    async def _ready_channel(self, session: AsyncSession) -> LarkChannelConfig:
        channel = await self._channel(session)
        if not channel.enabled or channel.webhook_ciphertext is None:
            raise LarkNotificationError("channel_not_ready", "Lark 通道尚未启用并完成配置", 409)
        if channel.signing_enabled and channel.signing_secret_ciphertext is None:
            raise LarkNotificationError("channel_not_ready", "Lark 签名配置不完整", 409)
        return channel

    def _channel_secrets(self, channel: LarkChannelConfig) -> tuple[str, str | None]:
        if channel.webhook_ciphertext is None:
            raise LarkNotificationError("channel_not_ready", "Lark 通道配置不完整", 409)
        webhook = self._secrets.decrypt(channel.webhook_ciphertext)
        signing = (
            self._secrets.decrypt(channel.signing_secret_ciphertext)
            if channel.signing_enabled and channel.signing_secret_ciphertext
            else None
        )
        return webhook, signing

    def _task_login_url(self, task_id: str) -> str:
        task_path = f"/admin/tasks?task_id={quote(task_id, safe='')}"
        return f"{self._admin_base_url}/admin/login?return_to={quote(task_path, safe='')}"

    async def _mention_targets(
        self, session: AsyncSession, recipient_ids: list[str]
    ) -> list[MentionTarget]:
        recipients = await _enabled_recipients(session, recipient_ids)
        by_id = {recipient.id: recipient for recipient in recipients}
        return [
            MentionTarget(
                id=recipient.id,
                display_name=recipient.display_name,
                open_id=self._secrets.decrypt(recipient.open_id_ciphertext),
                open_id_masked=recipient.open_id_masked,
            )
            for recipient_id in recipient_ids
            if (recipient := by_id.get(recipient_id)) is not None
        ]

    async def _delivery_context(
        self,
        session: AsyncSession,
        event_type: str,
        task_id: str,
        reminder_index: int,
    ) -> tuple[bool, list[MentionTarget], int | None]:
        if event_type == GROUP_ONLY_EVENT:
            return False, [], None
        if event_type in TIMED_EVENTS:
            snapshot = await session.scalar(
                select(LarkReminderSnapshot).where(
                    LarkReminderSnapshot.task_id == task_id,
                    LarkReminderSnapshot.event_type == event_type,
                )
            )
            if snapshot is None:
                raise LarkNotificationError("snapshot_missing", "任务提醒快照不存在", 409)
            if snapshot.mention_all:
                elapsed_hours = _reminder_elapsed_hours(
                    snapshot.threshold_hours,
                    snapshot.repeat_interval_hours,
                    reminder_index,
                )
                return True, [], elapsed_hours
            raw_targets = json.loads(snapshot.recipient_snapshot_json)
            mentions = [
                MentionTarget(
                    id=str(item["id"]),
                    display_name=item.get("display_name"),
                    open_id=self._secrets.decrypt(str(item["open_id_ciphertext"])),
                    open_id_masked=str(item["open_id_masked"]),
                )
                for item in raw_targets
            ]
            elapsed_hours = _reminder_elapsed_hours(
                snapshot.threshold_hours,
                snapshot.repeat_interval_hours,
                reminder_index,
            )
            return snapshot.mention_all, mentions, elapsed_hours
        rule = await session.get(LarkNotificationRule, event_type)
        if rule is None or not rule.enabled:
            raise LarkNotificationError("rule_disabled", "通知规则已停用", 409)
        if rule.mention_all:
            return True, [], None
        mentions = await self._mention_targets(session, _json_ids(rule.recipient_ids_json))
        if not rule.mention_all and not mentions:
            raise LarkNotificationError("recipient_unavailable", "通知规则没有有效通知目标", 409)
        return rule.mention_all, mentions, None

    async def _send_with_bounded_retries(
        self,
        webhook: str,
        payload: dict[str, Any],
        signing_secret: str | None,
        now: datetime,
    ) -> DeliveryAttempt:
        attempt = DeliveryAttempt(False, False, "provider_rejected")
        for _ in range(self._settings.lark_delivery_max_attempts):
            attempt = await self._client.send(webhook, _with_signature(payload, signing_secret, now))
            if attempt.accepted or not attempt.retryable:
                break
        return attempt


def build_lark_card(
    *,
    title: str,
    subtitle: str,
    mention_all: bool = False,
    mentions: list[MentionTarget],
    customer_name: str,
    domain: str,
    submitted_at: datetime,
    task_url: str,
) -> dict[str, Any]:
    """Compile only the seven confirmed card fields and one URL action."""

    mention_tokens = ["<at id=all></at>"] if mention_all else []
    seen_open_ids: set[str] = set()
    if not mention_all:
        for item in mentions:
            if item.open_id not in seen_open_ids:
                mention_tokens.append(f"<at id={item.open_id}></at>")
                seen_open_ids.add(item.open_id)
    mention_text = " ".join(mention_tokens) or "无（群通知）"
    content = (
        f"{subtitle}\n\n"
        f"**@人员：** {mention_text}\n"
        f"**客户名称：** {customer_name}\n"
        f"**域名：** {domain}\n"
        f"**提交时间：** {_as_utc(submitted_at).astimezone(_BEIJING_TZ).strftime('%Y-%m-%d %H:%M')}"
    )
    payload: dict[str, Any] = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": title},
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "type": "primary",
                            "text": {"tag": "plain_text", "content": "查看任务"},
                            "url": task_url,
                        }
                    ],
                },
            ],
        },
    }
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > _MAX_CARD_BYTES:
        raise LarkNotificationError("card_too_large", "Lark 卡片内容超过限制", 422)
    return payload


def _with_signature(
    payload: dict[str, Any], signing_secret: str | None, now: datetime
) -> dict[str, Any]:
    if signing_secret is None:
        return payload
    timestamp = str(int(now.timestamp()))
    string_to_sign = f"{timestamp}\n{signing_secret}".encode()
    signature = base64.b64encode(
        hmac.new(string_to_sign, digestmod=hashlib.sha256).digest()
    ).decode("ascii")
    return {"timestamp": timestamp, "sign": signature, **payload}


def _channel_dto(channel: LarkChannelConfig) -> LarkChannelDto:
    return LarkChannelDto(
        enabled=channel.enabled,
        group_label=channel.group_label,
        webhook_status="configured" if channel.webhook_ciphertext else "missing",
        signing_enabled=channel.signing_enabled,
        signing_secret_status="configured" if channel.signing_secret_ciphertext else "missing",
        last_test_status=cast(Any, channel.last_test_status),
        last_tested_at=channel.last_tested_at,
        last_success_at=channel.last_success_at,
        updated_at=channel.updated_at,
    )


def _recipient_dto(recipient: LarkRecipient) -> LarkRecipientDto:
    return LarkRecipientDto(
        id=recipient.id,
        display_name=recipient.display_name,
        open_id_masked=recipient.open_id_masked,
        enabled=recipient.enabled,
        updated_at=recipient.updated_at,
    )


def _rule_dto(rule: LarkNotificationRule) -> LarkNotificationRuleDto:
    return LarkNotificationRuleDto(
        event_type=cast(Any, rule.event_type),
        enabled=rule.enabled,
        mention_all=False if rule.event_type == GROUP_ONLY_EVENT else rule.mention_all,
        recipient_ids=[] if rule.event_type == GROUP_ONLY_EVENT else _json_ids(rule.recipient_ids_json),
        threshold_hours=rule.threshold_hours,
        repeat_interval_hours=rule.repeat_interval_hours,
        max_repeat_count=rule.max_repeat_count,
        updated_at=rule.updated_at,
    )


def _json_ids(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [item for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []


def _safe_payload(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _enabled_recipients(
    session: AsyncSession, recipient_ids: list[str]
) -> list[LarkRecipient]:
    if not recipient_ids:
        return []
    rows = list(
        (
            await session.scalars(
                select(LarkRecipient).where(
                    LarkRecipient.id.in_(recipient_ids), LarkRecipient.enabled.is_(True)
                )
            )
        ).all()
    )
    by_id = {row.id: row for row in rows}
    return [by_id[item] for item in recipient_ids if item in by_id]


async def _validate_enabled_rules(
    session: AsyncSession, *, disabled_recipient_id: str
) -> None:
    rules = list(
        (
            await session.scalars(
                select(LarkNotificationRule).where(
                    LarkNotificationRule.enabled.is_(True),
                    LarkNotificationRule.event_type != GROUP_ONLY_EVENT,
                )
            )
        ).all()
    )
    for rule in rules:
        remaining = [item for item in _json_ids(rule.recipient_ids_json) if item != disabled_recipient_id]
        if (
            disabled_recipient_id in _json_ids(rule.recipient_ids_json)
            and not rule.mention_all
            and not await _enabled_recipients(session, remaining)
        ):
            raise LarkNotificationError(
                "recipient_required_by_rule",
                "该人员是已启用规则的最后一名有效通知人员",
                409,
            )


async def _audit(
    session: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    actor_id: str,
    summary: dict[str, Any],
    trace_id: str | None = None,
) -> None:
    session.add(
        AuditEvent(
            event_id=uuid4().hex,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_id=actor_id,
            trace_id=trace_id or uuid4().hex,
            summary_json=json.dumps(summary, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        )
    )


def _mask_open_id(open_id: str) -> str:
    if len(open_id) <= 10:
        return f"{open_id[:3]}***{open_id[-2:]}"
    return f"{open_id[:6]}***{open_id[-4:]}"


def _validate_admin_base(value: str) -> str:
    parsed = urlsplit(value.rstrip("/"))
    local = parsed.hostname in {"127.0.0.1", "localhost"} and parsed.scheme == "http"
    if not ((parsed.scheme == "https" and parsed.netloc) or local):
        raise LarkSecretConfigurationError("Admin frontend base URL is invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LarkSecretConfigurationError("Admin frontend base URL is invalid")
    return value.rstrip("/")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
