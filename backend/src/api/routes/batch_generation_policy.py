"""Internal-admin routes for batch strategy versions and their reference images."""

from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.deps import require_admin
from src.db.models import AssetRecord
from src.db.session import get_db
from src.models.batch_generation_policy import BatchPolicyPayload
from src.services.asset_service import AssetService, LocalFallbackAssetStorage
from src.services.auth_service import AuthenticatedPrincipal
from src.services.batch_generation_policy_service import (
    BatchGenerationPolicyService,
    BatchPolicyValidationError,
)
from src.services.event_service import EventService

from pycore.api import success_response
from pycore.api.responses import APIResponse, error_response

router = APIRouter(prefix="/api/v1", tags=["batch-generation-policy"])

_MAX_REFERENCE_IMAGE_BYTES = 12 * 1024 * 1024


def get_policy_service() -> BatchGenerationPolicyService:
    """Build the stateless policy service for one request."""

    return BatchGenerationPolicyService()


def get_asset_service(request: Request) -> AssetService:
    """Build storage from application configuration without exposing its resolved path."""

    return AssetService(LocalFallbackAssetStorage(request.app.state.settings.asset_root), EventService())


PolicyDependency = Annotated[BatchGenerationPolicyService, Depends(get_policy_service)]
AssetDependency = Annotated[AssetService, Depends(get_asset_service)]
AdminDependency = Annotated[AuthenticatedPrincipal, Depends(require_admin)]
DatabaseDependency = Annotated[AsyncSession, Depends(get_db)]
OptionalBatchPolicyBody = Annotated[BatchPolicyPayload | None, Body()]


@router.post("/model-strategy-assets/reference-images", status_code=status.HTTP_201_CREATED)
async def upload_reference_image(
    file: UploadFile,
    principal: AdminDependency,
    session: DatabaseDependency,
    assets: AssetDependency,
) -> APIResponse:
    """Store one immutable template reference image using the local fallback asset backend."""

    content = await file.read()
    if not content or len(content) > _MAX_REFERENCE_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail="Reference image is invalid")
    media_type = _detect_reference_image_media_type(content)
    if media_type is None:
        raise HTTPException(status_code=422, detail="Reference image must be JPEG, PNG, or WebP")
    record = await assets.create_reference_image(
        session,
        content=content,
        media_type=media_type,
        original_filename=_safe_filename(file.filename),
        actor_id=principal.id,
        trace_id=uuid4().hex,
    )
    return success_response(data=_asset_dto(record), code=201)


@router.get("/model-strategy-assets")
async def list_reference_images(
    _: AdminDependency,
    session: DatabaseDependency,
    assets: AssetDependency,
    ids: Annotated[list[str] | None, Query()] = None,
) -> APIResponse:
    """Return only metadata for explicitly requested strategy-reference asset IDs."""

    records = await assets.list_reference_images(session, ids or [])
    return success_response(data=[_asset_dto(record) for record in records])


@router.get("/model-strategy-assets/reference-images/{asset_id}/content")
async def read_reference_image_content(
    asset_id: str,
    _: AdminDependency,
    session: DatabaseDependency,
    assets: AssetDependency,
) -> Response:
    """Return protected reference bytes without exposing their storage address."""

    try:
        record, content = await assets.read_reference_image(session, asset_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Reference image not found") from error
    return Response(
        content=content,
        media_type=record.media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/batch-generation-policy")
async def get_batch_generation_policy(
    _: AdminDependency, session: DatabaseDependency, service: PolicyDependency
) -> APIResponse:
    """Read the current batch scene version and a deep-copy draft seed."""

    return success_response(data=(await service.get_policy(session)).model_dump(mode="json"))


@router.put("/batch-generation-policy/draft", status_code=status.HTTP_200_OK)
async def save_batch_generation_policy_draft(
    payload: BatchPolicyPayload,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: PolicyDependency,
) -> APIResponse:
    """Persist the editor draft without changing the active runtime version."""

    saved_at = await service.save_draft(session, payload, principal.id)
    return success_response(data={"draft_saved": True, "saved_at": saved_at})


@router.get("/batch-generation-policy/versions")
async def list_batch_generation_policy_versions(
    _: AdminDependency, session: DatabaseDependency, service: PolicyDependency
) -> APIResponse:
    """Read immutable batch scene history newest first."""

    versions = await service.list_versions(session)
    return success_response(data=[version.model_dump(mode="json") for version in versions])


@router.post(
    "/batch-generation-policy/publish",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def publish_batch_generation_policy(
    principal: AdminDependency,
    session: DatabaseDependency,
    service: PolicyDependency,
    payload: OptionalBatchPolicyBody = None,
) -> APIResponse | JSONResponse:
    """Atomically validate and activate the saved draft.

    A body is accepted for backward compatibility with older internal clients; it is
    persisted as the draft before being published in the same transaction.
    """

    try:
        if payload is not None:
            await service.save_draft(session, payload, principal.id)
        await service.publish_draft(session, principal.id)
    except BatchPolicyValidationError as error:
        response, http_status = error_response(
            "批量生图策略校验失败",
            error_code=error.error_code,
            status_code=422,
            validation_errors=[item.model_dump(mode="json") for item in error.validation_errors],
        )
        return JSONResponse(status_code=http_status, content=response.model_dump(mode="json"))
    return success_response(data={"published": True}, code=201)


def _asset_dto(record: AssetRecord) -> dict[str, object]:
    """Map an internal immutable asset record to the public metadata contract."""

    asset = record
    return {
        "id": asset.asset_id,
        "filename": asset.original_filename or "reference-image",
        "mime_type": asset.media_type,
        "size_bytes": asset.size,
        "content_hash": asset.content_hash,
        "version": 1,
        "created_at": asset.created_at,
    }


def _detect_reference_image_media_type(content: bytes) -> str | None:
    """Trust only server-recognized raster signatures, never the browser-provided content type."""

    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _safe_filename(value: str | None) -> str:
    """Return a display filename without allowing browser-provided path segments."""

    candidate = Path(value or "reference-image").name.strip()
    return candidate[:255] or "reference-image"
