"""Model connection CRUD and controlled image-to-image smoke-test orchestration."""

import json
import os
import re
import stat
import struct
import time
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Timer
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.config import AppSettings
from src.db.models import (
    BatchGenerationPolicyState,
    BatchGenerationPolicyVersion,
    ModelConnection,
    ModelConnectionSecret,
    SingleImageEditPolicyState,
    SingleImageEditPolicyVersion,
)
from src.models.model_connection import (
    CreateModelConnectionRequest,
    ModelCapabilityDto,
    ModelConnectionDto,
    ModelConnectionTestData,
    UpdateModelConnectionRequest,
)
from src.services.event_service import EventService
from src.services.model_provider import (
    PROMPT_OPTIMIZATION_STATUS,
    DiagnosticCaptureStatus,
    DiagnosticImageMediaType,
    ImageGenerationProvider,
    ImageToImageRequest,
    ImageToImageResult,
    ProviderError,
    ProviderOperation,
    ProviderStatusFamily,
    fixed_rendering_metadata,
    image_provider_for_connection,
    provider_adapter_name,
)
from src.services.model_secret_service import ModelConnectionSecretService

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CONTROLLED_IMAGE_SIZE = 1024
_MINIMUM_PROVIDER_IMAGE_SIZE = 15
_DIAGNOSTIC_TTL_SECONDS = 60 * 60
_DIAGNOSTIC_TRACE_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_DIAGNOSTIC_SUFFIXES: dict[DiagnosticImageMediaType, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


class ModelConnectionInUseError(RuntimeError):
    """Raised when a connection is still selected by a current scene policy."""


def _png_chunk(chunk_type: bytes, content: bytes) -> bytes:
    """Build one deterministic PNG chunk for the server-owned smoke asset."""

    return (
        struct.pack(">I", len(content))
        + chunk_type
        + content
        + struct.pack(">I", zlib.crc32(chunk_type + content) & 0xFFFFFFFF)
    )


def _build_controlled_test_image() -> bytes:
    """Return a stable 1024px RGB logo mark, with no browser-provided input."""

    size = _CONTROLLED_IMAGE_SIZE
    center = size // 2
    outer_radius = 336
    inner_radius = 122
    background = b"\xf8\xf9\xfc"
    mark = b"\x19\x2d\x4f"
    raw_rows = bytearray()

    for y in range(size):
        row = bytearray(background * size)
        outer_half_width = outer_radius - abs(y - center)
        if outer_half_width >= 0:
            left = max(0, center - outer_half_width)
            right = min(size, center + outer_half_width)
            row[left * 3 : right * 3] = mark * (right - left)
        inner_half_width = inner_radius - abs(y - center)
        if inner_half_width >= 0:
            left = max(0, center - inner_half_width)
            right = min(size, center + inner_half_width)
            row[left * 3 : right * 3] = background * (right - left)
        raw_rows.extend(b"\x00")
        raw_rows.extend(row)

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        _PNG_SIGNATURE
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw_rows, 9))
        + _png_chunk(b"IEND", b"")
    )


