"""Recoverable customer single-image editing for T-014."""

import asyncio
import json
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import (
    AssetRecord,
    LogoVersion,
    ModelConnection,
    SingleImageEditPolicyState,
    SingleImageEditPolicyVersion,
    SingleImageEditRequest,
)
from src.db.session import DatabaseRuntime, get_db_context
from src.models.generation import (
    SingleImageEditAcceptedDto,
    SingleImageEditContextDto,
    SingleImageEditStatusDto,
    SingleImageEditVersionDto,
)
from src.models.single_image_edit_policy import SingleImageEditPolicyPayload
from src.services.asset_service import AssetService, LocalFallbackAssetStorage
from src.services.event_service import EventService
from src.services.model_provider import (
    ImageGenerationProvider,
    ImageGenerationRequest,
    ImageToImageRequest,
    ImageToImageResult,
    KieGptImageProvider,
    ProviderError,
    fixed_rendering_metadata,
    image_provider_for_connection,
    is_valid_native_output,
)
from src.services.model_secret_service import ModelConnectionSecretService, SecretConfigurationError
from src.services.single_image_edit_policy_service import (
    SingleImageEditPolicyService,
    SingleImageEditPolicyUpgradeRequiredError,
)
from src.services.single_image_edit_prompt_compiler import (
    SingleImageEditCompileContext,
    SingleImageEditPromptCompilation,
    compile_single_image_edit_prompt,
)

_SINGLE_IMAGE_EDIT_SCENE = "single_image_edit"
_MAX_PROVIDER_ATTEMPTS = 2
_TERMINAL_PROVIDER_FAILURES = {
    "generation_configuration_failed",
    "invalid_output_count",
    "invalid_provider_request",
    "invalid_reference_input",
    "missing_reference_image",
    "provider_auth_failed",
    "provider_quota_exhausted",
    "provider_validation_failed",
    "unsupported_model",
    "unsupported_provider",
    "invalid_provider_url",
}


