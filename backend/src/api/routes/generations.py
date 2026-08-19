"""Customer batch-generation endpoints with server-owned execution state."""

from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, Response, UploadFile, status
from fastapi import Path as ApiPath
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.deps import require_customer
from src.db.models import AssetRecord
from src.db.session import get_db
from src.models.generation import (
    BatchGenerationRequestDto,
    GenerationSlotRetryRequestDto,
    LatestSuccessfulGenerationDto,
    SingleImageEditRequestDto,
)
from src.services.asset_service import (
    AssetService,
    LocalFallbackAssetStorage,
    is_valid_source_image,
)
from src.services.auth_service import AuthenticatedPrincipal
from src.services.batch_generation_service import (
    BatchGenerationRequestError,
    BatchGenerationService,
)
from src.services.event_service import EventService
from src.services.single_image_edit_service import (
    SingleImageEditRequestError,
    SingleImageEditService,
)

from pycore.api import success_response
from pycore.api.responses import APIResponse, error_response

router = APIRouter(prefix="/api/v1/generations", tags=["generations"])
source_asset_router = APIRouter(prefix="/api/v1", tags=["generation-source-assets"])


def get_generation_service(request: Request) -> BatchGenerationService:
    """Keep one worker coordinator per application so polling cannot duplicate jobs."""

    service = getattr(request.app.state, "batch_generation_service", None)
    if service is None:
        settings = request.app.state.settings
        service = BatchGenerationService(
            request.app.state.database_runtime,
            settings.asset_root,
            settings.model_connection_secret_encryption_key,
            provider=getattr(request.app.state, "batch_generation_provider", None),
            retry_token_secret=settings.auth_session_secret,
        )
        request.app.state.batch_generation_service = service
    return service


def get_customer_asset_service(request: Request) -> AssetService:
    return AssetService(
        LocalFallbackAssetStorage(request.app.state.settings.asset_root), EventService()
    )


CustomerDependency = Annotated[AuthenticatedPrincipal, Depends(require_customer)]
DatabaseDependency = Annotated[AsyncSession, Depends(get_db)]
ServiceDependency = Annotated[BatchGenerationService, Depends(get_generation_service)]
CustomerAssetDependency = Annotated[AssetService, Depends(get_customer_asset_service)]

_MAX_SOURCE_IMAGE_BYTES = 10 * 1024 * 1024
_IMMUTABLE_CUSTOMER_IMAGE_CACHE_CONTROL = "private, max-age=900, must-revalidate"


def get_single_image_edit_service(request: Request) -> SingleImageEditService:
    """Keep one recoverable single-edit coordinator per application."""

    service = getattr(request.app.state, "single_image_edit_service", None)
    if service is None:
        settings = request.app.state.settings
        service = SingleImageEditService(
            request.app.state.database_runtime,
            settings.asset_root,
            settings.model_connection_secret_encryption_key,
            provider=getattr(request.app.state, "single_image_edit_provider", None),
        )
        request.app.state.single_image_edit_service = service
    return service


SingleEditServiceDependency = Annotated[
    SingleImageEditService, Depends(get_single_image_edit_service)
]


def _request_error_response(error: BatchGenerationRequestError) -> JSONResponse:
    body, http_status = error_response(
        str(error), error_code=error.code, status_code=error.status_code
    )
    return JSONResponse(status_code=http_status, content=body.model_dump())


def _single_edit_error_response(error: SingleImageEditRequestError) -> JSONResponse:
    body, http_status = error_response(
        str(error), error_code=error.code, status_code=error.status_code
    )
    return JSONResponse(status_code=http_status, content=body.model_dump())


