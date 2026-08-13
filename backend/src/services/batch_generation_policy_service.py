"""Persistence orchestration for the internal batch image-to-image strategy."""

import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import (
    AssetRecord,
    BatchGenerationPolicyState,
    BatchGenerationPolicyVersion,
    BatchGenerationStyleRotationCursor,
    ModelConnection,
)
from src.models.batch_generation_policy import (
    BatchPolicyDataDto,
    BatchPolicyPayload,
    BatchPolicyVersionDto,
    BatchStyleDto,
    StrategyValidationErrorDto,
)
from src.services.batch_prompt_compiler import (
    BatchCompileContext,
    BatchTemplateCombination,
    rotate_complete_template_combinations,
    validate_batch_policy,
)
from src.services.event_service import EventService

_BATCH_SCENE = "batch_generation"


class BatchPolicyValidationError(RuntimeError):
    """A safe field-validation failure that leaves the active policy untouched."""

    def __init__(self, validation_errors: list[StrategyValidationErrorDto], error_code: str) -> None:
        super().__init__(error_code)
        self.validation_errors = validation_errors
        self.error_code = error_code


class BatchGenerationPolicyService:
    """Persist editor drafts separately while keeping runtime versions immutable."""

    def __init__(self, events: EventService | None = None) -> None:
        self._events = events or EventService()

    async def get_policy(self, session: AsyncSession) -> BatchPolicyDataDto:
        """Return the persisted draft and metadata for the active published snapshot."""

        active = await self._active_version(session)
        active_dto = self._version_dto(active) if active else None
        state = await session.get(BatchGenerationPolicyState, _BATCH_SCENE)
        draft = self._draft_from_state(state)
        if draft is None:
            draft = (
                BatchPolicyPayload(
                    model_connection_id=active_dto.model_connection_id,
                    styles=[style.model_copy(deep=True) for style in active_dto.styles_snapshot],
                )
                if active_dto
                else BatchPolicyPayload(model_connection_id="", styles=[])
            )
        return BatchPolicyDataDto(
            draft_seed=draft,
            last_published_at=active.published_at if active else None,
            draft_updated_at=state.draft_updated_at if state else None,
        )

    async def save_draft(
        self, session: AsyncSession, policy: BatchPolicyPayload, actor_id: str
    ) -> datetime:
        """Persist an incomplete editor payload without validating or activating it."""

        now = datetime.now(UTC)
        state = await session.get(BatchGenerationPolicyState, _BATCH_SCENE)
        if state is None:
            state = BatchGenerationPolicyState(scene=_BATCH_SCENE, updated_at=now)
            session.add(state)
        state.draft_payload_json = json.dumps(
            policy.model_dump(mode="json"), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        state.draft_updated_at = now
        state.updated_at = now
        await self._events.record_audit(
            session,
            action="batch_generation_policy.draft_saved",
            resource_type="batch_generation_policy_draft",
            resource_id=_BATCH_SCENE,
            actor_id=actor_id,
            trace_id=uuid4().hex,
            summary={"style_count": len(policy.styles)},
        )
        await session.flush()
        return now

    async def publish_draft(self, session: AsyncSession, actor_id: str) -> BatchPolicyVersionDto:
        """Validate and activate the last persisted draft, leaving the draft available for editing."""

        policy_data = await self.get_policy(session)
        return await self.publish(session, policy_data.draft_seed, actor_id)

    async def list_versions(self, session: AsyncSession) -> list[BatchPolicyVersionDto]:
        """List immutable batch snapshots newest first."""

        records = (
            await session.scalars(
                select(BatchGenerationPolicyVersion).order_by(BatchGenerationPolicyVersion.version.desc())
            )
        ).all()
        return [self._version_dto(record) for record in records]

    async def publish(
        self, session: AsyncSession, policy: BatchPolicyPayload, actor_id: str
    ) -> BatchPolicyVersionDto:
        """Validate, snapshot, activate, and audit a new version in one transaction."""

        context = await self._compile_context(session, policy)
        validation_errors = validate_batch_policy(policy, context)
        if validation_errors:
            raise BatchPolicyValidationError(
                validation_errors=validation_errors,
                error_code=(
                    "unknown_template_variable"
                    if any(error.code == "unknown_template_variable" for error in validation_errors)
                    else "policy_validation_failed"
                ),
            )

        next_version = (await session.scalar(select(func.max(BatchGenerationPolicyVersion.version)))) or 0
        now = datetime.now(UTC)
        record = BatchGenerationPolicyVersion(
            id=uuid4().hex,
            version=next_version + 1,
            model_connection_id=policy.model_connection_id,
            model_connection_version=context.model_connection_version or 0,
            styles_snapshot_json=json.dumps(
                [style.model_dump(mode="json") for style in policy.styles],
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            published_at=now,
        )
        session.add(record)
        await session.flush()

        state = await session.get(BatchGenerationPolicyState, _BATCH_SCENE)
        if state is None:
            state = BatchGenerationPolicyState(
                scene=_BATCH_SCENE,
                active_version_id=record.id,
                updated_at=now,
            )
            session.add(state)
        else:
            state.active_version_id = record.id
            state.updated_at = now
        for style in policy.styles:
            session.add(
                BatchGenerationStyleRotationCursor(
                    policy_version_id=record.id,
                    style_id=style.id,
                    next_template_offset=0,
                    updated_at=now,
                )
            )
        await self._events.record_audit(
            session,
            action="batch_generation_policy.published",
            resource_type="batch_generation_policy_version",
            resource_id=record.id,
            actor_id=actor_id,
            trace_id=uuid4().hex,
            summary={
                "version": record.version,
                "model_connection_id": record.model_connection_id,
                "style_count": len(policy.styles),
                "target_count": sum(style.generation_count for style in policy.styles),
            },
        )
        await session.flush()
        return self._version_dto(record)

    @staticmethod
    def _draft_from_state(state: BatchGenerationPolicyState | None) -> BatchPolicyPayload | None:
        if state is None or not state.draft_payload_json:
            return None
        try:
            return BatchPolicyPayload.model_validate_json(state.draft_payload_json)
        except ValueError:
            return None

    async def allocate_rotation_combinations(
        self, session: AsyncSession, version_id: str
    ) -> list[BatchTemplateCombination]:
        """Advance only each style's own cursor while retaining template/reference pairs."""

        record = await session.get(BatchGenerationPolicyVersion, version_id)
        if record is None:
            raise LookupError("Batch generation policy version not found")
        styles = self._styles_snapshot(record)
        cursor_records: list[BatchGenerationStyleRotationCursor] = list(
            (
                await session.scalars(
                    select(BatchGenerationStyleRotationCursor).where(
                        BatchGenerationStyleRotationCursor.policy_version_id == record.id
                    )
                )
            ).all()
        )
        cursors = {item.style_id: item.next_template_offset for item in cursor_records}
        combinations: list[BatchTemplateCombination]
        next_cursors: dict[str, int]
        combinations, next_cursors = rotate_complete_template_combinations(styles, cursors)
        now = datetime.now(UTC)
        rows_by_style = {item.style_id: item for item in cursor_records}
        for style_id, offset in next_cursors.items():
            row = rows_by_style.get(style_id)
            if row is None:
                session.add(
                    BatchGenerationStyleRotationCursor(
                        policy_version_id=record.id,
                        style_id=style_id,
                        next_template_offset=offset,
                        updated_at=now,
                    )
                )
            else:
                row.next_template_offset = offset
                row.updated_at = now
        await session.flush()
        return combinations

    async def allocate_replenishment_combination(
        self, session: AsyncSession, version_id: str, style_id: str
    ) -> BatchTemplateCombination:
        """Advance only one failed style when a bounded replacement is needed."""

        record = await session.get(BatchGenerationPolicyVersion, version_id)
        if record is None:
            raise LookupError("Batch generation policy version not found")
        style = next((item for item in self._styles_snapshot(record) if item.id == style_id), None)
        if style is None:
            raise LookupError("Batch generation policy style not found")
        complete_templates = [
            template
            for template in style.templates
            if template.name.strip()
            and template.positive_prompt.strip()
            and "域名" in _template_variable_names(template.positive_prompt)
        ]
        if not complete_templates:
            raise LookupError("Batch generation policy style has no complete template")
        cursor = await session.get(
            BatchGenerationStyleRotationCursor,
            {"policy_version_id": record.id, "style_id": style.id},
        )
        now = datetime.now(UTC)
        offset = (cursor.next_template_offset if cursor else 0) % len(complete_templates)
        template = complete_templates[offset]
        next_offset = (offset + 1) % len(complete_templates)
        if cursor is None:
            session.add(
                BatchGenerationStyleRotationCursor(
                    policy_version_id=record.id,
                    style_id=style.id,
                    next_template_offset=next_offset,
                    updated_at=now,
                )
            )
        else:
            cursor.next_template_offset = next_offset
            cursor.updated_at = now
        await session.flush()
        return BatchTemplateCombination(
            style_id=style.id,
            template_id=template.id,
            reference_image_asset_ids=tuple(template.reference_images),
        )

    async def _active_version(self, session: AsyncSession) -> BatchGenerationPolicyVersion | None:
        state = await session.get(BatchGenerationPolicyState, _BATCH_SCENE)
        if state is None or state.active_version_id is None:
            return None
        return await session.get(BatchGenerationPolicyVersion, state.active_version_id)

    async def _compile_context(
        self, session: AsyncSession, policy: BatchPolicyPayload
    ) -> BatchCompileContext:
        connection = await session.get(ModelConnection, policy.model_connection_id) if policy.model_connection_id else None
        if connection is not None and connection.retired_at is not None:
            connection = None
        asset_ids = {
            asset_id
            for style in policy.styles
            for template in style.templates
            for asset_id in template.reference_images
        }
        records: list[AssetRecord] = []
        if asset_ids:
            records = list(
                (
                    await session.scalars(
                        select(AssetRecord).where(
                            AssetRecord.asset_id.in_(asset_ids),
                            AssetRecord.purpose == "model_strategy_reference",
                        )
                    )
                )
                .all()
            )
        assets = {record.asset_id: record for record in records}
        return BatchCompileContext(
            model_connection_id=connection.id if connection else None,
            model_connection_version=connection.version if connection else None,
            image_to_image_verified=_has_verified_image_to_image(connection),
            assets=assets,
        )

    @staticmethod
    def _styles_snapshot(record: BatchGenerationPolicyVersion) -> list[BatchStyleDto]:
        return [
            BatchStyleDto.model_validate(_migrate_legacy_style_snapshot(item))
            for item in json.loads(record.styles_snapshot_json)
        ]

    def _version_dto(self, record: BatchGenerationPolicyVersion) -> BatchPolicyVersionDto:
        return BatchPolicyVersionDto(
            id=record.id,
            version=record.version,
            model_connection_id=record.model_connection_id,
            styles_snapshot=self._styles_snapshot(record),
            published_at=record.published_at,
        )


def _has_verified_image_to_image(connection: ModelConnection | None) -> bool:
    """Read only the verified capability flag stored by the controlled connection test."""

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


def _template_variable_names(value: str) -> list[str]:
    """Read template variables without extending the public compiler API."""

    return [match.group(1).strip() for match in re.finditer(r"{{\s*([^{}]+?)\s*}}", value)]


def _migrate_legacy_style_snapshot(value: object) -> object:
    """Map the pre-migration single-reference field while reading stored JSON only."""

    if not isinstance(value, dict):
        return value
    style = dict(value)
    templates = style.get("templates")
    if not isinstance(templates, list):
        return style
    normalized_templates: list[object] = []
    for template in templates:
        if not isinstance(template, dict):
            normalized_templates.append(template)
            continue
        normalized = dict(template)
        legacy_reference = normalized.pop("reference_image_asset_id", None)
        if "reference_images" not in normalized:
            normalized["reference_images"] = [legacy_reference] if legacy_reference else []
        normalized_templates.append(normalized)
    style["templates"] = normalized_templates
    return style
