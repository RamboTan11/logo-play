"""Persistence orchestration for the internal single-image editing strategy."""

import json
from contextlib import suppress
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import (
    ModelConnection,
    SingleImageEditPolicyState,
    SingleImageEditPolicyVersion,
)
from src.models.batch_generation_policy import StrategyValidationErrorDto
from src.models.single_image_edit_policy import (
    SingleImageEditPolicyDataDto,
    SingleImageEditPolicyPayload,
    SingleImageEditPolicyVersionDto,
)
from src.services.event_service import EventService
from src.services.single_image_edit_prompt_compiler import (
    SINGLE_EDIT_RULE_BLOCKS,
    SINGLE_IMAGE_EDIT_PROMPT_COMPILER_VERSION,
    SINGLE_IMAGE_EDIT_RULE_SET_VERSION,
    SingleImageEditCompileContext,
    validate_single_image_edit_policy,
)

_SINGLE_IMAGE_EDIT_SCENE = "single_image_edit"


class SingleImageEditPolicyValidationError(RuntimeError):
    """A safe validation failure that leaves the active version unchanged."""

    def __init__(self, validation_errors: list[StrategyValidationErrorDto], error_code: str) -> None:
        super().__init__(error_code)
        self.validation_errors = validation_errors
        self.error_code = error_code


class SingleImageEditPolicyUpgradeRequiredError(RuntimeError):
    """An active legacy policy cannot be converted without guessing at its meaning."""