@router.post("/batch", status_code=status.HTTP_202_ACCEPTED, response_model=None)
async def create_batch_generation(
    payload: BatchGenerationRequestDto,
    principal: CustomerDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse | JSONResponse:
    """Accept structured domain input, commit it, then start recoverable execution."""

    try:
        accepted = await service.accept(
            session,
            principal.id,
            payload.domain_label,
            payload.domain_suffix,
            payload.source_image_asset_id,
            payload.user_reference_requirement,
        )
    except BatchGenerationRequestError as error:
        return _request_error_response(error)
    await session.commit()
    service.schedule(accepted.request_id)
    return success_response(data=accepted.model_dump(mode="json"), code=status.HTTP_202_ACCEPTED)


@router.post(
    "/batch/{request_id}/slots/{slot_index}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=None,
)
async def retry_batch_generation_slot(
    payload: GenerationSlotRetryRequestDto,
    request_id: str,
    slot_index: Annotated[int, ApiPath(ge=0, le=8)],
    principal: CustomerDependency,
    service: ServiceDependency,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
    ],
) -> APIResponse | JSONResponse:
    """Retry one failed stable slot from its immutable server-side snapshot."""

    try:
        accepted = await service.retry_failed_slot(
            principal.id, request_id, slot_index, payload.retry_token, idempotency_key
        )
    except BatchGenerationRequestError as error:
        return _request_error_response(error)
    service.schedule_slot_retry(request_id, slot_index)
    return success_response(
        data=accepted.model_dump(mode="json"), code=status.HTTP_202_ACCEPTED
    )


@source_asset_router.post(
    "/generation-source-assets", status_code=status.HTTP_201_CREATED, response_model=None
)
async def upload_generation_source_asset(
    file: UploadFile,
    principal: CustomerDependency,
    session: DatabaseDependency,
    assets: CustomerAssetDependency,
) -> APIResponse | JSONResponse:
    """Accept one customer-owned raster source without exposing storage details."""

    content = await file.read(_MAX_SOURCE_IMAGE_BYTES + 1)
    media_type = _detect_source_image_media_type(content)
    suffix = Path(file.filename or "").suffix.lower()
    expected_suffixes = {"image/png": {".png"}, "image/jpeg": {".jpg", ".jpeg"}, "image/webp": {".webp"}}
    declared_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if (
        not content
        or len(content) > _MAX_SOURCE_IMAGE_BYTES
        or media_type is None
        or declared_type != media_type
        or suffix not in expected_suffixes.get(media_type, set())
        or not is_valid_source_image(content, media_type)
    ):
        body, http_status = error_response(
            "视觉参考图片无效，请上传不超过 10 MB 的 PNG、JPEG 或 WebP。",
            error_code="invalid_source_image",
            status_code=422,
        )
        return JSONResponse(status_code=http_status, content=body.model_dump(mode="json"))
    record = await assets.create_customer_generation_source(
        session,
        content=content,
        media_type=media_type,
        actor_id=principal.id,
        trace_id=uuid4().hex,
        original_filename=_safe_filename(file.filename),
    )
    return success_response(data=_asset_dto(record), code=201)