class SingleImageEditRequestError(RuntimeError):
    """A customer-safe single-edit failure with an explicit response status."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class SingleImageEditService:
    """Persist one edit run and create at most one new Logo version."""

    def __init__(
        self,
        runtime: DatabaseRuntime,
        asset_root: str,
        secret_encryption_key: str | None,
        provider: ImageGenerationProvider | None = None,
        events: EventService | None = None,
    ) -> None:
        self._runtime = runtime
        event_service = events or EventService()
        self._assets = AssetService(LocalFallbackAssetStorage(asset_root), event_service)
        self._provider_override = provider
        self._secrets = ModelConnectionSecretService(secret_encryption_key)
        self._events = event_service
        self._accept_lock = asyncio.Lock()
        self._provider_semaphore = asyncio.Semaphore(4)
        self._scheduled: set[asyncio.Task[None]] = set()
        self._scheduled_request_ids: set[str] = set()

    async def accept(
        self,
        session: AsyncSession,
        customer_id: str,
        source_version_id: str,
        edit_instruction: str,
    ) -> SingleImageEditAcceptedDto:
        """Validate the latest source and persist an immutable runtime snapshot."""

        async with self._accept_lock:
            instruction = edit_instruction.strip()
            if not instruction:
                raise SingleImageEditRequestError(
                    "edit_instruction_required", "请填写修改指令", 422
                )
            source = await session.get(LogoVersion, source_version_id)
            if source is None or source.customer_id != customer_id:
                raise SingleImageEditRequestError("logo_version_not_found", "当前版本不存在", 404)
            root_id = source.root_logo_version_id or source.id
            active_request = await session.scalar(
                select(SingleImageEditRequest.id)
                .where(
                    SingleImageEditRequest.customer_id == customer_id,
                    SingleImageEditRequest.root_logo_version_id == root_id,
                    SingleImageEditRequest.status == "processing",
                )
                .limit(1)
            )
            if active_request is not None:
                raise SingleImageEditRequestError(
                    "single_edit_in_progress", "当前版本正在生成中", 409
                )

            policy_version, connection, compilation = await self._runtime_policy(session, instruction)
            source_asset = await session.get(AssetRecord, source.asset_id)
            if source_asset is None:
                raise SingleImageEditRequestError(
                    "source_image_unavailable", "当前版本图片不可用", 409
                )
            now = datetime.now(UTC)
            request = SingleImageEditRequest(
                id=uuid4().hex,
                customer_id=customer_id,
                domain=source.domain,
                root_logo_version_id=root_id,
                source_logo_version_id=source.id,
                policy_version_id=policy_version.id,
                model_connection_id=connection.id,
                model_connection_version=connection.version,
                description="",
                edit_instruction=instruction,
                status="processing",
                attempt_count=0,
                run_snapshot_json=json.dumps(
                    {
                        "policy_version_id": policy_version.id,
                        "model_connection_id": connection.id,
                        "model_connection_version": connection.version,
                        "source": {
                            "logo_version_id": source.id,
                            "root_logo_version_id": root_id,
                            "version_number": source.version_number,
                            "asset_id": source.asset_id,
                            "content_hash": source_asset.content_hash,
                        },
                        "input": {
                            "original_edit_instruction": instruction,
                            "variables": {"用户修改指令": instruction},
                        },
                        "policy": {
                            "positive_content": _effective_positive_content(policy_version),
                            "negative_avoidance": policy_version.negative_avoidance,
                        },
                        "compiler_version": compilation.compiler_version,
                        "rule_set_version": "single-edit-delta-v1",
                        "rule_blocks": [
                            {"name": name, "content": content}
                            for name, content in compilation.rule_blocks
                        ],
                        "compiled_prompt": compilation.compiled_prompt,
                        "output_constraint": compilation.output_constraint,
                        "rendering": fixed_rendering_metadata(connection.model_id),
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                created_at=now,
                updated_at=now,
            )
            session.add(request)
            await self._events.record_audit(
                session,
                action="single_image_edit.accepted",
                resource_type="single_image_edit_request",
                resource_id=request.id,
                actor_id=customer_id,
                trace_id=uuid4().hex,
                summary={
                    "source_logo_version_id": source.id,
                    "source_version_number": source.version_number,
                    "policy_version_id": policy_version.id,
                    "model_connection_version": connection.version,
                    "has_edit_instruction": True,
                },
            )
            await session.flush()
            return SingleImageEditAcceptedDto(
                request_id=request.id,
                source_version_id=source.id,
                status="processing",
            )

    def schedule(self, request_id: str) -> None:
        if request_id in self._scheduled_request_ids:
            return
        self._scheduled_request_ids.add(request_id)
        task = asyncio.create_task(self.execute(request_id))
        self._scheduled.add(task)

        def clear_scheduled(completed: asyncio.Task[None]) -> None:
            self._scheduled.discard(completed)
            self._scheduled_request_ids.discard(request_id)

        task.add_done_callback(clear_scheduled)

    async def resume_pending(self) -> None:
        async with get_db_context(self._runtime) as session:
            request_ids = list(
                (
                    await session.scalars(
                        select(SingleImageEditRequest.id).where(
                            SingleImageEditRequest.status == "processing"
                        )
                    )
                ).all()
            )
        for request_id in request_ids:
            self.schedule(request_id)

    async def execute(self, request_id: str) -> None:
        async with self._provider_semaphore:
            last_error: ProviderError | None = None
            for _ in range(_MAX_PROVIDER_ATTEMPTS):
                try:
                    connection, request, provider_request = await self._provider_input(request_id)
                    provider = image_provider_for_connection(
                        connection.provider,
                        connection.model_id,
                        self._provider_override,
                    )
                    result = await self._generate(
                        provider,
                        connection,
                        request,
                        provider_request,
                    )
                    if (
                        result.diagnostic_capture_status != "captured"
                        or result.diagnostic_image is None
                        or result.diagnostic_media_type is None
                        or not is_valid_native_output(
                            result.diagnostic_image,
                            result.diagnostic_media_type,
                            connection.model_id,
                        )
                    ):
                        raise ProviderError(
                            "invalid_generated_image",
                            "Generated image did not meet output requirements",
                        )
                    await self._persist_success(
                        request,
                        connection.model_id,
                        result.diagnostic_image,
                        result.diagnostic_media_type,
                        result.provider_http_status,
                        result.response_image_count,
                        result.provider_request_id_hash,
                    )
                    return
                except ProviderError as error:
                    last_error = error
                    if error.code in _TERMINAL_PROVIDER_FAILURES or error.code in {
                        "provider_submission_uncertain",
                    }:
                        break
                except (LookupError, SecretConfigurationError, ValueError) as error:
                    last_error = ProviderError("generation_configuration_failed", str(error))
                    break
            await self._persist_failure(
                request_id,
                last_error or ProviderError("single_edit_generation_failed", "Generation failed"),
            )

    async def _generate(
        self,
        provider: ImageGenerationProvider,
        connection: ModelConnection,
        request_record: SingleImageEditRequest,
        request: ImageToImageRequest,
    ) -> ImageToImageResult:
        if not isinstance(provider, KieGptImageProvider):
            return await provider.image_to_image(connection.api_url or "", request)
        generation_request = ImageGenerationRequest(
            model_id=request.model_id,
            api_key=request.api_key,
            prompt=request.prompt,
            reference_image=request.reference_image,
            reference_media_type=request.reference_media_type,
            max_input_images=request.max_input_images,
            output_count=request.output_count,
        )
        task_id = request_record.provider_task_id
        if task_id is None:
            task_id = await self._claim_provider_submission(request_record.id)
        if task_id is None:
            try:
                submission = await provider.submit(connection.api_url or "", generation_request)
            except ProviderError as error:
                if error.code != "provider_submission_uncertain":
                    await self._clear_provider_submission_claim(request_record.id)
                raise
            await self._persist_provider_task_id(request_record.id, submission.task_id)
            task_id = submission.task_id
        return await provider.wait_for_result(request.api_key, task_id)

    async def _claim_provider_submission(self, request_id: str) -> str | None:
        async with get_db_context(self._runtime) as session:
            request = await session.get(SingleImageEditRequest, request_id)
            if request is None or request.status != "processing":
                raise ProviderError(
                    "provider_task_persistence_failed",
                    "Single-image edit task is no longer writable",
                )
            if request.provider_task_id is not None:
                return cast(str, request.provider_task_id)
            if request.provider_submission_state == "submitting":
                raise ProviderError(
                    "provider_submission_uncertain",
                    "A prior model task submission did not return a recoverable identifier",
                )
            request.provider_submission_state = "submitting"
            request.updated_at = datetime.now(UTC)
            return None

    async def _clear_provider_submission_claim(self, request_id: str) -> None:
        async with get_db_context(self._runtime) as session:
            request = await session.get(SingleImageEditRequest, request_id)
            if request is not None and request.provider_task_id is None:
                request.provider_submission_state = None
                request.updated_at = datetime.now(UTC)

    async def _persist_provider_task_id(self, request_id: str, task_id: str) -> None:
        async with get_db_context(self._runtime) as session:
            request = await session.get(SingleImageEditRequest, request_id)
            if request is None or request.status != "processing":
                raise ProviderError(
                    "provider_task_persistence_failed",
                    "Single-image edit task is no longer writable",
                )
            if request.provider_task_id is not None and request.provider_task_id != task_id:
                raise ProviderError(
                    "provider_task_conflict",
                    "Single-image edit task identifier is inconsistent",
                )
            request.provider_task_id = task_id
            request.provider_submission_state = "submitted"
            request.updated_at = datetime.now(UTC)

    async def status_for_customer(
        self, customer_id: str, request_id: str
    ) -> SingleImageEditStatusDto:
        async with get_db_context(self._runtime) as session:
            request = await session.get(SingleImageEditRequest, request_id)
            if request is None or request.customer_id != customer_id:
                raise SingleImageEditRequestError(
                    "single_edit_not_found", "单图生成请求不存在", 404
                )
            should_schedule = request.status == "processing"
        if should_schedule:
            self.schedule(request_id)
        async with get_db_context(self._runtime) as session:
            request = await session.get(SingleImageEditRequest, request_id)
            if request is None:
                raise SingleImageEditRequestError(
                    "single_edit_not_found", "单图生成请求不存在", 404
                )
            return await self._status_dto(session, request)

    async def context_for_customer(
        self, customer_id: str, logo_version_id: str
    ) -> SingleImageEditContextDto:
        async with get_db_context(self._runtime) as session:
            version = await session.get(LogoVersion, logo_version_id)
            if version is None or version.customer_id != customer_id:
                raise SingleImageEditRequestError("logo_version_not_found", "当前版本不存在", 404)
            root_id = version.root_logo_version_id or version.id
            versions = await self._version_window(session, customer_id, root_id)
            if not versions:
                raise SingleImageEditRequestError("logo_version_not_found", "当前版本不存在", 404)
            return SingleImageEditContextDto(
                root_version_id=root_id,
                domain=version.domain,
                current_version_id=versions[-1].id,
                versions=await self._version_dtos(session, versions),
            )

    async def read_version_image(
        self, customer_id: str, logo_version_id: str, *, thumbnail: bool = False
    ) -> tuple[str, bytes]:
        async with get_db_context(self._runtime) as session:
            version = await session.get(LogoVersion, logo_version_id)
            if version is None or version.customer_id != customer_id:
                raise SingleImageEditRequestError(
                    "generation_image_not_found", "生成图片不存在", 404
                )
            root_id = version.root_logo_version_id or version.id
            window = await self._version_window(session, customer_id, root_id)
            if version.id not in {item.id for item in window}:
                raise SingleImageEditRequestError(
                    "generation_image_not_found", "生成图片不存在", 404
                )
            asset, content = await self._assets.read_generated_logo(
                session, version.asset_id, thumbnail=thumbnail
            )
            return ("image/webp" if thumbnail else asset.media_type), cast(bytes, content)

    async def _runtime_policy(
        self, session: AsyncSession, description: str
    ) -> tuple[
        SingleImageEditPolicyVersion,
        ModelConnection,
        SingleImageEditPromptCompilation,
    ]:
        try:
            await SingleImageEditPolicyService().ensure_active_upgrade(session)
        except SingleImageEditPolicyUpgradeRequiredError as error:
            raise SingleImageEditRequestError(
                "single_edit_policy_upgrade_required",
                "当前单图编辑策略需要管理员升级后才能使用",
                409,
            ) from error
        state = await session.get(SingleImageEditPolicyState, _SINGLE_IMAGE_EDIT_SCENE)
        if state is None or state.active_version_id is None:
            raise SingleImageEditRequestError(
                "single_edit_policy_not_published", "请先发布单图编辑策略", 409
            )
        version = await session.get(SingleImageEditPolicyVersion, state.active_version_id)
        if version is None:
            raise SingleImageEditRequestError(
                "single_edit_policy_not_published", "请先发布单图编辑策略", 409
            )
        connection = await session.get(ModelConnection, version.model_connection_id)
        if (
            connection is None
            or connection.version != version.model_connection_version
            or not _image_to_image_verified(connection)
        ):
            raise SingleImageEditRequestError(
                "single_edit_runtime_unavailable", "当前单图编辑模型不可用", 409
            )
        policy = SingleImageEditPolicyPayload(
            model_connection_id=version.model_connection_id,
            positive_content=_effective_positive_content(version),
            negative_avoidance=version.negative_avoidance,
        )
        compilation = compile_single_image_edit_prompt(
            policy=policy,
            edit_instruction=description,
            context=SingleImageEditCompileContext(
                model_connection_id=connection.id,
                model_connection_version=connection.version,
                image_to_image_verified=True,
            ),
        )
        return version, connection, compilation

    async def _provider_input(
        self, request_id: str
    ) -> tuple[ModelConnection, SingleImageEditRequest, ImageToImageRequest]:
        async with get_db_context(self._runtime) as session:
            request = await session.get(SingleImageEditRequest, request_id)
            if request is None or request.status != "processing":
                raise LookupError("Single-image edit request is unavailable")
            connection = await session.get(ModelConnection, request.model_connection_id)
            if (
                connection is None
                or connection.version != request.model_connection_version
                or not _image_to_image_verified(connection)
            ):
                raise LookupError("Single-image edit model connection is unavailable")
            source = await session.get(LogoVersion, request.source_logo_version_id)
            if source is None:
                raise LookupError("Single-image edit source version is unavailable")
            asset, source_image = await self._assets.read_generated_logo(session, source.asset_id)
            snapshot = _safe_snapshot(request.run_snapshot_json)
            source_snapshot = snapshot.get("source")
            expected_hash = (
                source_snapshot.get("content_hash") if isinstance(source_snapshot, dict) else None
            )
            prompt = snapshot.get("compiled_prompt")
            if expected_hash != asset.content_hash or not isinstance(prompt, str) or not prompt:
                raise LookupError("Single-image edit snapshot is unavailable")
            api_key = await self._secrets.read(session, connection.id)
            if not api_key:
                raise LookupError("Single-image edit model credential is unavailable")
            request.attempt_count += 1
            request.updated_at = datetime.now(UTC)
            return (
                connection,
                request,
                ImageToImageRequest(
                    model_id=connection.model_id,
                    api_key=api_key,
                    reference_image=source_image,
                    reference_media_type=asset.media_type,
                    prompt=prompt,
                    max_input_images=connection.max_input_images,
                    output_count=1,
                ),
            )

    async def _persist_success(
        self,
        request_snapshot: SingleImageEditRequest,
        model_id: str,
        content: bytes,
        media_type: str,
        provider_http_status: int | None,
        response_image_count: int | None,
        provider_request_id_hash: str | None,
    ) -> None:
        async with get_db_context(self._runtime) as session:
            request = await session.get(SingleImageEditRequest, request_snapshot.id)
            if request is None or request.status != "processing" or request.result_logo_version_id:
                return
            source = await session.get(LogoVersion, request.source_logo_version_id)
            if source is None:
                raise LookupError("Single-image edit source version is unavailable")
            latest = await self._latest_version(
                session, request.customer_id, request.root_logo_version_id
            )
            if latest is None:
                raise LookupError("Single-image edit version chain is unavailable")
            asset = await self._assets.create_generated_logo(
                session,
                content=content,
                media_type=media_type,
                actor_id=request.customer_id,
                trace_id=uuid4().hex,
                source_resource_id=request.id,
                source_resource_type="single_image_edit_request",
            )
            version_id = uuid4().hex
            session.add(
                LogoVersion(
                    id=version_id,
                    customer_id=request.customer_id,
                    domain=request.domain,
                    generation_request_id=None,
                    candidate_job_id=None,
                    single_edit_request_id=request.id,
                    parent_logo_version_id=source.id,
                    root_logo_version_id=request.root_logo_version_id,
                    version_number=latest.version_number + 1,
                    asset_id=asset.asset_id,
                    created_at=datetime.now(UTC),
                )
            )
            request.status = "succeeded"
            request.error_code = None
            request.result_logo_version_id = version_id
            request.updated_at = datetime.now(UTC)
            await self._events.record_audit(
                session,
                action="single_image_edit.succeeded",
                resource_type="single_image_edit_request",
                resource_id=request.id,
                actor_id=request.customer_id,
                trace_id=uuid4().hex,
                summary={
                    "source_logo_version_id": source.id,
                    "result_logo_version_id": version_id,
                    "provider_http_status": provider_http_status,
                    "response_image_count": response_image_count,
                    "provider_request_id_hash": provider_request_id_hash,
                    "rendering": fixed_rendering_metadata(model_id),
                },
            )

    async def _persist_failure(self, request_id: str, error: ProviderError) -> None:
        async with get_db_context(self._runtime) as session:
            request = await session.get(SingleImageEditRequest, request_id)
            if request is None or request.status != "processing":
                return
            request.status = "failed"
            request.error_code = error.code
            request.updated_at = datetime.now(UTC)
            await self._events.record_audit(
                session,
                action="single_image_edit.failed",
                resource_type="single_image_edit_request",
                resource_id=request.id,
                actor_id=request.customer_id,
                trace_id=uuid4().hex,
                summary={
                    "error_code": error.code,
                    "provider_http_status": error.provider_http_status,
                    "response_image_count": error.response_image_count,
                    "provider_status_family": error.http_status_family,
                    "provider_operation": error.provider_operation,
                },
            )

    async def _status_dto(
        self, session: AsyncSession, request: SingleImageEditRequest
    ) -> SingleImageEditStatusDto:
        versions = await self._version_window(
            session, request.customer_id, request.root_logo_version_id
        )
        return SingleImageEditStatusDto(
            request_id=request.id,
            source_version_id=request.source_logo_version_id,
            root_version_id=request.root_logo_version_id,
            domain=request.domain,
            status=request.status,
            error_code=request.error_code,
            current_version_id=versions[-1].id,
            versions=await self._version_dtos(session, versions),
        )

    async def _latest_version(
        self, session: AsyncSession, customer_id: str, root_id: str
    ) -> LogoVersion | None:
        return await session.scalar(
            select(LogoVersion)
            .where(
                LogoVersion.customer_id == customer_id,
                or_(LogoVersion.id == root_id, LogoVersion.root_logo_version_id == root_id),
            )
            .order_by(LogoVersion.version_number.desc(), LogoVersion.created_at.desc())
            .limit(1)
        )

    async def _version_window(
        self, session: AsyncSession, customer_id: str, root_id: str
    ) -> list[LogoVersion]:
        rows = list(
            (
                await session.scalars(
                    select(LogoVersion)
                    .where(
                        LogoVersion.customer_id == customer_id,
                        or_(LogoVersion.id == root_id, LogoVersion.root_logo_version_id == root_id),
                    )
                    .order_by(LogoVersion.version_number.desc(), LogoVersion.created_at.desc())
                    .limit(2)
                )
            ).all()
        )
        return list(reversed(rows))

    async def _version_dtos(
        self, session: AsyncSession, versions: list[LogoVersion]
    ) -> list[SingleImageEditVersionDto]:
        result: list[SingleImageEditVersionDto] = []
        for version in versions:
            description: str | None = None
            if version.single_edit_request_id:
                request = await session.get(SingleImageEditRequest, version.single_edit_request_id)
                if request is not None:
                    description = request.edit_instruction or request.description or None
            result.append(
                SingleImageEditVersionDto(
                    id=version.id,
                    version_number=version.version_number,
                    edit_instruction=description,
                    image_url=(f"/api/v1/generations/logo-versions/{version.id}/single-edit-image"),
                )
            )
        return result


def _image_to_image_verified(connection: ModelConnection) -> bool:
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


def _effective_positive_content(version: SingleImageEditPolicyVersion) -> str:
    """Compile historical split-template snapshots through the current schema."""

    positive_content = str(version.positive_content)
    if "{{用户补充描述}}" in positive_content:
        return positive_content
    legacy_template = str(version.user_description_template).strip()
    if not legacy_template:
        return positive_content
    return f"{positive_content.rstrip()}\n{legacy_template}"


def _safe_snapshot(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
