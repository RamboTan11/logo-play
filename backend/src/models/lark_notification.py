"""Safe DTOs for the fixed-group Lark notification module."""

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

LarkEventType = Literal[
    "task.adoption_submitted",
    "task.waiting_assignment_overdue",
    "task.upload_overdue",
    "task.adoption_changed_before_acceptance",
    "task.adoption_changed_in_progress",
    "task.delivery_uploaded",
    "task.customer_feedback_submitted",
]
LARK_EVENT_TYPES: tuple[LarkEventType, ...] = (
    "task.adoption_submitted",
    "task.waiting_assignment_overdue",
    "task.upload_overdue",
    "task.adoption_changed_before_acceptance",
    "task.adoption_changed_in_progress",
    "task.delivery_uploaded",
    "task.customer_feedback_submitted",
)
DeliveryStatus = Literal["accepted", "retrying", "failed"]

TIMED_EVENTS = {"task.waiting_assignment_overdue", "task.upload_overdue"}
GROUP_ONLY_EVENT = "task.delivery_uploaded"


class LarkChannelDto(BaseModel):
    enabled: bool
    group_label: str | None
    webhook_status: Literal["configured", "missing"]
    signing_enabled: bool
    signing_secret_status: Literal["configured", "missing"]
    last_test_status: DeliveryStatus | None
    last_tested_at: datetime | None
    last_success_at: datetime | None
    updated_at: datetime


class LarkChannelUpdate(BaseModel):
    enabled: bool
    group_label: str | None = Field(default=None, max_length=120)
    webhook: str | None = Field(default=None, max_length=2048)
    signing_enabled: bool
    signing_secret: str | None = Field(default=None, max_length=4096)

    @field_validator("group_label", "webhook", "signing_secret")
    @classmethod
    def trim_optional(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("webhook")
    @classmethod
    def validate_webhook(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        local = parsed.hostname in {"127.0.0.1", "localhost"} and parsed.scheme == "http"
        official = parsed.scheme == "https" and parsed.hostname == "open.larksuite.com"
        if not (local or official) or not parsed.path.startswith("/open-apis/bot/v2/hook/"):
            raise ValueError("Webhook must be an international Lark custom-bot URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Webhook must not contain credentials, query, or fragment")
        return value


class LarkTestRequest(BaseModel):
    mention_enabled: bool = False
    recipient_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_mentions(self) -> "LarkTestRequest":
        if not self.mention_enabled and self.recipient_ids:
            raise ValueError("Recipients require mention_enabled")
        if len(self.recipient_ids) != len(set(self.recipient_ids)):
            raise ValueError("Recipients must be unique")
        return self


class LarkTestResultDto(BaseModel):
    accepted: bool
    status: DeliveryStatus
    tested_at: datetime
    trace_id: str


class LarkRecipientDto(BaseModel):
    id: str
    display_name: str | None
    open_id_masked: str
    enabled: bool
    updated_at: datetime


class LarkRecipientCreate(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    open_id: str = Field(min_length=6, max_length=128, pattern=r"^ou_[A-Za-z0-9_-]+$")
    enabled: bool = True

    @field_validator("display_name", "open_id")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class LarkRecipientUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    open_id: str | None = Field(default=None, max_length=128, pattern=r"^ou_[A-Za-z0-9_-]+$")
    enabled: bool | None = None

    @field_validator("display_name", "open_id")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class LarkNotificationRuleDto(BaseModel):
    event_type: LarkEventType
    enabled: bool
    mention_all: bool
    recipient_ids: list[str]
    threshold_hours: int | None
    repeat_interval_hours: int | None
    max_repeat_count: int | None
    updated_at: datetime


class LarkNotificationRuleUpdate(BaseModel):
    enabled: bool
    mention_all: bool = False
    recipient_ids: list[str] = Field(default_factory=list, max_length=100)
    threshold_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    repeat_interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    max_repeat_count: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def unique_recipients(self) -> "LarkNotificationRuleUpdate":
        if len(self.recipient_ids) != len(set(self.recipient_ids)):
            raise ValueError("Recipients must be unique")
        return self


class LarkNotificationRuleBatchItem(LarkNotificationRuleUpdate):
    event_type: LarkEventType


class LarkNotificationRuleBatchUpdate(BaseModel):
    rules: list[LarkNotificationRuleBatchItem] = Field(
        min_length=len(LARK_EVENT_TYPES), max_length=len(LARK_EVENT_TYPES)
    )

    @model_validator(mode="after")
    def complete_unique_event_set(self) -> "LarkNotificationRuleBatchUpdate":
        event_types = [rule.event_type for rule in self.rules]
        if len(event_types) != len(set(event_types)) or set(event_types) != set(LARK_EVENT_TYPES):
            raise ValueError("Rules must contain each supported event exactly once")
        return self


class LarkRecentDeliveryDto(BaseModel):
    id: str
    created_at: datetime
    event_type: str
    task_id: str | None
    task_url: str | None
    notification_mode: Literal["mention", "group_only"]
    reminder_index: int
    status: DeliveryStatus
    error_summary: str | None


class LarkRecentDeliveryListDto(BaseModel):
    items: list[LarkRecentDeliveryDto]