@source_asset_router.get("/generation-source-assets/{asset_id}/content", response_model=None)
async def read_generation_source_asset_content(
    asset_id: str,
    principal: CustomerDependency,
    session: DatabaseDependency,
    assets: CustomerAssetDependency,
) -> Response | JSONResponse:
    """Return source bytes only to the owning customer."""

    try:
        record, content = await assets.read_customer_generation_source(
            session, asset_id, principal.id
        )
    except LookupError:
        body, http_status = error_response(
            "视觉参考图片不存在", error_code="source_image_not_found", status_code=404
        )
        return JSONResponse(status_code=http_status, content=body.model_dump(mode="json"))
    return Response(
        content=content,
        media_type=record.media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/single-edit", status_code=status.HTTP_202_ACCEPTED, response_model=None)
async def create_single_image_edit(
    payload: SingleImageEditRequestDto,
    principal: CustomerDependency,
    session: DatabaseDependency,
    service: SingleEditServiceDependency,
) -> APIResponse | JSONResponse:
    """Accept one edit from the server-owned latest version, then execute it."""

    try:
        accepted = await service.accept(
            session,
            principal.id,
            payload.source_version_id,
            payload.edit_instruction,
        )
    except SingleImageEditRequestError as error:
        return _single_edit_error_response(error)
    await session.commit()
    service.schedule(accepted.request_id)
    return success_response(data=accepted.model_dump(mode="json"), code=status.HTTP_202_ACCEPTED)


@router.get("/single-edit/{request_id}", response_model=None)
async def get_single_image_edit_status(
    request_id: str,
    principal: CustomerDependency,
    service: SingleEditServiceDependency,
) -> APIResponse | JSONResponse:
    """Return one run plus the server-owned current/previous version window."""

    try:
        result = await service.status_for_customer(principal.id, request_id)
    except SingleImageEditRequestError as error:
        return _single_edit_error_response(error)
    return success_response(data=result.model_dump(mode="json"))


@router.get("/logo-versions/{logo_version_id}/single-edit-context", response_model=None)
async def get_single_image_edit_context(
    logo_version_id: str,
    principal: CustomerDependency,
    service: SingleEditServiceDependency,
) -> APIResponse | JSONResponse:
    """Resolve a refresh-safe edit chain without exposing versions outside its two-item window."""

    try:
        result = await service.context_for_customer(principal.id, logo_version_id)
    except SingleImageEditRequestError as error:
        return _single_edit_error_response(error)
    return success_response(data=result.model_dump(mode="json"))


@router.get("/logo-versions/{logo_version_id}/single-edit-image", response_model=None)
async def get_single_image_edit_image(
    logo_version_id: str,
    principal: CustomerDependency,
    service: SingleEditServiceDependency,
    thumbnail: bool = Query(False),
) -> Response | JSONResponse:
    """Read a customer-owned image only while it is in the chain's two-version window."""

    try:
        media_type, content = await service.read_version_image(
            principal.id, logo_version_id, thumbnail=thumbnail
        )
    except SingleImageEditRequestError as error:
        return _single_edit_error_response(error)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/latest-successful", response_model=None)
async def get_latest_successful_generation(
    principal: CustomerDependency,
    service: ServiceDependency,
) -> APIResponse:
    """Return the latest successful generation and its complete customer history."""

    latest = await service.latest_successful_for_customer(principal.id)
    data = LatestSuccessfulGenerationDto(latest=latest)
    return success_response(data=data.model_dump(mode="json"))


@router.get("/{request_id}", response_model=None)
async def get_generation_status(
    request_id: str,
    principal: CustomerDependency,
    service: ServiceDependency,
    include_history: bool = Query(True),
) -> APIResponse | JSONResponse:
    """Return request status and, when requested, complete successful history."""

    try:
        result = await service.status_for_customer(
            principal.id, request_id, include_history=include_history
        )
    except BatchGenerationRequestError as error:
        return _request_error_response(error)
    return success_response(data=result.model_dump(mode="json"))


@router.get(
    "/{window_anchor_request_id}/logo-versions/{logo_version_id}/image", response_model=None
)
async def get_logo_image(
    window_anchor_request_id: str,
    logo_version_id: str,
    principal: CustomerDependency,
    service: ServiceDependency,
    thumbnail: bool = Query(False),
) -> Response | JSONResponse:
    """Read an image only through the authenticated customer's successful history."""

    try:
        media_type, content = await service.read_logo_image(
            principal.id, window_anchor_request_id, logo_version_id, thumbnail=thumbnail
        )
    except BatchGenerationRequestError as error:
        return _request_error_response(error)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": _IMMUTABLE_CUSTOMER_IMAGE_CACHE_CONTROL},
    )


def _asset_dto(asset: AssetRecord) -> dict[str, object]:
    return {
        "id": asset.asset_id,
        "filename": asset.original_filename or "generation-source",
        "mime_type": asset.media_type,
        "size_bytes": asset.size,
        "content_hash": asset.content_hash,
        "version": 1,
        "created_at": asset.created_at,
    }


def _safe_filename(value: str | None) -> str:
    candidate = Path(value or "generation-source").name.strip()
    return candidate[:255] or "generation-source"


def _detect_source_image_media_type(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return None
