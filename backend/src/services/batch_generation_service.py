"""Recoverable customer batch image generation execution for T-013/T-014A."""

import asyncio
import hmac
import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import (
    AssetRecord,
    BatchGenerationPolicyState,
    BatchGenerationPolicyVersion,
    EndpointIdempotencyRecord,
    GenerationCandidateJob,
    GenerationRequest,
    LogoVersion,
    ModelConnection,
)
from src.db.session import DatabaseRuntime, get_db_context
from src.models.batch_generation_policy import BatchPolicyPayload, BatchStyleDto
from src.models.generation import (
    BatchGenerationAcceptedDto,
    DomainSuffix,
    GeneratedLogoVersionDto,
    GenerationBatchDto,
    GenerationCandidateFailureDto,
    GenerationCandidateSlotDto,
    GenerationSlotRetryAcceptedDto,
    GenerationStatusDto,
)
from src.services.asset_service import (
    AssetService,
    LocalFallbackAssetStorage,
    is_valid_source_image,
)
from src.services.batch_generation_policy_service import (
    BatchGenerationPolicyService,
    BatchStyleSelectionError,
)
from src.services.batch_prompt_compiler import (
    REPLENISHMENT_BUDGET,
    BatchCompileContext,
    BatchTemplateCombination,
    ReferenceInputQuotaError,
    compile_batch_prompt,
    normalize_domain,
    normalize_reference_requirement,
    validate_batch_policy,
    validate_reference_input_quota,
)
from src.services.event_service import EventService
from src.services.model_provider import (
    ImageGenerationProvider,
    ImageGenerationRequest,
    ImageToImageResult,
    KieGptImageProvider,
    KieTaskSubmission,
    ProviderError,
    fixed_rendering_metadata,
    image_provider_for_connection,
    is_valid_native_output,
)
from src.services.model_secret_service import ModelConnectionSecretService, SecretConfigurationError

_BATCH_SCENE = "batch_generation"
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
_NON_REPLENISHABLE_FAILURES = {
    "provider_poll_timeout",
    "provider_submission_uncertain",
    "provider_task_conflict",
    "provider_task_persistence_failed",
    "timeout",
    "network_error",
}