class SingleImageEditPolicyService:
    """Keep drafts browser-local while published single-edit versions remain append-only."""

    def __init__(self, events: EventService | None = None) -> None:
        self._events = events or EventService()

    async def get_policy(self, session: AsyncSession) -> SingleImageEditPolicyDataDto:
        """Return the current single-edit snapshot and an independent draft seed."""

        with suppress(SingleImageEditPolicyUpgradeRequiredError):
            # The admin page can still inspect the immutable legacy snapshot.
            await self.ensure_active_upgrade(session)
        active = await self._active_version(session)
        active_dto = self._version_dto(active) if active else None
        return SingleImageEditPolicyDataDto(
            draft_seed=(
                SingleImageEditPolicyPayload(
                    model_connection_id=active_dto.model_connection_id,
                    positive_content=active_dto.positive_content,
                    negative_avoidance=active_dto.negative_avoidance,
                )
                if active_dto
                else SingleImageEditPolicyPayload()
            ),
        )

    async def list_versions(self, session: AsyncSession) -> list[SingleImageEditPolicyVersionDto]:
        """List immutable single-edit snapshots newest first."""

        with suppress(SingleImageEditPolicyUpgradeRequiredError):
            # The admin page can still inspect the immutable legacy snapshot.
            await self.ensure_active_upgrade(session)
        records = (
            await session.scalars(
                select(SingleImageEditPolicyVersion).order_by(
                    SingleImageEditPolicyVersion.version.desc()
                )
            )
        ).all()
        return [self._version_dto(record) for record in records]

    async def publish(
        self,
        session: AsyncSession,
        policy: SingleImageEditPolicyPayload,
        actor_id: str,
    ) -> SingleImageEditPolicyVersionDto:
        """Validate, snapshot, activate, and audit one single-image strategy atomically."""

        context = await self._compile_context(session, policy)
        validation_errors = validate_single_image_edit_policy(policy, context)
        if validation_errors:
            raise SingleImageEditPolicyValidationError(
                validation_errors=validation_errors,
                error_code=(
                    "unknown_template_variable"
                    if any(error.code == "unknown_template_variable" for error in validation_errors)
                    else "policy_validation_failed"
                ),
            )

        next_version = (
            await session.scalar(select(func.max(SingleImageEditPolicyVersion.version)))
        ) or 0
        now = datetime.now(UTC)
        record = SingleImageEditPolicyVersion(
            id=uuid4().hex,
            version=next_version + 1,
            model_connection_id=policy.model_connection_id,
            model_connection_version=context.model_connection_version or 0,
            positive_content=policy.positive_content,
            user_description_template="",
            negative_avoidance=policy.negative_avoidance,
            compiler_version=SINGLE_IMAGE_EDIT_PROMPT_COMPILER_VERSION,
            rule_set_version=SINGLE_IMAGE_EDIT_RULE_SET_VERSION,
            rule_blocks_json=json.dumps(dict(SINGLE_EDIT_RULE_BLOCKS), ensure_ascii=True),
            published_at=now,
        )
        session.add(record)
        await session.flush()

        state = await session.get(SingleImageEditPolicyState, _SINGLE_IMAGE_EDIT_SCENE)
        if state is None:
            state = SingleImageEditPolicyState(
                scene=_SINGLE_IMAGE_EDIT_SCENE,
                active_version_id=record.id,
                updated_at=now,
            )
            session.add(state)
        else:
            state.active_version_id = record.id
            state.updated_at = now
        await self._events.record_audit(
            session,
            action="single_image_edit_policy.published",
            resource_type="single_image_edit_policy_version",
            resource_id=record.id,
            actor_id=actor_id,
            trace_id=uuid4().hex,
            summary={
                "version": record.version,
                "model_connection_id": record.model_connection_id,
                "has_negative_avoidance": bool(record.negative_avoidance.strip()),
            },
        )
        await session.flush()
        return self._version_dto(record)

    async def ensure_active_upgrade(self, session: AsyncSession) -> None:
        """Migrate one legacy active policy through an immutable, idempotent successor."""

        active = await self._active_version(session)
        if active is None or active.compiler_version == SINGLE_IMAGE_EDIT_PROMPT_COMPILER_VERSION:
            return
        legacy = _effective_positive_content(active)
        legacy_count = legacy.count("{{用户补充描述}}")
        if "{{用户修改指令}}" in legacy or legacy_count == 0:
            raise SingleImageEditPolicyUpgradeRequiredError(
                "single_edit_policy_upgrade_required"
            )
        if legacy_count != 1:
            raise SingleImageEditPolicyUpgradeRequiredError(
                "single_edit_policy_upgrade_required"
            )
        next_version = (await session.scalar(select(func.max(SingleImageEditPolicyVersion.version)))) or 0
        now = datetime.now(UTC)
        successor = SingleImageEditPolicyVersion(
            id=uuid4().hex,
            version=next_version + 1,
            model_connection_id=active.model_connection_id,
            model_connection_version=active.model_connection_version,
            positive_content=legacy.replace("{{用户补充描述}}", "{{用户修改指令}}"),
            user_description_template="",
            negative_avoidance=active.negative_avoidance,
            compiler_version=SINGLE_IMAGE_EDIT_PROMPT_COMPILER_VERSION,
            rule_set_version=SINGLE_IMAGE_EDIT_RULE_SET_VERSION,
            rule_blocks_json=json.dumps(dict(SINGLE_EDIT_RULE_BLOCKS), ensure_ascii=True),
            published_at=now,
        )
        session.add(successor)
        await session.flush()
        state = await session.get(SingleImageEditPolicyState, _SINGLE_IMAGE_EDIT_SCENE)
        if state is not None:
            state.active_version_id = successor.id
            state.updated_at = now
        await self._events.record_audit(
            session,
            action="single_image_edit_policy.upgraded",
            resource_type="single_image_edit_policy_version",
            resource_id=successor.id,
            actor_id=None,
            trace_id=uuid4().hex,
            summary={"from_version": active.version, "to_version": successor.version},
        )
        await session.flush()

    async def _active_version(
        self, session: AsyncSession
    ) -> SingleImageEditPolicyVersion | None:
        state = await session.get(SingleImageEditPolicyState, _SINGLE_IMAGE_EDIT_SCENE)
        if state is None or state.active_version_id is None:
            return None
        return await session.get(SingleImageEditPolicyVersion, state.active_version_id)

    async def _compile_context(
        self, session: AsyncSession, policy: SingleImageEditPolicyPayload
    ) -> SingleImageEditCompileContext:
        connection = (
            await session.get(ModelConnection, policy.model_connection_id)
            if policy.model_connection_id
            else None
        )
        if connection is not None and connection.retired_at is not None:
            connection = None
        return SingleImageEditCompileContext(
            model_connection_id=connection.id if connection else None,
            model_connection_version=connection.version if connection else None,
            image_to_image_verified=_has_verified_image_to_image(connection),
        )

    @staticmethod
    def _version_dto(
        record: SingleImageEditPolicyVersion,
    ) -> SingleImageEditPolicyVersionDto:
        return SingleImageEditPolicyVersionDto(
            id=record.id,
            version=record.version,
            model_connection_id=record.model_connection_id,
            positive_content=_effective_positive_content(record),
            negative_avoidance=record.negative_avoidance,
            published_at=record.published_at,
            compiler_contract=(
                {
                    "compiler_version": record.compiler_version,
                    "rule_set_version": record.rule_set_version,
                    "rule_block_names": list(json.loads(record.rule_blocks_json or "[]")),
                }
                if record.compiler_version == SINGLE_IMAGE_EDIT_PROMPT_COMPILER_VERSION
                else None
            ),
        )


def _has_verified_image_to_image(connection: ModelConnection | None) -> bool:
    """Read only the capability flag produced by the controlled connection test."""

    if connection is None:
        return False
    try:
        capabilities = json.loads(connection.verified_capabilities_json)
    except (TypeError, ValueError):
        return False
    return any(
        isinstance(item, dict)
        and item.get("capability") == "image_to_image"
        and item.get("verified") is True
        for item in capabilities
    )


def _effective_positive_content(record: SingleImageEditPolicyVersion) -> str:
    """Expose legacy snapshots through the current positive-content-only contract."""

    positive_content = str(record.positive_content)
    if "{{用户补充描述}}" in positive_content:
        return positive_content
    legacy_template = str(record.user_description_template).strip()
    if not legacy_template:
        return positive_content
    return f"{positive_content.rstrip()}\n{legacy_template}"
