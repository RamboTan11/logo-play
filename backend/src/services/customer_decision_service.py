"""Persistent, customer-isolated saved Logo and adoption workflows."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import (
    AssetRecord,
    DesignTask,
    EndpointIdempotencyRecord,
    LogoVersion,
    SavedLogo,
    SingleImageEditRequest,
)
from src.models.customer_decision import (
    DesignTaskDetailDto,
    DesignTaskDetailResponseDto,
    DesignTaskListDto,
    DesignTaskMutationDto,
    DesignTaskSummaryDto,
    SavedLogoDto,
    SavedLogoListDto,
    SavedLogoMutationDto,
)
from src.services.asset_service import AssetService, LocalFallbackAssetStorage
from src.services.batch_prompt_compiler import normalize_domain
from src.services.event_service import EventService
from src.services.lark_notification_service import LarkWorkflowService

_SAVE_ENDPOINT = "POST /api/v1/saved-logos"
_ADOPT_ENDPOINT = "POST /api/v1/design-tasks/adopt"


class CustomerDecisionError(RuntimeError):
    """A stable customer-safe decision failure."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """A replayable endpoint result committed in the caller's transaction."""

    status_code: int
    data: dict[str, Any] | None = None
    error_code: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class AdoptionSnapshot:
    adopted_version: LogoVersion
    adopted_asset: AssetRecord
    root_version: LogoVersion
    root_asset: AssetRecord
    ai_edit_inputs: list[str]