class BatchGenerationRequestError(RuntimeError):
    """A customer-safe request failure with an explicit response status and code."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class BatchGenerationService:
    """Persist work first, then execute it through an app-owned recoverable worker."""

    def __init__(
        self,
        runtime: DatabaseRuntime,
        asset_root: str,
        secret_encryption_key: str | None,
        provider: ImageGenerationProvider | None = None,
        events: EventService | None = None,
        retry_token_secret: str | None = None,
    ) -> None:
        self._runtime = runtime
        event_service = events or EventService()
        self._assets = AssetService(LocalFallbackAssetStorage(asset_root), event_service)
        self._provider_override = provider
        self._secrets = ModelConnectionSecretService(secret_encryption_key)
        self._events = event_service
        self._scheduled: set[asyncio.Task[None]] = set()
        self._scheduled_request_ids: set[str] = set()
        self._retry_token_secret = (retry_token_secret or secret_encryption_key or "").encode()
        self._scheduled_slot_retries: set[tuple[str, int]] = set()
        self._slot_retry_lock = asyncio.Lock()

    async def accept(
        self,
        session: AsyncSession,
        customer_id: str,
        domain_label: str,
        domain_suffix: DomainSuffix,
        source_image_asset_id: str | None = None,
        user_reference_requirement: str | None = None,
        selected_style_ids: list[str] | None = None,
    ) -> BatchGenerationAcceptedDto:
        """Create all initial jobs and snapshots without invoking the provider."""

        normalized_label = normalize_domain(domain_label)
        if normalized_label is None:
            raise BatchGenerationRequestError("invalid_domain", "请输入品牌信息", 422)
        raw_requirement = user_reference_requirement.strip() if user_reference_requirement else None
        source_asset: AssetRecord | None = None
        if source_image_asset_id is not None:
            source_asset = await session.get(AssetRecord, source_image_asset_id)
            if (
                source_asset is None
                or source_asset.purpose != "customer_generation_source"
                or source_asset.owner_customer_id != customer_id
            ):
                raise BatchGenerationRequestError(
                    "invalid_source_image", "视觉参考图片不可用", 422
                )
            try:
                _, source_content = await self._assets.read_customer_generation_source(
                    session, source_asset.asset_id, customer_id
                )
            except LookupError as error:
                raise BatchGenerationRequestError(
                    "invalid_source_image", "视觉参考图片不可用", 422
                ) from error
            if sha256(source_content).hexdigest() != source_asset.content_hash:
                raise BatchGenerationRequestError(
                    "invalid_source_image", "视觉参考图片完整性校验失败", 422
                )
            if not is_valid_source_image(source_content, source_asset.media_type):
                raise BatchGenerationRequestError(
                    "invalid_source_image", "视觉参考图片不可解码", 422
                )
        full_domain = f"{normalized_label}{domain_suffix}"
        policy_version, policy, context, connection = await self._runtime_policy(session)
        if source_asset is not None:
            context = BatchCompileContext(
                model_connection_id=context.model_connection_id,
                model_connection_version=context.model_connection_version,
                image_to_image_verified=context.image_to_image_verified,
                assets={**context.assets, source_asset.asset_id: source_asset},
                max_input_images=context.max_input_images,
            )
        selected_ids = list(selected_style_ids or [])
        try:
            combinations, style_allocation = (
                await BatchGenerationPolicyService().allocate_rotation_combinations(
                    session, policy_version.id, selected_ids
                )
            )
        except BatchStyleSelectionError as error:
            raise BatchGenerationRequestError(error.code, error.message, 422) from error
        if not combinations:
            raise BatchGenerationRequestError(
                "no_generation_target", "当前批量生图策略没有可生成的图片", 409
            )
        try:
            for combination in combinations:
                validate_reference_input_quota(
                    customer_source_count=1 if source_asset is not None else 0,
                    template_reference_count=len(combination.reference_image_asset_ids),
                    max_input_images=connection.max_input_images,
                )
        except ReferenceInputQuotaError as error:
            raise BatchGenerationRequestError(error.code, str(error), 409) from error

        now = datetime.now(UTC)
        request = GenerationRequest(
            id=uuid4().hex,
            customer_id=customer_id,
            domain=full_domain,
            domain_label=normalized_label,
            domain_suffix=domain_suffix,
            source_image_asset_id=source_asset.asset_id if source_asset else None,
            user_reference_requirement_raw=raw_requirement or None,
            user_reference_requirement_normalized=normalize_reference_requirement(raw_requirement),
            generation_mode=(
                "reference_guided_generation" if source_asset is not None else "text_generation"
            ),
            selected_style_ids_json=json.dumps(selected_ids, ensure_ascii=True, separators=(",", ":")),
            style_allocation_json=json.dumps(
                style_allocation, ensure_ascii=True, separators=(",", ":"), sort_keys=True
            ),
            policy_version_id=policy_version.id,
            model_connection_id=policy_version.model_connection_id,
            model_connection_version=policy_version.model_connection_version,
            target_count=len(combinations),
            status="processing",
            failure_summary_json="{}",
            created_at=now,
            updated_at=now,
        )
        session.add(request)
        for ordinal, combination in enumerate(combinations, start=1):
            session.add(
                self._candidate_job(
                    request=request,
                    policy=policy,
                    context=context,
                    model_id=connection.model_id,
                    combination=combination,
                    ordinal=ordinal,
                    now=now,
                )
            )
        await self._events.record_audit(
            session,
            action="batch_generation.accepted",
            resource_type="generation_request",
            resource_id=request.id,
            actor_id=customer_id,
            trace_id=uuid4().hex,
            summary={
                "policy_version_id": policy_version.id,
                "model_connection_version": policy_version.model_connection_version,
                "target_count": request.target_count,
                "created_candidate_jobs": len(combinations),
                "selected_style_ids": selected_ids,
                "style_allocation": style_allocation,
            },
        )
        await session.flush()
        return BatchGenerationAcceptedDto(
            request_id=request.id,
            target_count=request.target_count,
            created_candidate_jobs=len(combinations),
            status="processing",
        )

    def schedule(self, request_id: str) -> None:
        """Start best-effort execution after the accepting transaction has committed."""

        if request_id in self._scheduled_request_ids:
            return
        self._scheduled_request_ids.add(request_id)
        task = asyncio.create_task(self.execute(request_id))
        self._scheduled.add(task)

        def clear_scheduled(completed: asyncio.Task[None]) -> None:
            self._scheduled.discard(completed)
            self._scheduled_request_ids.discard(request_id)

        task.add_done_callback(clear_scheduled)

    def schedule_slot_retry(self, request_id: str, slot_index: int) -> None:
        """Run a committed failed-slot reset without touching another candidate."""

        key = (request_id, slot_index)
        if key in self._scheduled_slot_retries:
            return
        self._scheduled_slot_retries.add(key)
        task = asyncio.create_task(self._execute_slot_retry(request_id, slot_index))
        self._scheduled.add(task)

        def clear_scheduled(completed: asyncio.Task[None]) -> None:
            self._scheduled.discard(completed)
            self._scheduled_slot_retries.discard(key)

        task.add_done_callback(clear_scheduled)

    async def retry_failed_slot(
        self,
        customer_id: str,
        request_id: str,
        slot_index: int,
        retry_token: str,
        idempotency_key: str,
    ) -> GenerationSlotRetryAcceptedDto:
        """Atomically validate and reset only the original job for one visible slot."""

        endpoint = f"generation_slot_retry:{request_id}:{slot_index}"
        request_hash = sha256(retry_token.encode()).hexdigest()
        async with self._slot_retry_lock, get_db_context(self._runtime) as session:
            replay = await session.scalar(
                select(EndpointIdempotencyRecord).where(
                    EndpointIdempotencyRecord.customer_id == customer_id,
                    EndpointIdempotencyRecord.endpoint == endpoint,
                    EndpointIdempotencyRecord.idempotency_key == idempotency_key,
                )
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise BatchGenerationRequestError(
                        "idempotency_conflict",
                        "Idempotency key was already used with different content",
                        409,
                    )
                data = _safe_snapshot(replay.response_json).get("data")
                return GenerationSlotRetryAcceptedDto.model_validate(data)
            request = await session.get(GenerationRequest, request_id)
            if request is None or request.customer_id != customer_id:
                raise BatchGenerationRequestError(
                    "generation_not_found", "Generation request not found", 404
                )
            if slot_index < 0 or slot_index >= request.target_count or slot_index > 8:
                raise BatchGenerationRequestError(
                    "generation_slot_not_found", "Generation slot not found", 404
                )
            original = await session.scalar(
                select(GenerationCandidateJob).where(
                    GenerationCandidateJob.request_id == request_id,
                    GenerationCandidateJob.ordinal == slot_index + 1,
                )
            )
            if original is None:
                raise BatchGenerationRequestError(
                    "generation_slot_not_found", "Generation slot not found", 404
                )
            if not hmac.compare_digest(self._retry_token(original, slot_index), retry_token):
                raise BatchGenerationRequestError(
                    "invalid_retry_token", "Invalid retry token", 403
                )
            visible = await self._visible_slot_jobs(session, request)
            visible_job = visible.get(slot_index)
            if visible_job is not None and visible_job.status == "succeeded":
                raise BatchGenerationRequestError(
                    "generation_slot_not_failed", "Generation slot is not failed", 409
                )
            if original.status != "failed":
                raise BatchGenerationRequestError(
                    "generation_slot_retry_in_progress", "Generation slot retry is in progress", 409
                )
            original.status = "pending"
            original.attempt_count = 0
            original.error_code = None
            original.provider_task_id = None
            original.provider_submission_state = None
            original.result_asset_id = None
            original.updated_at = datetime.now(UTC)
            accepted = GenerationSlotRetryAcceptedDto(
                request_id=request_id, slot_index=slot_index, status="processing"
            )
            session.add(EndpointIdempotencyRecord(
                id=uuid4().hex,
                customer_id=customer_id,
                endpoint=endpoint,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                response_status=202,
                response_json=json.dumps(
                    {"data": accepted.model_dump(mode="json")},
                    ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                ),
            ))
        return accepted

    async def _execute_slot_retry(self, request_id: str, slot_index: int) -> None:
        async with get_db_context(self._runtime) as session:
            job = await session.scalar(
                select(GenerationCandidateJob).where(
                    GenerationCandidateJob.request_id == request_id,
                    GenerationCandidateJob.ordinal == slot_index + 1,
                )
            )
            job_id = job.id if job is not None and job.status == "pending" else None
        if job_id is not None:
            await self._execute_candidate(job_id)

    async def execute(self, request_id: str) -> None:
        """Resume one request without delaying any other accepted batch."""

        try:
            while True:
                request = await self._request(request_id)
                if request is None or request.status in {"succeeded", "failed"}:
                    return
                await self._recover_running_jobs(request_id)
                pending = await self._pending_jobs(request_id)
                if pending:
                    # Every selected candidate owns one provider task and starts together.
                    await asyncio.gather(*(self._execute_candidate(job.id) for job in pending))
                    continue

                success_count, failed_jobs, total_jobs = await self._job_counts(request_id)
                if success_count >= request.target_count:
                    await self._finish(request_id, "succeeded", None)
                    return
                if any(
                    job.error_code in _TERMINAL_PROVIDER_FAILURES for job in failed_jobs
                ):
                    await self._finish(
                        request_id,
                        "succeeded" if success_count else "failed",
                        {
                            "success_count": success_count,
                            "failed_count": len(failed_jobs),
                            "failure_codes": sorted(
                                {job.error_code for job in failed_jobs if job.error_code}
                            ),
                        },
                    )
                    return
                if any(
                    job.error_code in _NON_REPLENISHABLE_FAILURES
                    and job.provider_submission_state in {"submitting", "submitted"}
                    for job in failed_jobs
                ):
                    await self._finish(
                        request_id,
                        "succeeded" if success_count else "failed",
                        {
                            "success_count": success_count,
                            "failed_count": len(failed_jobs),
                            "failure_codes": sorted(
                                {job.error_code for job in failed_jobs if job.error_code}
                            ),
                        },
                    )
                    return
                replacements_used = max(0, total_jobs - request.target_count)
                remaining_budget = REPLENISHMENT_BUDGET - replacements_used
                if remaining_budget <= 0 or not failed_jobs:
                    await self._finish(
                        request_id,
                        "succeeded" if success_count else "failed",
                        {
                            "success_count": success_count,
                            "failed_count": len(failed_jobs),
                            "failure_codes": sorted(
                                {job.error_code for job in failed_jobs if job.error_code}
                            ),
                        },
                    )
                    return
                await self._create_replenishments(request_id, failed_jobs[:remaining_budget])
        except (BatchGenerationRequestError, LookupError, ValueError):
            await self._finish(
                request_id,
                "failed",
                {
                    "success_count": 0,
                    "failed_count": 0,
                    "failure_codes": ["runtime_unavailable"],
                },
            )

    async def status_for_customer(
        self, customer_id: str, request_id: str, *, include_history: bool = True
    ) -> GenerationStatusDto:
        """Return request status, with history only when the caller needs it."""

        async with get_db_context(self._runtime) as session:
            request = await session.get(GenerationRequest, request_id)
            if request is None or request.customer_id != customer_id:
                raise BatchGenerationRequestError("generation_not_found", "生成请求不存在", 404)
            should_schedule = request.status == "processing"
        if should_schedule:
            self.schedule(request_id)

        async with get_db_context(self._runtime) as session:
            request = await session.get(GenerationRequest, request_id)
            if request is None:
                raise BatchGenerationRequestError("generation_not_found", "生成请求不存在", 404)
            return await self._status_dto(session, request, include_history=include_history)

    async def latest_successful_for_customer(
        self, customer_id: str
    ) -> GenerationStatusDto | None:
        """Return the customer's newest successful request and complete result history."""

        async with get_db_context(self._runtime) as session:
            request = await session.scalar(
                select(GenerationRequest)
                .where(
                    GenerationRequest.customer_id == customer_id,
                    GenerationRequest.status == "succeeded",
                )
                .order_by(GenerationRequest.created_at.desc(), GenerationRequest.id.desc())
                .limit(1)
            )
            if request is None:
                return None
            return await self._status_dto(session, request)

    async def read_logo_image(
        self, customer_id: str, window_anchor_request_id: str, logo_version_id: str, *, thumbnail: bool = False
    ) -> tuple[str, bytes]:
        """Read one result only when it belongs to the customer's successful history."""

        async with get_db_context(self._runtime) as session:
            anchor = await session.get(GenerationRequest, window_anchor_request_id)
            if anchor is None or anchor.customer_id != customer_id:
                raise BatchGenerationRequestError("generation_not_found", "生成图片不存在", 404)
            window_ids = {
                request.id for request in await self._successful_batch_window(session, anchor)
            }
            # A processing request can already own successful candidate assets.
            # Keep those assets readable while the remaining provider tasks run.
            if anchor.status == "processing":
                window_ids.add(anchor.id)
            logo = await session.get(LogoVersion, logo_version_id)
            if (
                logo is None
                or logo.customer_id != customer_id
                or logo.generation_request_id not in window_ids
            ):
                raise BatchGenerationRequestError(
                    "generation_image_not_found", "生成图片不存在", 404
                )
            asset, content = await self._assets.read_generated_logo(
                session, logo.asset_id, thumbnail=thumbnail
            )
            return ("image/webp" if thumbnail else asset.media_type), cast(bytes, content)

    async def _successful_batch_window(
        self, session: AsyncSession, anchor: GenerationRequest
    ) -> list[GenerationRequest]:
        rows = list(
            (
                await session.scalars(
                    select(GenerationRequest)
                    .where(
                        # History belongs to the customer, so switching domains
                        # never removes older successful logo batches.
                        GenerationRequest.customer_id == anchor.customer_id,
                        GenerationRequest.created_at <= anchor.created_at,
                        GenerationRequest.status == "succeeded",
                    )
                    .order_by(GenerationRequest.created_at.asc(), GenerationRequest.id.asc())
                )
            ).all()
        )
        return rows

    async def _status_dto(
        self,
        session: AsyncSession,
        request: GenerationRequest,
        *,
        include_history: bool = True,
    ) -> GenerationStatusDto:
        rows = await self._successful_batch_window(session, request) if include_history else []
        if request.status == "processing" and request.id not in {row.id for row in rows}:
            rows.append(request)
        # Anchor each image URL to its own successful batch. Using the
        # currently polled request as the anchor rewrites every historical
        # URL after a regeneration and makes an already selected mockup
        # image restart against a moving endpoint.
        batches = [await self._batch_dto(session, row, row.id) for row in rows]
        summary = _safe_summary(request.failure_summary_json)
        return GenerationStatusDto(
            request_id=request.id,
            domain=request.domain,
            domain_label=request.domain_label,
            domain_suffix=cast(DomainSuffix, request.domain_suffix),
            target_count=request.target_count,
            status=request.status,
            error_code=request.error_code,
            failure_summary=summary or None,
            batches=batches,
        )

    async def _execute_candidate(self, job_id: str) -> None:
        """Run one candidate with a bounded retry count and no shared DB transaction."""

        last_error: ProviderError | None = None
        for _ in range(_MAX_PROVIDER_ATTEMPTS):
            try:
                connection, job, provider_request = await self._provider_input(job_id)
                provider = image_provider_for_connection(
                    connection.provider,
                    connection.model_id,
                    self._provider_override,
                )
                result = await self._generate(
                    provider,
                    connection,
                    job,
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
                    connection,
                    job,
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
            job_id, last_error or ProviderError("generation_failed", "Generation failed")
        )

    async def _generate(
        self,
        provider: ImageGenerationProvider,
        connection: ModelConnection,
        job: GenerationCandidateJob,
        request: ImageGenerationRequest,
    ) -> ImageToImageResult:
        if not isinstance(provider, KieGptImageProvider):
            return await provider.generate(connection.api_url or "", request)
        task_id = job.provider_task_id
        if task_id is None:
            task_id = await self._claim_provider_submission(job.id)
        if task_id is None:
            try:
                submission = await self._submit_kie(provider, connection.api_url or "", request)
            except ProviderError as error:
                if error.code != "provider_submission_uncertain":
                    await self._clear_provider_submission_claim(job.id)
                raise
            await self._persist_provider_task_id(job.id, submission.task_id)
            task_id = submission.task_id
        return await provider.wait_for_result(request.api_key, task_id)

    async def _submit_kie(
        self,
        provider: KieGptImageProvider,
        api_url: str,
        request: ImageGenerationRequest,
    ) -> KieTaskSubmission:
        """Submit one independent Kie task without serializing its batch peers."""

        return await provider.submit(api_url, request)

    async def _claim_provider_submission(self, job_id: str) -> str | None:
        async with get_db_context(self._runtime) as session:
            job = await session.get(GenerationCandidateJob, job_id)
            if job is None or job.status == "succeeded":
                raise ProviderError(
                    "provider_task_persistence_failed",
                    "Generation task is no longer writable",
                )
            if job.provider_task_id is not None:
                return cast(str, job.provider_task_id)
            if job.provider_submission_state == "submitting":
                raise ProviderError(
                    "provider_submission_uncertain",
                    "A prior model task submission did not return a recoverable identifier",
                )
            job.provider_submission_state = "submitting"
            job.updated_at = datetime.now(UTC)
            return None

    async def _clear_provider_submission_claim(self, job_id: str) -> None:
        async with get_db_context(self._runtime) as session:
            job = await session.get(GenerationCandidateJob, job_id)
            if job is not None and job.provider_task_id is None:
                job.provider_submission_state = None
                job.updated_at = datetime.now(UTC)

    async def _persist_provider_task_id(self, job_id: str, task_id: str) -> None:
        async with get_db_context(self._runtime) as session:
            job = await session.get(GenerationCandidateJob, job_id)
            if job is None or job.status == "succeeded":
                raise ProviderError(
                    "provider_task_persistence_failed",
                    "Generation task is no longer writable",
                )
            if job.provider_task_id is not None and job.provider_task_id != task_id:
                raise ProviderError(
                    "provider_task_conflict",
                    "Generation task identifier is inconsistent",
                )
            job.provider_task_id = task_id
            job.provider_submission_state = "submitted"
            job.updated_at = datetime.now(UTC)

    async def _provider_input(
        self, job_id: str
    ) -> tuple[ModelConnection, GenerationCandidateJob, ImageGenerationRequest]:
        async with get_db_context(self._runtime) as session:
            job = await session.get(GenerationCandidateJob, job_id)
            if job is None:
                raise LookupError("Generation candidate not found")
            request = await session.get(GenerationRequest, job.request_id)
            if request is None:
                raise LookupError("Generation request not found")
            connection = await session.get(ModelConnection, request.model_connection_id)
            if (
                connection is None
                or connection.version != request.model_connection_version
                or not _image_to_image_verified(connection)
            ):
                raise LookupError("Generation model connection is no longer available")
            snapshot = _safe_snapshot(job.run_snapshot_json)
            ordered_input_snapshot = snapshot.get("input_images")
            generation_mode = snapshot.get("generation_mode")
            reference_snapshot = snapshot.get("reference_images")
            if reference_snapshot is None and isinstance(snapshot.get("reference_image"), dict):
                reference_snapshot = [snapshot["reference_image"]]
            reference_images: list[tuple[bytes, str]] = []
            if isinstance(ordered_input_snapshot, list):
                for image in ordered_input_snapshot:
                    if not isinstance(image, dict) or not isinstance(image.get("asset_id"), str):
                        raise LookupError("Generation input image snapshot is invalid")
                    asset_id = image["asset_id"]
                    role = image.get("role")
                    if role == "user_content_structure":
                        asset, content = await self._assets.read_customer_generation_source(
                            session, asset_id, request.customer_id
                        )
                    elif role == "template_style":
                        asset, content = await self._assets.read_reference_image(session, asset_id)
                    else:
                        raise LookupError("Generation input image role is invalid")
                    if image.get("content_hash") != asset.content_hash:
                        raise LookupError("Generation input image changed")
                    if role == "user_content_structure" and not is_valid_source_image(
                        content, asset.media_type
                    ):
                        raise LookupError("Generation source image is invalid")
                    reference_images.append((content, asset.media_type))
                customer_source_count = sum(
                    1
                    for image in ordered_input_snapshot
                    if isinstance(image, dict)
                    and image.get("role") == "user_content_structure"
                )
                template_reference_count = sum(
                    1
                    for image in ordered_input_snapshot
                    if isinstance(image, dict) and image.get("role") == "template_style"
                )
                try:
                    validate_reference_input_quota(
                        customer_source_count=customer_source_count,
                        template_reference_count=template_reference_count,
                        max_input_images=connection.max_input_images,
                    )
                except ReferenceInputQuotaError as error:
                    raise LookupError(error.code) from error
                if any(
                    not isinstance(image, dict) or image.get("order") != index
                    for index, image in enumerate(ordered_input_snapshot)
                ):
                    raise LookupError("Generation input image order is invalid")
                if bool(request.source_image_asset_id) != any(
                    isinstance(image, dict) and image.get("role") == "user_content_structure"
                    for image in ordered_input_snapshot
                ):
                    raise LookupError("Generation input image snapshot is inconsistent")
            elif job.reference_image_asset_id is None:
                if generation_mode != "text_to_image" or reference_snapshot not in (None, []):
                    raise LookupError("Generation mode snapshot is inconsistent")
            else:
                if generation_mode != "image_to_image" or not isinstance(reference_snapshot, list):
                    raise LookupError("Generation mode snapshot is inconsistent")
                for reference in reference_snapshot:
                    if not isinstance(reference, dict) or not isinstance(
                        reference.get("asset_id"), str
                    ):
                        raise LookupError("Generation reference image snapshot is invalid")
                    asset, content = await self._assets.read_reference_image(
                        session, reference["asset_id"]
                    )
                    if reference.get("content_hash") != asset.content_hash:
                        raise LookupError("Generation reference image changed")
                    reference_images.append((content, asset.media_type))
            prompt = snapshot.get("compiled_prompt")
            if not isinstance(prompt, str) or not prompt:
                raise LookupError("Generation prompt snapshot is unavailable")
            api_key = await self._secrets.read(session, connection.id)
            if not api_key:
                raise LookupError("Generation model credential is unavailable")
            job.status = "running"
            job.attempt_count += 1
            job.updated_at = datetime.now(UTC)
            return (
                connection,
                job,
                ImageGenerationRequest(
                    model_id=connection.model_id,
                    api_key=api_key,
                    prompt=prompt,
                    reference_image=reference_images[0][0] if len(reference_images) == 1 else None,
                    reference_media_type=reference_images[0][1]
                    if len(reference_images) == 1
                    else None,
                    reference_images=tuple(reference_images) if len(reference_images) > 1 else (),
                    max_input_images=connection.max_input_images,
                    output_count=1,
                ),
            )

    async def _persist_success(
        self,
        connection: ModelConnection,
        job: GenerationCandidateJob,
        content: bytes,
        media_type: str,
        provider_http_status: int | None,
        response_image_count: int | None,
        provider_request_id_hash: str | None,
    ) -> None:
        async with get_db_context(self._runtime) as session:
            record = await session.get(GenerationCandidateJob, job.id)
            request = await session.get(GenerationRequest, job.request_id)
            if record is None or request is None or record.status == "succeeded":
                return
            asset = await self._assets.create_generated_logo(
                session,
                content=content,
                media_type=media_type,
                actor_id=request.customer_id,
                trace_id=uuid4().hex,
                source_resource_id=record.id,
            )
            record.status = "succeeded"
            record.result_asset_id = asset.asset_id
            record.error_code = None
            record.updated_at = datetime.now(UTC)
            logo_version_id = uuid4().hex
            session.add(
                LogoVersion(
                    id=logo_version_id,
                    customer_id=request.customer_id,
                    domain=request.domain,
                    generation_request_id=request.id,
                    candidate_job_id=record.id,
                    single_edit_request_id=None,
                    parent_logo_version_id=None,
                    root_logo_version_id=logo_version_id,
                    version_number=1,
                    asset_id=asset.asset_id,
                    created_at=datetime.now(UTC),
                )
            )
            await self._events.record_audit(
                session,
                action="batch_generation.candidate_succeeded",
                resource_type="generation_candidate_job",
                resource_id=record.id,
                actor_id=request.customer_id,
                trace_id=uuid4().hex,
                summary={
                    "provider_http_status": provider_http_status,
                    "response_image_count": response_image_count,
                    "provider_request_id_hash": provider_request_id_hash,
                    "rendering": fixed_rendering_metadata(connection.model_id),
                },
            )

    async def _persist_failure(self, job_id: str, error: ProviderError) -> None:
        async with get_db_context(self._runtime) as session:
            job = await session.get(GenerationCandidateJob, job_id)
            if job is None or job.status == "succeeded":
                return
            request = await session.get(GenerationRequest, job.request_id)
            if request is None:
                return
            job.status = "failed"
            job.error_code = error.code
            job.updated_at = datetime.now(UTC)
            await self._events.record_audit(
                session,
                action="batch_generation.candidate_failed",
                resource_type="generation_candidate_job",
                resource_id=job.id,
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

    async def _create_replenishments(
        self, request_id: str, failed_jobs: list[GenerationCandidateJob]
    ) -> None:
        async with get_db_context(self._runtime) as session:
            request = await session.get(GenerationRequest, request_id)
            if request is None:
                return
            policy_version, policy, context, connection = await self._runtime_policy(
                session, request.policy_version_id, request.source_image_asset_id
            )
            current_max = (
                await session.scalar(
                    select(func.max(GenerationCandidateJob.ordinal)).where(
                        GenerationCandidateJob.request_id == request.id
                    )
                )
            ) or 0
            policy_service = BatchGenerationPolicyService()
            now = datetime.now(UTC)
            for index, failed in enumerate(failed_jobs, start=1):
                failed_snapshot = _safe_snapshot(failed.run_snapshot_json)
                replenishes_ordinal = failed_snapshot.get("replenishes_ordinal")
                visible_ordinal = (
                    replenishes_ordinal
                    if isinstance(replenishes_ordinal, int)
                    else failed.ordinal
                )
                combination = await policy_service.allocate_replenishment_combination(
                    session, policy_version.id, failed.style_id
                )
                session.add(
                    self._candidate_job(
                        request=request,
                        policy=policy,
                        context=context,
                        model_id=connection.model_id,
                        combination=combination,
                        ordinal=current_max + index,
                        now=now,
                        replenishes_ordinal=visible_ordinal,
                    )
                )

    async def _runtime_policy(
        self,
        session: AsyncSession,
        policy_version_id: str | None = None,
        source_image_asset_id: str | None = None,
    ) -> tuple[
        BatchGenerationPolicyVersion,
        BatchPolicyPayload,
        BatchCompileContext,
        ModelConnection,
    ]:
        if policy_version_id is None:
            state = await session.get(BatchGenerationPolicyState, _BATCH_SCENE)
            if state is None or state.active_version_id is None:
                raise BatchGenerationRequestError(
                    "batch_policy_not_published", "请先发布批量生图策略", 409
                )
            policy_version_id = state.active_version_id
        version = await session.get(BatchGenerationPolicyVersion, policy_version_id)
        if version is None:
            raise LookupError("Batch generation policy version not found")
        styles = [
            BatchStyleDto.model_validate(item) for item in json.loads(version.styles_snapshot_json)
        ]
        policy = BatchPolicyPayload(model_connection_id=version.model_connection_id, styles=styles)
        connection = await session.get(ModelConnection, version.model_connection_id)
        asset_ids = {
            asset_id
            for style in styles
            for template in style.templates
            for asset_id in template.reference_images
        }
        assets: dict[str, AssetRecord] = {}
        if asset_ids:
            records = list(
                (
                    await session.scalars(
                        select(AssetRecord).where(AssetRecord.asset_id.in_(asset_ids))
                    )
                ).all()
            )
            assets = {record.asset_id: record for record in records}
        if source_image_asset_id is not None:
            source_asset = await session.get(AssetRecord, source_image_asset_id)
            if (
                source_asset is None
                or source_asset.purpose != "customer_generation_source"
            ):
                raise LookupError("Batch generation source image is unavailable")
            assets[source_asset.asset_id] = source_asset
        context = BatchCompileContext(
            model_connection_id=connection.id if connection else None,
            model_connection_version=connection.version if connection else None,
            image_to_image_verified=_image_to_image_verified(connection),
            assets=assets,
            max_input_images=connection.max_input_images if connection else None,
        )
        validation_errors = validate_batch_policy(policy, context)
        if (
            validation_errors
            or context.model_connection_version != version.model_connection_version
        ):
            raise LookupError("Batch generation policy runtime is unavailable")
        if connection is None:
            raise LookupError("Batch generation model connection is unavailable")
        return version, policy, context, connection

    def _candidate_job(
        self,
        *,
        request: GenerationRequest,
        policy: BatchPolicyPayload,
        context: BatchCompileContext,
        model_id: str,
        combination: BatchTemplateCombination,
        ordinal: int,
        now: datetime,
        replenishes_ordinal: int | None = None,
    ) -> GenerationCandidateJob:
        style = next(item for item in policy.styles if item.id == combination.style_id)
        template = next(item for item in style.templates if item.id == combination.template_id)
        compilation = compile_batch_prompt(
            policy=policy,
            domain=request.domain_label,
            style_id=combination.style_id,
            template_id=combination.template_id,
            context=context,
            user_reference_requirement=request.user_reference_requirement_raw,
            customer_source_present=request.source_image_asset_id is not None,
        )
        source_asset = context.assets.get(request.source_image_asset_id or "")
        input_images: list[dict[str, object]] = []
        if source_asset is not None:
            input_images.append(
                {
                    "order": 0,
                    "role": "user_content_structure",
                    "asset_id": source_asset.asset_id,
                    "version": 1,
                    "content_hash": source_asset.content_hash,
                }
            )
        input_images.extend(
            {
                "order": index + (1 if source_asset is not None else 0),
                "role": "template_style",
                "asset_id": asset_id,
                "version": 1,
                "content_hash": content_hash,
            }
            for index, (asset_id, content_hash) in enumerate(
                zip(
                    compilation.reference_image_asset_ids,
                    compilation.reference_image_content_hashes,
                    strict=True,
                )
            )
        )
        snapshot = {
            "policy_version_id": request.policy_version_id,
            "selected_style_ids": _safe_string_list(request.selected_style_ids_json),
            "style_allocation": _safe_snapshot(request.style_allocation_json),
            "model_connection_id": request.model_connection_id,
            "model_connection_version": request.model_connection_version,
            "style": {"id": style.id, "name": style.name},
            "template": {
                "id": template.id,
                "name": template.name,
                "positive_prompt": template.positive_prompt,
                "negative_prompt": template.negative_prompt,
            },
            "generation_mode": request.generation_mode,
            "provider_generation_mode": (
                "image_to_image" if input_images else "text_to_image"
            ),
            "source_image": (
                {
                    "asset_id": source_asset.asset_id,
                    "version": 1,
                    "content_hash": source_asset.content_hash,
                }
                if source_asset is not None
                else None
            ),
            "user_reference_requirement_raw": request.user_reference_requirement_raw,
            "user_reference_requirement_normalized": request.user_reference_requirement_normalized,
            "requirement_binding": compilation.requirement_binding,
            "input_images": input_images,
            "reference_images": [
                {"asset_id": asset_id, "asset_version": 1, "content_hash": content_hash}
                for asset_id, content_hash in zip(
                    compilation.reference_image_asset_ids,
                    compilation.reference_image_content_hashes,
                    strict=True,
                )
            ],
            "input": {
                "domain": request.domain,
                "domain_label": compilation.normalized_domain,
                "domain_suffix": request.domain_suffix,
                "variables": {
                    "域名": compilation.normalized_domain,
                    "用户参考要求": request.user_reference_requirement_normalized,
                },
            },
            "compiler_version": compilation.compiler_version,
            "compiler_rule_set": compilation.rule_set_version,
            "compiled_prompt": compilation.compiled_prompt,
            "output_constraint": compilation.output_constraint,
            "rendering": fixed_rendering_metadata(model_id),
            "target_count": request.target_count,
            "max_parallelism": request.target_count,
            "replenishment_budget": REPLENISHMENT_BUDGET,
            "provider_max_input_images": context.max_input_images,
            "reference_limit_preflight": {
                "customer_source_count": 1 if source_asset is not None else 0,
                "template_reference_count": len(compilation.reference_image_asset_ids),
                "total": len(input_images),
                "max_input_images": context.max_input_images,
                "passed": True,
            },
        }
        snapshot["replenishes_ordinal"] = replenishes_ordinal
        return GenerationCandidateJob(
            id=uuid4().hex,
            request_id=request.id,
            ordinal=ordinal,
            style_id=combination.style_id,
            template_id=combination.template_id,
            reference_image_asset_id=compilation.reference_image_asset_id,
            source_image_asset_id=request.source_image_asset_id,
            status="pending",
            attempt_count=0,
            run_snapshot_json=json.dumps(
                snapshot, ensure_ascii=True, separators=(",", ":"), sort_keys=True
            ),
            created_at=now,
            updated_at=now,
        )

    async def _request(self, request_id: str) -> GenerationRequest | None:
        async with get_db_context(self._runtime) as session:
            return await session.get(GenerationRequest, request_id)

    async def _recover_running_jobs(self, request_id: str) -> None:
        async with get_db_context(self._runtime) as session:
            rows = list(
                (
                    await session.scalars(
                        select(GenerationCandidateJob).where(
                            GenerationCandidateJob.request_id == request_id,
                            GenerationCandidateJob.status == "running",
                        )
                    )
                ).all()
            )
            for row in rows:
                row.status = "pending"
                row.updated_at = datetime.now(UTC)

    async def _pending_jobs(self, request_id: str) -> list[GenerationCandidateJob]:
        async with get_db_context(self._runtime) as session:
            return list(
                (
                    await session.scalars(
                        select(GenerationCandidateJob)
                        .where(
                            GenerationCandidateJob.request_id == request_id,
                            GenerationCandidateJob.status == "pending",
                        )
                        .order_by(GenerationCandidateJob.ordinal)
                    )
                ).all()
            )

    async def _job_counts(self, request_id: str) -> tuple[int, list[GenerationCandidateJob], int]:
        async with get_db_context(self._runtime) as session:
            rows = list(
                (
                    await session.scalars(
                        select(GenerationCandidateJob).where(
                            GenerationCandidateJob.request_id == request_id
                        )
                    )
                ).all()
            )
            return (
                sum(1 for row in rows if row.status == "succeeded"),
                [row for row in rows if row.status == "failed"],
                len(rows),
            )

    async def _finish(self, request_id: str, status: str, summary: dict[str, Any] | None) -> None:
        async with get_db_context(self._runtime) as session:
            request = await session.get(GenerationRequest, request_id)
            if request is None or request.status in {"succeeded", "failed"}:
                return
            request.status = status
            request.error_code = None if status == "succeeded" else "generation_budget_exhausted"
            request.failure_summary_json = json.dumps(
                summary or {}, ensure_ascii=True, separators=(",", ":")
            )
            request.updated_at = datetime.now(UTC)
            await self._events.record_audit(
                session,
                action=f"batch_generation.{status}",
                resource_type="generation_request",
                resource_id=request.id,
                actor_id=request.customer_id,
                trace_id=uuid4().hex,
                summary={
                    "target_count": request.target_count,
                    "status": status,
                    "success_count": (summary or {}).get("success_count", request.target_count),
                },
            )

    async def _batch_dto(
        self, session: AsyncSession, request: GenerationRequest, anchor_request_id: str
    ) -> GenerationBatchDto:
        logo_rows = list(
            (
                await session.scalars(
                    select(LogoVersion).where(LogoVersion.generation_request_id == request.id)
                )
            ).all()
        )
        logos_by_job = {logo.candidate_job_id: logo for logo in logo_rows}
        visible = await self._visible_slot_jobs(session, request)
        candidates: list[GenerationCandidateSlotDto] = []
        visible_logos: list[LogoVersion] = []
        for slot_index in range(min(request.target_count, 9)):
            job = visible.get(slot_index)
            logo = logos_by_job.get(job.id) if job is not None else None
            if job is not None and job.status == "succeeded" and logo is not None:
                visible_logos.append(logo)
                candidates.append(
                    GenerationCandidateSlotDto(
                        slot_index=slot_index,
                        status="succeeded",
                        logo_version_id=logo.id,
                        image_url=(
                            f"/api/v1/generations/{anchor_request_id}"
                            f"/logo-versions/{logo.id}/image"
                        ),
                    )
                )
                continue
            original = await session.scalar(
                select(GenerationCandidateJob).where(
                    GenerationCandidateJob.request_id == request.id,
                    GenerationCandidateJob.ordinal == slot_index + 1,
                )
            )
            if job is not None and job.status in {"pending", "running"}:
                candidates.append(
                    GenerationCandidateSlotDto(slot_index=slot_index, status="processing")
                )
                continue
            error_code = (job.error_code if job is not None else None) or "retry_in_progress"
            candidates.append(
                GenerationCandidateSlotDto(
                    slot_index=slot_index,
                    status="failed",
                    failure=GenerationCandidateFailureDto(
                        code=error_code, message=_failure_message(error_code)
                    ),
                    retry_token=(
                        self._retry_token(original, slot_index)
                        if original is not None and original.status == "failed"
                        else None
                    ),
                )
            )
        return GenerationBatchDto(
            request_id=request.id,
            domain=request.domain,
            domain_label=request.domain_label,
            domain_suffix=cast(DomainSuffix, request.domain_suffix),
            target_count=request.target_count,
            status=request.status,
            created_at=request.created_at,
            logo_versions=[
                GeneratedLogoVersionDto(
                    id=logo.id,
                    image_url=(
                        f"/api/v1/generations/{anchor_request_id}/logo-versions/{logo.id}/image"
                    ),
                )
                for logo in visible_logos
            ],
            candidates=candidates,
        )

    async def _visible_slot_jobs(
        self, session: AsyncSession, request: GenerationRequest
    ) -> dict[int, GenerationCandidateJob]:
        jobs = list(
            (
                await session.scalars(
                    select(GenerationCandidateJob)
                    .where(GenerationCandidateJob.request_id == request.id)
                    .order_by(GenerationCandidateJob.ordinal)
                )
            ).all()
        )
        visible: dict[int, GenerationCandidateJob] = {}
        for job in jobs:
            replenishes_ordinal = _safe_snapshot(job.run_snapshot_json).get(
                "replenishes_ordinal"
            )
            ordinal_value = (
                replenishes_ordinal if isinstance(replenishes_ordinal, int) else job.ordinal
            )
            slot_index = ordinal_value - 1
            if not 0 <= slot_index < min(request.target_count, 9):
                continue
            current = visible.get(slot_index)
            if current is None or (current.status != "succeeded" and job.status == "succeeded") or current.status != "succeeded" and job.ordinal > current.ordinal:
                visible[slot_index] = job
        return visible

    def _retry_token(self, job: GenerationCandidateJob, slot_index: int) -> str:
        if not self._retry_token_secret:
            raise BatchGenerationRequestError(
                "generation_retry_unavailable", "Generation slot retry unavailable", 503
            )
        snapshot_hash = sha256(job.run_snapshot_json.encode()).hexdigest()
        payload = f"{job.request_id}:{slot_index}:{job.id}:{snapshot_hash}".encode()
        return hmac.new(self._retry_token_secret, payload, "sha256").hexdigest()


def _image_to_image_verified(connection: ModelConnection | None) -> bool:
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


def _safe_snapshot(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_string_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [item for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []


def _safe_summary(value: str) -> dict[str, object]:
    return _safe_snapshot(value)


def _failure_message(code: str) -> str:
    messages = {
        "provider_auth_failed": "Generation service authentication failed.",
        "provider_quota_exhausted": "Generation service quota is unavailable.",
        "generation_configuration_failed": "Generation configuration is unavailable.",
        "retry_in_progress": "This slot is being retried.",
        "timeout": "Generation timed out. Retry this slot.",
        "network_error": "Network error. Retry this slot.",
    }
    return messages.get(code, "This slot failed. Retry this slot.")
