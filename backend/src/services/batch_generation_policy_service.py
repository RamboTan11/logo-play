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
    GenerationStyleCatalogDto,
    GenerationStyleCatalogStyleDto,
    GenerationStyleShowcaseImageDto,
    StrategyValidationErrorDto,
)
from src.services.asset_service import BATCH_STYLE_SHOWCASE_PURPOSE
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


class BatchStyleSelectionError(RuntimeError):
    """A customer-safe rejection for a stale or malformed style selection."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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
        validation_errors.extend(await self._validate_showcase_assets(session, policy))
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
        self, session: AsyncSession, version_id: str, selected_style_ids: list[str] | None = None
    ) -> tuple[list[BatchTemplateCombination], dict[str, int]]:
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
        allocation = await self._style_allocation(session, styles, selected_style_ids or [])
        combinations: list[BatchTemplateCombination]
        next_cursors: dict[str, int]
        combinations, next_cursors = rotate_complete_template_combinations(styles, cursors, allocation)
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
        return combinations, allocation

    async def get_customer_style_catalog(
        self, session: AsyncSession
    ) -> GenerationStyleCatalogDto:
        """Return only complete, published customer-facing style metadata."""

        record = await self._active_version(session)
        if record is None:
            return GenerationStyleCatalogDto(policy_version_id="", styles=[])
        styles = self._styles_snapshot(record)
        catalog_styles = await self._catalog_styles(session, styles)
        return GenerationStyleCatalogDto(policy_version_id=record.id, styles=catalog_styles)

    async def has_customer_showcase_image(
        self, session: AsyncSession, style_id: str, asset_id: str
    ) -> bool:
        """Check active catalog membership before serving protected preview bytes."""

        catalog = await self.get_customer_style_catalog(session)
        return any(
            style.id == style_id
            and any(image.asset_id == asset_id for image in style.showcase_images)
            for style in catalog.styles
        )

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

    async def _style_allocation(
        self,
        session: AsyncSession,
        styles: list[BatchStyleDto],
        selected_style_ids: list[str],
    ) -> dict[str, int]:
        """Allocate default counts or selected-style quotas with stable largest remainder."""

        enabled = [style for style in styles if style.generation_count > 0 and _has_complete_template(style)]
        if not selected_style_ids:
            return {style.id: style.generation_count for style in enabled}
        if len(set(selected_style_ids)) != len(selected_style_ids):
            raise BatchStyleSelectionError("duplicate_selected_style", "风格选择不能重复")
        total_count = sum(style.generation_count for style in enabled)
        if len(selected_style_ids) > total_count:
            raise BatchStyleSelectionError(
                "selected_style_count_exceeds_target", "选择的风格数量不能超过本批生成数量"
            )
        catalog_ids = {style.id for style in await self._catalog_styles(session, styles)}
        by_id = {style.id: style for style in enabled}
        invalid = [style_id for style_id in selected_style_ids if style_id not in catalog_ids or style_id not in by_id]
        if invalid:
            raise BatchStyleSelectionError("selected_style_unavailable", "所选风格已失效，请刷新后重试")
        selected = [style for style in enabled if style.id in set(selected_style_ids)]
        remaining = total_count - len(selected)
        weight_total = sum(style.generation_count for style in selected)
        floor_counts: dict[str, int] = {}
        remainders: list[tuple[int, int, str]] = []
        for order, style in enumerate(selected):
            numerator = remaining * style.generation_count
            floor_counts[style.id] = numerator // weight_total
            remainders.append((numerator % weight_total, order, style.id))
        extra = remaining - sum(floor_counts.values())
        for _, _, style_id in sorted(remainders, key=lambda item: (-item[0], item[1]))[:extra]:
            floor_counts[style_id] += 1
        return {style.id: 1 + floor_counts[style.id] for style in selected}

    async def _catalog_styles(
        self, session: AsyncSession, styles: list[BatchStyleDto]
    ) -> list[GenerationStyleCatalogStyleDto]:
        """Filter immutable snapshots into customer-safe styles without template leakage."""

        all_ids = [asset_id for style in styles for asset_id in style.showcase_image_asset_ids]
        records: dict[str, AssetRecord] = {}
        if all_ids:
            rows = list(
                (
                    await session.scalars(
                        select(AssetRecord).where(
                            AssetRecord.asset_id.in_(set(all_ids)),
                            AssetRecord.purpose == BATCH_STYLE_SHOWCASE_PURPOSE,
                        )
                    )
                ).all()
            )
            records = {row.asset_id: row for row in rows}
        catalog: list[GenerationStyleCatalogStyleDto] = []
        for style in styles:
            asset_ids = style.showcase_image_asset_ids
            if (
                style.generation_count <= 0
                or not style.description.strip()
                or not 1 <= len(asset_ids) <= 3
                or len(set(asset_ids)) != len(asset_ids)
                or any(asset_id not in records for asset_id in asset_ids)
                or not _has_complete_template(style)
            ):
                continue
            catalog.append(
                GenerationStyleCatalogStyleDto(
                    id=style.id,
                    name=style.name,
                    description=style.description,
                    showcase_images=[
                        GenerationStyleShowcaseImageDto(
                            asset_id=asset_id,
                            content_url=(
                                f"/api/v1/generation-style-catalog/styles/{style.id}"
                                f"/showcase-images/{asset_id}/content"
                            ),
                            filename=(records[asset_id].original_filename or "").strip(),
                        )
                        for asset_id in asset_ids
                    ],
                )
            )
        return catalog

    async def _validate_showcase_assets(
        self, session: AsyncSession, policy: BatchPolicyPayload
    ) -> list[StrategyValidationErrorDto]:
        """Validate preview metadata separately from provider template references."""

        referenced_ids = {
            asset_id for style in policy.styles for asset_id in style.showcase_image_asset_ids
        }
        records: set[str] = set()
        if referenced_ids:
            records = set(
                (
                    await session.scalars(
                        select(AssetRecord.asset_id).where(
                            AssetRecord.asset_id.in_(referenced_ids),
                            AssetRecord.purpose == BATCH_STYLE_SHOWCASE_PURPOSE,
                        )
                    )
                ).all()
            )
        errors: list[StrategyValidationErrorDto] = []
        for index, style in enumerate(policy.styles):
            if style.generation_count <= 0:
                continue
            prefix = f"styles[{index}]"
            if not style.description.strip():
                errors.append(
                    StrategyValidationErrorDto(
                        field=f"{prefix}.description", code="required", message="请填写客户简介"
                    )
                )
            image_ids = style.showcase_image_asset_ids
            if not 1 <= len(image_ids) <= 3:
                errors.append(
                    StrategyValidationErrorDto(
                        field=f"{prefix}.showcase_image_asset_ids",
                        code="invalid_showcase_image",
                        message="请上传 1 至 3 张客户展示样图",
                    )
                )
            elif len(set(image_ids)) != len(image_ids):
                errors.append(
                    StrategyValidationErrorDto(
                        field=f"{prefix}.showcase_image_asset_ids",
                        code="invalid_showcase_image",
                        message="客户展示样图不能重复",
                    )
                )
            else:
                for image_index, asset_id in enumerate(image_ids):
                    if asset_id not in records:
                        errors.append(
                            StrategyValidationErrorDto(
                                field=f"{prefix}.showcase_image_asset_ids[{image_index}]",
                                code="invalid_showcase_image",
                                message="客户展示样图无效，请重新上传",
                            )
                        )
        return errors


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
    style.setdefault("description", "")
    style.setdefault("showcase_image_asset_ids", [])
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


def _has_complete_template(style: BatchStyleDto) -> bool:
    """Keep catalog and selection eligibility aligned with runtime rotation."""

    return any(
        template.name.strip()
        and template.positive_prompt.strip()
        and _template_variable_names(template.positive_prompt).count("域名") == 1
        and _template_variable_names(template.positive_prompt).count("用户参考要求") <= 1
        and all(
            variable in {"域名", "用户参考要求"}
            for variable in _template_variable_names(template.positive_prompt)
            + _template_variable_names(template.negative_prompt or "")
        )
        for template in style.templates
    )