def _png_dimensions(image: bytes) -> tuple[int, int] | None:
    """Read only the PNG IHDR dimensions needed for the preflight check."""

    if image[:8] != _PNG_SIGNATURE or len(image) < 24:
        return None
    chunk_length = struct.unpack(">I", image[8:12])[0]
    if chunk_length != 13 or image[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", image[16:24])
    return (width, height) if width > 0 and height > 0 else None


_CONTROLLED_TEST_IMAGE = _build_controlled_test_image()
_CONTROLLED_TEST_PROMPT = "Generate one minimal logo variation from the supplied reference image."


@dataclass(frozen=True, slots=True)
class CapturedControlledSmokeDiagnostic:
    """Internal-only metadata for a short-lived image available to support tooling."""

    trace_id: str
    path: Path
    media_type: DiagnosticImageMediaType


class ControlledSmokeDiagnosticStore:
    """Keep only one local, restricted smoke-test image outside business asset storage."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = (
            root or Path(__file__).resolve().parents[2] / "data" / "controlled-smoke-diagnostics"
        )

    def prepare_for_test(self) -> bool:
        """Clean all earlier diagnostics before a new controlled provider request."""

        try:
            self._ensure_root()
            for candidate in self._root.iterdir():
                self._unlink_diagnostic(candidate)
        except OSError:
            return False
        return True

    def save(
        self, trace_id: str, image: bytes, media_type: DiagnosticImageMediaType
    ) -> CapturedControlledSmokeDiagnostic | None:
        """Persist one already-validated image under an opaque trace-derived name."""

        if not _DIAGNOSTIC_TRACE_PATTERN.fullmatch(trace_id) or not image:
            return None
        try:
            self._ensure_root()
            target = self._root / f"{trace_id}{_DIAGNOSTIC_SUFFIXES[media_type]}"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(target, flags, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as file:
                    file.write(image)
                os.chmod(target, 0o600)
            except OSError:
                target.unlink(missing_ok=True)
                raise
            expiry_timer = Timer(_DIAGNOSTIC_TTL_SECONDS, self._unlink_diagnostic, args=(target,))
            expiry_timer.daemon = True
            expiry_timer.start()
        except OSError:
            return None
        return CapturedControlledSmokeDiagnostic(
            trace_id=trace_id, path=target, media_type=media_type
        )

    def locate(self, trace_id: str) -> CapturedControlledSmokeDiagnostic | None:
        """Return one unexpired diagnostic for trusted local support tooling only."""

        if not _DIAGNOSTIC_TRACE_PATTERN.fullmatch(trace_id):
            return None
        try:
            self._ensure_root()
            self._remove_expired()
            candidates = [
                candidate
                for candidate in self._root.glob(f"{trace_id}.*")
                if candidate.suffix in _DIAGNOSTIC_SUFFIXES.values()
                and self._is_restricted_file(candidate)
            ]
        except OSError:
            return None
        if len(candidates) != 1:
            return None
        target = candidates[0]
        media_type = next(
            media_type
            for media_type, suffix in _DIAGNOSTIC_SUFFIXES.items()
            if suffix == target.suffix
        )
        return CapturedControlledSmokeDiagnostic(
            trace_id=trace_id, path=target, media_type=media_type
        )

    def locate_latest(self) -> CapturedControlledSmokeDiagnostic | None:
        """Find the sole current diagnostic without exposing it through the product API."""

        try:
            self._ensure_root()
            self._remove_expired()
            candidates = [
                candidate
                for candidate in self._root.iterdir()
                if candidate.suffix in _DIAGNOSTIC_SUFFIXES.values()
                and self._is_restricted_file(candidate)
            ]
        except OSError:
            return None
        if len(candidates) != 1:
            return None
        candidate = candidates[0]
        return self.locate(candidate.stem)

    def _ensure_root(self) -> None:
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._root, 0o700)

    def _remove_expired(self) -> None:
        cutoff = time.time() - _DIAGNOSTIC_TTL_SECONDS
        for candidate in self._root.iterdir():
            try:
                if candidate.stat().st_mtime <= cutoff:
                    self._unlink_diagnostic(candidate)
            except OSError:
                continue

    @staticmethod
    def _is_restricted_file(candidate: Path) -> bool:
        try:
            metadata = candidate.lstat()
        except OSError:
            return False
        if not stat.S_ISREG(metadata.st_mode):
            return False
        if os.name == "nt":
            # Windows inherits directory ACLs and does not represent POSIX 0600
            # through stat mode bits. lstat still rejects links and non-files.
            return True
        return stat.S_IMODE(metadata.st_mode) == 0o600

    @staticmethod
    def _unlink_diagnostic(candidate: Path) -> None:
        try:
            if stat.S_ISREG(candidate.lstat().st_mode):
                candidate.unlink(missing_ok=True)
        except OSError:
            return


def locate_controlled_smoke_diagnostic(trace_id: str) -> CapturedControlledSmokeDiagnostic | None:
    """Locate a trace-owned diagnostic only for the current local support workflow."""

    return ControlledSmokeDiagnosticStore().locate(trace_id)


def locate_latest_controlled_smoke_diagnostic() -> CapturedControlledSmokeDiagnostic | None:
    """Locate the current support-session image after a newly completed real smoke test."""

    return ControlledSmokeDiagnosticStore().locate_latest()


class ModelConnectionService:
    """Persist safe connection metadata and delegate provider-specific work."""

    def __init__(
        self,
        settings: AppSettings,
        events: EventService | None = None,
        provider: ImageGenerationProvider | None = None,
        diagnostics: ControlledSmokeDiagnosticStore | None = None,
    ) -> None:
        self._settings = settings
        self._events = events or EventService()
        self._provider_override = provider
        self._diagnostics = diagnostics or ControlledSmokeDiagnosticStore()

    def _secrets(self) -> ModelConnectionSecretService:
        return ModelConnectionSecretService(self._settings.model_connection_secret_encryption_key)

    async def list(self, session: AsyncSession) -> list[ModelConnectionDto]:
        rows = (
            await session.scalars(
                select(ModelConnection)
                .where(ModelConnection.retired_at.is_(None))
                .order_by(ModelConnection.created_at.desc())
            )
        ).all()
        secrets = self._secrets()
        api_keys = {row.id: await secrets.read(session, row.id) for row in rows}
        return [self._dto(row, api_keys[row.id]) for row in rows]

    async def create(
        self, session: AsyncSession, request: CreateModelConnectionRequest, actor_id: str
    ) -> ModelConnectionDto:
        secrets = self._secrets()
        record = ModelConnection(
            id=uuid4().hex,
            provider=request.provider.strip(),
            model_id=request.model_id.strip(),
            api_url=str(request.api_url),
            region_or_workspace=_optional_text(request.region_or_workspace),
            connection_status="untested",
            verified_capabilities_json="[]",
            max_input_images=request.max_input_images,
            version=1,
            updated_at=datetime.now(UTC),
        )
        session.add(record)
        await session.flush()
        await secrets.replace(session, record.id, request.api_key.strip())
        await self._events.record_audit(
            session,
            action="model_connection.created",
            resource_type="model_connection",
            resource_id=record.id,
            actor_id=actor_id,
            trace_id=uuid4().hex,
            summary={
                "provider": record.provider,
                "model_id": record.model_id,
                "credential_status": "configured",
            },
        )
        await session.flush()
        return self._dto(record, await secrets.read(session, record.id))

    async def update(
        self,
        session: AsyncSession,
        connection_id: str,
        request: UpdateModelConnectionRequest,
        actor_id: str,
    ) -> ModelConnectionDto:
        record = await self._require_connection(session, connection_id)
        record.provider = request.provider.strip()
        record.model_id = request.model_id.strip()
        record.api_url = str(request.api_url)
        record.region_or_workspace = _optional_text(request.region_or_workspace)
        if request.max_input_images is not None:
            record.max_input_images = request.max_input_images
        record.connection_status = "untested"
        record.verified_capabilities_json = "[]"
        record.version += 1
        record.updated_at = datetime.now(UTC)
        secrets = self._secrets()
        if request.api_key and request.api_key.strip():
            await secrets.replace(session, record.id, request.api_key.strip())
        await self._events.record_audit(
            session,
            action="model_connection.updated",
            resource_type="model_connection",
            resource_id=record.id,
            actor_id=actor_id,
            trace_id=uuid4().hex,
            summary={
                "connection_status": record.connection_status,
                "credential_replaced": bool(request.api_key and request.api_key.strip()),
            },
        )
        await session.flush()
        return self._dto(record, await secrets.read(session, record.id))

    async def delete(self, session: AsyncSession, connection_id: str, actor_id: str) -> None:
        record = await self._require_connection(session, connection_id)
        batch_policy_id = await session.scalar(
            select(BatchGenerationPolicyState.active_version_id)
            .join(
                BatchGenerationPolicyVersion,
                BatchGenerationPolicyVersion.id == BatchGenerationPolicyState.active_version_id,
            )
            .where(BatchGenerationPolicyVersion.model_connection_id == connection_id)
            .limit(1)
        )
        single_image_policy_id = await session.scalar(
            select(SingleImageEditPolicyState.active_version_id)
            .join(
                SingleImageEditPolicyVersion,
                SingleImageEditPolicyVersion.id == SingleImageEditPolicyState.active_version_id,
            )
            .where(SingleImageEditPolicyVersion.model_connection_id == connection_id)
            .limit(1)
        )
        if batch_policy_id is not None or single_image_policy_id is not None:
            raise ModelConnectionInUseError("Model connection is used by a current policy")
        secret = await session.get(ModelConnectionSecret, connection_id)
        if secret is not None:
            await session.delete(secret)
        record.retired_at = datetime.now(UTC)
        record.updated_at = record.retired_at
        await self._events.record_audit(
            session,
            action="model_connection.retired",
            resource_type="model_connection",
            resource_id=connection_id,
            actor_id=actor_id,
            trace_id=uuid4().hex,
            summary={"retired": True, "credential_removed": secret is not None},
        )

    async def test(
        self, session: AsyncSession, connection_id: str, actor_id: str
    ) -> ModelConnectionTestData:
        record = await self._require_connection(session, connection_id)
        trace_id = uuid4().hex
        started = time.monotonic()
        secret = self._secrets()
        api_key = await secret.read(session, record.id)
        if (
            not api_key
            or not record.model_id.strip()
            or not self._settings.enable_real_model_smoke_tests
        ):
            return await self._fallback(
                session, record, actor_id, trace_id, "external_test_not_enabled", api_key
            )
        diagnostic_storage_ready = self._diagnostics.prepare_for_test()
        dimensions = _png_dimensions(_CONTROLLED_TEST_IMAGE)
        if dimensions is None or min(dimensions) < _MINIMUM_PROVIDER_IMAGE_SIZE:
            return await self._failed_test(
                session,
                record,
                actor_id,
                trace_id,
                "controlled_test_asset_invalid",
                None,
                "受控测试图片不符合要求，请联系管理员后重试。",
                started,
                api_key,
            )
        try:
            provider = image_provider_for_connection(
                record.provider,
                record.model_id,
                self._provider_override,
            )
            result = await provider.image_to_image(
                record.api_url,
                ImageToImageRequest(
                    model_id=record.model_id,
                    api_key=api_key,
                    reference_image=_CONTROLLED_TEST_IMAGE,
                    reference_media_type="image/png",
                    prompt=_CONTROLLED_TEST_PROMPT,
                    output_count=1,
                ),
            )
        except ProviderError as error:
            return await self._failed_test(
                session,
                record,
                actor_id,
                trace_id,
                error.code,
                error.http_status_family,
                _message_for_provider_error(error.code),
                started,
                api_key,
                provider_http_status=error.provider_http_status,
                response_image_count=error.response_image_count,
                provider_request_id_hash=error.provider_request_id_hash,
                provider_operation=error.provider_operation,
            )
        diagnostic_capture_status = self._persist_diagnostic(
            trace_id, result, diagnostic_storage_ready
        )
        duration_ms = _duration_ms(started)
        error_code = "diagnostic_capture_failed" if diagnostic_capture_status == "failed" else None
        now = datetime.now(UTC)
        record.connection_status = "verified"
        record.updated_at = now
        record.verified_capabilities_json = json.dumps(
            [
                {
                    "capability": "image_to_image",
                    "verified": True,
                    "verification_mode": "real",
                    "verified_at": now.isoformat(),
                }
            ]
        )
        await self._audit_test(
            session,
            record,
            actor_id,
            trace_id,
            "verified",
            error_code,
            None,
            duration_ms,
            result.provider_request_id_hash,
            result.provider_http_status,
            result.response_image_count,
            diagnostic_capture_status,
        )
        await session.flush()
        return ModelConnectionTestData(
            connection=self._dto(record, api_key),
            result="verified",
            message="真实图生图测试通过。",
            trace_id=trace_id,
            provider_http_status=result.provider_http_status,
            response_image_count=result.response_image_count,
            duration_ms=duration_ms,
            diagnostic_capture_status=diagnostic_capture_status,
            error_code=error_code,
        )

    async def _fallback(
        self,
        session: AsyncSession,
        record: ModelConnection,
        actor_id: str,
        trace_id: str,
        reason: str,
        api_key: str | None,
    ) -> ModelConnectionTestData:
        record.connection_status = "fallback_unverified"
        record.verified_capabilities_json = "[]"
        record.updated_at = datetime.now(UTC)
        await self._audit_test(
            session,
            record,
            actor_id,
            trace_id,
            "fallback_unverified",
            reason,
            None,
            0,
            None,
            None,
            None,
            "not_attempted",
        )
        await session.flush()
        return ModelConnectionTestData(
            connection=self._dto(record, api_key),
            result="fallback_unverified",
            message="未满足真实测试条件，连接尚未验证图生图能力。",
            trace_id=trace_id,
            error_code=reason,
            duration_ms=0,
            diagnostic_capture_status="not_attempted",
        )

    async def _failed_test(
        self,
        session: AsyncSession,
        record: ModelConnection,
        actor_id: str,
        trace_id: str,
        error_code: str,
        provider_status_family: ProviderStatusFamily | None,
        message: str,
        started: float,
        api_key: str,
        *,
        provider_http_status: int | None = None,
        response_image_count: int | None = None,
        provider_request_id_hash: str | None = None,
        provider_operation: ProviderOperation | None = None,
    ) -> ModelConnectionTestData:
        """Persist a safe real-test failure without retaining supplier diagnostics."""

        record.connection_status = "failed"
        record.verified_capabilities_json = "[]"
        record.updated_at = datetime.now(UTC)
        duration_ms = _duration_ms(started)
        await self._audit_test(
            session,
            record,
            actor_id,
            trace_id,
            "failed",
            error_code,
            provider_status_family,
            duration_ms,
            provider_request_id_hash,
            provider_http_status,
            response_image_count,
            "not_attempted",
            provider_operation,
        )
        await session.flush()
        return ModelConnectionTestData(
            connection=self._dto(record, api_key),
            result="failed",
            message=message,
            trace_id=trace_id,
            error_code=error_code,
            provider_status_family=provider_status_family,
            provider_http_status=provider_http_status,
            response_image_count=response_image_count,
            duration_ms=duration_ms,
            diagnostic_capture_status="not_attempted",
        )

    def _persist_diagnostic(
        self,
        trace_id: str,
        result: ImageToImageResult,
        storage_ready: bool,
    ) -> DiagnosticCaptureStatus:
        """Write only the adapter-validated image and retain no supplier URL or response body."""

        if result.diagnostic_capture_status != "captured":
            return result.diagnostic_capture_status
        if (
            not storage_ready
            or result.diagnostic_image is None
            or result.diagnostic_media_type is None
        ):
            return "failed"
        return (
            "captured"
            if self._diagnostics.save(
                trace_id, result.diagnostic_image, result.diagnostic_media_type
            )
            else "failed"
        )

    def locate_diagnostic(self, trace_id: str) -> CapturedControlledSmokeDiagnostic | None:
        """Expose an internal-only locator for the current support-session image check."""

        return self._diagnostics.locate(trace_id)

    async def _audit_test(
        self,
        session: AsyncSession,
        record: ModelConnection,
        actor_id: str,
        trace_id: str,
        result: str,
        error_code: str | None,
        provider_status_family: ProviderStatusFamily | None,
        duration_ms: int,
        request_id_hash: str | None,
        provider_http_status: int | None,
        response_image_count: int | None,
        diagnostic_capture_status: DiagnosticCaptureStatus,
        provider_operation: ProviderOperation | None = None,
    ) -> None:
        await self._events.record_audit(
            session,
            action="model_connection.tested",
            resource_type="model_connection",
            resource_id=record.id,
            actor_id=actor_id,
            trace_id=trace_id,
            summary={
                "adapter": provider_adapter_name(record.provider, record.model_id),
                "result": result,
                "error_code": error_code,
                "provider_status_family": provider_status_family,
                "provider_http_status": provider_http_status,
                "response_image_count": response_image_count,
                "provider_operation": provider_operation,
                "duration_ms": duration_ms,
                "provider_request_id_hash": request_id_hash,
                "diagnostic_capture_status": diagnostic_capture_status,
                "rendering": fixed_rendering_metadata(record.model_id),
                "prompt_optimization_status": PROMPT_OPTIMIZATION_STATUS,
            },
        )

    async def _require_connection(
        self, session: AsyncSession, connection_id: str
    ) -> ModelConnection:
        record = await session.get(ModelConnection, connection_id)
        if record is None or record.retired_at is not None:
            raise LookupError("Model connection not found")
        return record

    @staticmethod
    def _dto(record: ModelConnection, api_key: str | None) -> ModelConnectionDto:
        capabilities = [
            ModelCapabilityDto.model_validate(item)
            for item in json.loads(record.verified_capabilities_json)
        ]
        return ModelConnectionDto(
            id=record.id,
            provider=record.provider,
            model_id=record.model_id,
            max_input_images=record.max_input_images,
            api_url=record.api_url or "",
            region_or_workspace=record.region_or_workspace,
            credential_status="configured" if api_key else "missing",
            api_key_masked=mask_api_key(api_key) if api_key else None,
            connection_status=record.connection_status,
            verified_capabilities=capabilities,
            version=record.version,
            updated_at=record.updated_at,
        )


def _optional_text(value: str | None) -> str | None:
    """Normalize whitespace-only optional form values to null."""

    return value.strip() if value and value.strip() else None


def _duration_ms(started: float) -> int:
    """Return an integer elapsed duration suitable for safe diagnostic metadata."""

    return round((time.monotonic() - started) * 1000)


def mask_api_key(api_key: str) -> str:
    """Return the approved non-reversible display summary for an API Key."""

    return f"{api_key[:3]}******{api_key[-3:]}" if len(api_key) > 6 else "******"


def _message_for_provider_error(error_code: str) -> str:
    """Map normalized adapter failures to UI-safe controlled-test guidance."""

    if error_code == "provider_validation_failed":
        return "上游拒绝了请求参数。系统已按模型版本选择参数，请确认模型已开通且 API 地址与模型 ID 属于同一区域。"
    if error_code == "provider_auth_failed":
        return "模型服务拒绝了连接凭据，请检查 API Key 与账号权限。"
    if error_code == "provider_rate_limited":
        return "模型服务当前限流，请稍后重试。"
    if error_code == "provider_quota_exhausted":
        return "模型服务账户额度不足，请充值或调整账户额度后重试。"
    if error_code == "provider_unavailable":
        return "模型服务暂不可用，请稍后重试。"
    return "真实图生图测试失败，请检查模型配置与账号状态。"