class CustomerDecisionService:
    """Coordinate decision writes, immutable snapshots, and protected reads."""

    def __init__(
        self,
        asset_root: str,
        events: EventService | None = None,
    ) -> None:
        event_service = events or EventService()
        self._assets = AssetService(LocalFallbackAssetStorage(asset_root), event_service)
        self._events = event_service
        self._lark = LarkWorkflowService(event_service)

    async def save_logo(
        self,
        session: AsyncSession,
        *,
        customer_id: str,
        logo_version_id: str,
        idempotency_key: str,
    ) -> DecisionResult:
        key = _normalize_idempotency_key(idempotency_key)
        request_hash = _request_hash({"logo_version_id": logo_version_id})
        replay = await self._replay(session, customer_id, _SAVE_ENDPOINT, key, request_hash)
        if replay is not None:
            return replay

        logo = await self._owned_logo(session, customer_id, logo_version_id)
        if logo is None:
            return await self._store_error(
                session,
                customer_id=customer_id,
                endpoint=_SAVE_ENDPOINT,
                key=key,
                request_hash=request_hash,
                code="logo_version_not_found",
                message="Logo version not found",
                status_code=404,
            )

        saved = await session.scalar(
            select(SavedLogo).where(
                SavedLogo.customer_id == customer_id,
                SavedLogo.logo_version_id == logo.id,
            )
        )
        created = saved is None
        if saved is None:
            saved = SavedLogo(
                id=uuid4().hex,
                customer_id=customer_id,
                logo_version_id=logo.id,
                saved_at=datetime.now(UTC),
            )
            session.add(saved)
            await self._events.record_audit(
                session,
                action="saved_logo.created",
                resource_type="saved_logo",
                resource_id=saved.id,
                actor_id=customer_id,
                trace_id=uuid4().hex,
                summary={"logo_version_id": logo.id},
            )

        data = SavedLogoMutationDto(
            saved_logo=self._saved_logo_dto(saved, logo),
            created=created,
        ).model_dump(mode="json")
        return await self._store_success(
            session,
            customer_id=customer_id,
            endpoint=_SAVE_ENDPOINT,
            key=key,
            request_hash=request_hash,
            status_code=201 if created else 200,
            data=data,
        )

    async def adopt_logo(
        self,
        session: AsyncSession,
        *,
        customer_id: str,
        logo_version_id: str,
        adoption_suggestion: str | None,
        confirm_replace_active_task: bool,
        idempotency_key: str,
    ) -> DecisionResult:
        key = _normalize_idempotency_key(idempotency_key)
        normalized_suggestion = _normalize_optional_text(adoption_suggestion)
        request_hash = _request_hash(
            {
                "logo_version_id": logo_version_id,
                "adoption_suggestion": normalized_suggestion,
                "confirm_replace_active_task": confirm_replace_active_task,
            }
        )
        replay = await self._replay(session, customer_id, _ADOPT_ENDPOINT, key, request_hash)
        if replay is not None:
            return replay

        logo = await self._owned_logo(session, customer_id, logo_version_id)
        if logo is None:
            return await self._store_error(
                session,
                customer_id=customer_id,
                endpoint=_ADOPT_ENDPOINT,
                key=key,
                request_hash=request_hash,
                code="logo_version_not_found",
                message="Logo version not found",
                status_code=404,
            )
        domain = normalize_domain(logo.domain)
        if domain is None:
            return await self._store_error(
                session,
                customer_id=customer_id,
                endpoint=_ADOPT_ENDPOINT,
                key=key,
                request_hash=request_hash,
                code="logo_version_not_found",
                message="Logo version not found",
                status_code=404,
            )

        completed = await session.scalar(
            select(DesignTask.id)
            .where(
                DesignTask.customer_id == customer_id,
                DesignTask.status == "completed",
            )
            .limit(1)
        )
        if completed is not None:
            return await self._store_error(
                session,
                customer_id=customer_id,
                endpoint=_ADOPT_ENDPOINT,
                key=key,
                request_hash=request_hash,
                code="completed_task_exists",
                message="已有完成的任务，请前往我的方案查看",
                status_code=409,
            )

        snapshot = await self._adoption_snapshot(session, customer_id, logo)
        if snapshot is None:
            return await self._store_error(
                session,
                customer_id=customer_id,
                endpoint=_ADOPT_ENDPOINT,
                key=key,
                request_hash=request_hash,
                code="logo_version_not_found",
                message="Logo version not found",
                status_code=404,
            )

        active_tasks = list(
            (
                await session.scalars(
                    select(DesignTask)
                    .where(
                        DesignTask.customer_id == customer_id,
                        DesignTask.status.in_(("waiting_assignment", "in_progress")),
                    )
                    .order_by(DesignTask.submitted_at.asc(), DesignTask.id.asc())
                )
            ).all()
        )
        if active_tasks and not confirm_replace_active_task:
            return await self._store_error(
                session,
                customer_id=customer_id,
                endpoint=_ADOPT_ENDPOINT,
                key=key,
                request_hash=request_hash,
                code="active_task_confirmation_required",
                message="已有提交的方案，请确认是否发起变更",
                status_code=409,
            )

        now = datetime.now(UTC)
        task_id = uuid4().hex
        replaced_status = active_tasks[0].status if active_tasks else None
        for active_task in active_tasks:
            active_task.status = "canceled"
            active_task.updated_at = now
            await self._lark.stop_task(
                session,
                task_id=active_task.id,
                reason="superseded",
                now=now,
            )
            await self._events.record_audit(
                session,
                action="design_task.canceled",
                resource_type="design_task",
                resource_id=active_task.id,
                actor_id=customer_id,
                trace_id=uuid4().hex,
                summary={"status": "canceled", "replacement_task_id": task_id},
            )
        if active_tasks:
            await session.flush()

        task = DesignTask(
            id=task_id,
            customer_id=customer_id,
            domain=domain,
            status="waiting_assignment",
            submitted_at=now,
            updated_at=now,
        )
        session.add(task)

        task.adoption_suggestion = normalized_suggestion
        task.adopted_logo_version_id = snapshot.adopted_version.id
        task.adopted_asset_id = snapshot.adopted_asset.asset_id
        task.initial_logo_version_id = snapshot.root_version.id
        task.initial_asset_id = snapshot.root_asset.asset_id
        task.ai_edit_inputs_json = json.dumps(
            snapshot.ai_edit_inputs,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        task.updated_at = now
        trace_id = uuid4().hex
        await self._events.record_audit(
            session,
            action="design_task.created",
            resource_type="design_task",
            resource_id=task.id,
            actor_id=customer_id,
            trace_id=trace_id,
            summary={
                "status": task.status,
                "adopted_logo_version_id": snapshot.adopted_version.id,
                "initial_logo_version_id": snapshot.root_version.id,
                "ai_edit_input_count": len(snapshot.ai_edit_inputs),
                "has_adoption_suggestion": normalized_suggestion is not None,
            },
        )
        await self._events.enqueue_notification(
            session,
            event_type="task.created",
            resource_type="design_task",
            resource_id=task.id,
            trace_id=trace_id,
            payload={"task_id": task.id},
        )
        event_type = (
            "task.adoption_submitted"
            if replaced_status is None
            else (
                "task.adoption_changed_before_acceptance"
                if replaced_status == "waiting_assignment"
                else "task.adoption_changed_in_progress"
            )
        )
        await self._lark.enqueue_immediate(
            session,
            event_type=event_type,
            task_id=task.id,
            trace_id=trace_id,
            payload={
                "replacement": replaced_status is not None,
                "previous_status": replaced_status,
            },
        )
        await self._lark.snapshot_stage(
            session,
            task_id=task.id,
            event_type="task.waiting_assignment_overdue",
            entered_at=now,
        )

        data = DesignTaskMutationDto(
            task=self._task_summary(task),
            created=True,
        ).model_dump(mode="json")
        return await self._store_success(
            session,
            customer_id=customer_id,
            endpoint=_ADOPT_ENDPOINT,
            key=key,
            request_hash=request_hash,
            status_code=201,
            data=data,
        )

    async def list_saved_logos(
        self, session: AsyncSession, customer_id: str
    ) -> SavedLogoListDto:
        rows = (
            await session.execute(
                select(SavedLogo, LogoVersion)
                .join(LogoVersion, LogoVersion.id == SavedLogo.logo_version_id)
                .where(
                    SavedLogo.customer_id == customer_id,
                    LogoVersion.customer_id == customer_id,
                )
                .order_by(SavedLogo.saved_at.desc())
            )
        ).all()
        items = [self._saved_logo_dto(saved, logo) for saved, logo in rows]
        return SavedLogoListDto(items=items, total=len(items))

    async def list_tasks(
        self, session: AsyncSession, customer_id: str
    ) -> DesignTaskListDto:
        rows = (
            await session.execute(
                select(DesignTask, AssetRecord.created_at)
                .outerjoin(
                    AssetRecord,
                    AssetRecord.asset_id == DesignTask.delivery_asset_id,
                )
                .where(
                    DesignTask.customer_id == customer_id,
                    DesignTask.adopted_logo_version_id.is_not(None),
                    DesignTask.initial_logo_version_id.is_not(None),
                )
                .order_by(DesignTask.submitted_at.desc())
            )
        ).all()
        return DesignTaskListDto(
            items=[
                self._task_summary(task, delivery_uploaded_at)
                for task, delivery_uploaded_at in rows
            ],
            total=len(rows),
        )

    async def task_detail(
        self, session: AsyncSession, customer_id: str, task_id: str
    ) -> DesignTaskDetailResponseDto:
        row = (
            await session.execute(
                select(DesignTask, AssetRecord.created_at)
                .outerjoin(
                    AssetRecord,
                    AssetRecord.asset_id == DesignTask.delivery_asset_id,
                )
                .where(
                    DesignTask.id == task_id,
                    DesignTask.customer_id == customer_id,
                    DesignTask.adopted_logo_version_id.is_not(None),
                    DesignTask.initial_logo_version_id.is_not(None),
                )
            )
        ).one_or_none()
        if row is None:
            raise CustomerDecisionError(
                "design_task_not_found", "Design task not found", 404
            )
        task, delivery_uploaded_at = row
        initial_version_id = cast(str, task.initial_logo_version_id)
        return DesignTaskDetailResponseDto(
            task=DesignTaskDetailDto(
                **self._task_summary(task, delivery_uploaded_at).model_dump(),
                initial_logo_version_id=initial_version_id,
                initial_image_url=f"/api/v1/my/tasks/{task.id}/initial-image/content",
                ai_edit_inputs=_safe_string_list(task.ai_edit_inputs_json),
            )
        )

    async def read_saved_logo(
        self, session: AsyncSession, customer_id: str, saved_logo_id: str
    ) -> tuple[str, bytes]:
        row = (
            await session.execute(
                select(SavedLogo, LogoVersion)
                .join(LogoVersion, LogoVersion.id == SavedLogo.logo_version_id)
                .where(
                    SavedLogo.id == saved_logo_id,
                    SavedLogo.customer_id == customer_id,
                    LogoVersion.customer_id == customer_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise CustomerDecisionError("saved_logo_not_found", "Saved Logo not found", 404)
        _, logo = row
        return await self._read_snapshot_asset(
            session,
            logo.asset_id,
            "saved_logo_not_found",
            "Saved Logo not found",
        )

    async def read_task_image(
        self,
        session: AsyncSession,
        customer_id: str,
        task_id: str,
        *,
        initial: bool,
    ) -> tuple[str, bytes]:
        task = await session.scalar(
            select(DesignTask).where(
                DesignTask.id == task_id,
                DesignTask.customer_id == customer_id,
            )
        )
        asset_id = task.initial_asset_id if task is not None and initial else (
            task.adopted_asset_id if task is not None else None
        )
        if not asset_id:
            raise CustomerDecisionError("task_image_not_found", "Task image not found", 404)
        return await self._read_snapshot_asset(
            session,
            asset_id,
            "task_image_not_found",
            "Task image not found",
        )

    async def read_task_delivery_image(
        self, session: AsyncSession, customer_id: str, task_id: str
    ) -> tuple[str, bytes]:
        """Read a completed delivery image only for its owning customer."""

        task = await session.scalar(
            select(DesignTask).where(
                DesignTask.id == task_id,
                DesignTask.customer_id == customer_id,
            )
        )
        if task is None or task.delivery_asset_id is None:
            raise CustomerDecisionError(
                "task_delivery_not_found", "Task delivery image not found", 404
            )
        try:
            asset, content = await self._assets.read_task_delivery_image(
                session, task.delivery_asset_id
            )
        except LookupError as error:
            raise CustomerDecisionError(
                "task_delivery_not_found", "Task delivery image not found", 404
            ) from error
        return asset.media_type, content

    async def _owned_logo(
        self, session: AsyncSession, customer_id: str, logo_version_id: str
    ) -> LogoVersion | None:
        logo = await session.scalar(
            select(LogoVersion).where(
                LogoVersion.id == logo_version_id,
                LogoVersion.customer_id == customer_id,
            )
        )
        if logo is None:
            return None
        asset = await session.get(AssetRecord, logo.asset_id)
        if asset is None or asset.purpose != "generated_logo":
            return None
        return logo

    async def _adoption_snapshot(
        self, session: AsyncSession, customer_id: str, adopted: LogoVersion
    ) -> AdoptionSnapshot | None:
        root_id = adopted.root_logo_version_id or adopted.id
        root = await self._owned_logo(session, customer_id, root_id)
        adopted_asset = await session.get(AssetRecord, adopted.asset_id)
        root_asset = await session.get(AssetRecord, root.asset_id) if root is not None else None
        if (
            root is None
            or adopted_asset is None
            or root_asset is None
            or root.domain != adopted.domain
        ):
            return None

        inputs_reversed: list[str] = []
        current = adopted
        visited: set[str] = set()
        while current.id != root.id:
            if current.id in visited or not current.parent_logo_version_id:
                return None
            visited.add(current.id)
            if not current.single_edit_request_id:
                return None
            edit_request = await session.get(
                SingleImageEditRequest, current.single_edit_request_id
            )
            if (
                edit_request is None
                or edit_request.customer_id != customer_id
                or edit_request.result_logo_version_id != current.id
            ):
                return None
            inputs_reversed.append(edit_request.description)
            parent = await self._owned_logo(
                session, customer_id, current.parent_logo_version_id
            )
            if parent is None or parent.domain != adopted.domain:
                return None
            current = parent

        return AdoptionSnapshot(
            adopted_version=adopted,
            adopted_asset=adopted_asset,
            root_version=root,
            root_asset=root_asset,
            ai_edit_inputs=list(reversed(inputs_reversed)),
        )

    async def _read_snapshot_asset(
        self,
        session: AsyncSession,
        asset_id: str,
        error_code: str,
        message: str,
    ) -> tuple[str, bytes]:
        try:
            asset, content = await self._assets.read_generated_logo(session, asset_id)
        except LookupError as error:
            raise CustomerDecisionError(error_code, message, 404) from error
        return asset.media_type, content

    async def _replay(
        self,
        session: AsyncSession,
        customer_id: str,
        endpoint: str,
        key: str,
        request_hash: str,
    ) -> DecisionResult | None:
        record = await session.scalar(
            select(EndpointIdempotencyRecord).where(
                EndpointIdempotencyRecord.customer_id == customer_id,
                EndpointIdempotencyRecord.endpoint == endpoint,
                EndpointIdempotencyRecord.idempotency_key == key,
            )
        )
        if record is None:
            return None
        if record.request_hash != request_hash:
            raise CustomerDecisionError(
                "idempotency_conflict",
                "Idempotency key was already used with different content",
                409,
            )
        return _deserialize_result(record.response_status, record.response_json)

    async def _store_success(
        self,
        session: AsyncSession,
        *,
        customer_id: str,
        endpoint: str,
        key: str,
        request_hash: str,
        status_code: int,
        data: dict[str, Any],
    ) -> DecisionResult:
        result = DecisionResult(status_code=status_code, data=data)
        await self._store_result(
            session, customer_id, endpoint, key, request_hash, result
        )
        return result

    async def _store_error(
        self,
        session: AsyncSession,
        *,
        customer_id: str,
        endpoint: str,
        key: str,
        request_hash: str,
        code: str,
        message: str,
        status_code: int,
    ) -> DecisionResult:
        result = DecisionResult(
            status_code=status_code,
            error_code=code,
            message=message,
        )
        await self._store_result(
            session, customer_id, endpoint, key, request_hash, result
        )
        return result

    async def _store_result(
        self,
        session: AsyncSession,
        customer_id: str,
        endpoint: str,
        key: str,
        request_hash: str,
        result: DecisionResult,
    ) -> None:
        payload: dict[str, Any]
        if result.error_code is None:
            payload = {"kind": "success", "data": result.data or {}}
        else:
            payload = {
                "kind": "error",
                "error_code": result.error_code,
                "message": result.message or "Request failed",
            }
        session.add(
            EndpointIdempotencyRecord(
                id=uuid4().hex,
                customer_id=customer_id,
                endpoint=endpoint,
                idempotency_key=key,
                request_hash=request_hash,
                response_status=result.status_code,
                response_json=json.dumps(
                    payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
                ),
            )
        )
        await session.flush()

    @staticmethod
    def _saved_logo_dto(saved: SavedLogo, logo: LogoVersion) -> SavedLogoDto:
        return SavedLogoDto(
            id=saved.id,
            logo_version_id=logo.id,
            domain=logo.domain,
            image_url=f"/api/v1/saved-logos/{saved.id}/image/content",
            saved_at=_as_utc(saved.saved_at),
        )

    @staticmethod
    def _task_summary(
        task: DesignTask,
        delivery_uploaded_at: datetime | None = None,
    ) -> DesignTaskSummaryDto:
        return DesignTaskSummaryDto(
            id=task.id,
            domain=task.domain,
            status=cast(Any, task.status),
            adoption_suggestion=task.adoption_suggestion,
            submitted_at=_as_utc(task.submitted_at),
            adopted_logo_version_id=cast(str, task.adopted_logo_version_id),
            adopted_image_url=f"/api/v1/my/tasks/{task.id}/adopted-image/content",
            delivery_image_url=(
                f"/api/v1/my/tasks/{task.id}/delivery-image/content"
                if task.delivery_asset_id is not None
                else None
            ),
            delivery_uploaded_at=(
                _as_utc(delivery_uploaded_at)
                if delivery_uploaded_at is not None
                else None
            ),
        )


def _normalize_idempotency_key(value: str) -> str:
    candidate = value.strip()
    if not candidate or len(candidate) > 200:
        raise CustomerDecisionError(
            "idempotency_key_required", "A valid Idempotency-Key is required", 422
        )
    return candidate


def _as_utc(value: datetime) -> datetime:
    """Return stable UTC-aware timestamps after SQLite removes timezone metadata."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    return candidate or None


def _request_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _deserialize_result(status_code: int, raw_payload: str) -> DecisionResult:
    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError) as error:
        raise CustomerDecisionError(
            "idempotency_record_invalid", "Stored idempotency result is unavailable", 500
        ) from error
    if not isinstance(payload, dict):
        raise CustomerDecisionError(
            "idempotency_record_invalid", "Stored idempotency result is unavailable", 500
        )
    if payload.get("kind") == "success" and isinstance(payload.get("data"), dict):
        return DecisionResult(status_code=status_code, data=payload["data"])
    if payload.get("kind") == "error":
        return DecisionResult(
            status_code=status_code,
            error_code=str(payload.get("error_code") or "request_failed"),
            message=str(payload.get("message") or "Request failed"),
        )
    raise CustomerDecisionError(
        "idempotency_record_invalid", "Stored idempotency result is unavailable", 500
    )


def _safe_string_list(raw_value: str) -> list[str]:
    try:
        value = json.loads(raw_value)
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
