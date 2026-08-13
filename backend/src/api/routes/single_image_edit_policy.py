"""Internal-admin routes for immutable single-image edit strategy versions."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.deps import require_admin
from src.db.session import get_db
from src.models.single_image_edit_policy import SingleImageEditPolicyPayload
from src.services.auth_service import AuthenticatedPrincipal
from src.services.single_image_edit_policy_service import (
    SingleImageEditPolicyService,
    SingleImageEditPolicyValidationError,
)

from pycore.api import success_response
from pycore.api.responses import APIResponse, error_response

router = APIRouter(prefix="/api/v1", tags=["single-image-edit-policy"])


def get_policy_service() -> SingleImageEditPolicyService:
    """Build the stateless single-image policy service for one request."""

    return SingleImageEditPolicyService()


PolicyDependency = Annotated[SingleImageEditPolicyService, Depends(get_policy_service)]
AdminDependency = Annotated[AuthenticatedPrincipal, Depends(require_admin)]
DatabaseDependency = Annotated[AsyncSession, Depends(get_db)]


@router.get("/single-image-edit-policy")
async def get_single_image_edit_policy(
    _: AdminDependency,
    session: DatabaseDependency,
    service: PolicyDependency,
) -> APIResponse:
    """Read the current single-image scene version and a deep-copy draft seed."""

    return success_response(data=(await service.get_policy(session)).model_dump(mode="json"))


@router.get("/single-image-edit-policy/versions")
async def list_single_image_edit_policy_versions(
    _: AdminDependency,
    session: DatabaseDependency,
    service: PolicyDependency,
) -> APIResponse:
    """Read immutable single-image scene history newest first."""

    versions = await service.list_versions(session)
    return success_response(data=[version.model_dump(mode="json") for version in versions])


@router.post(
    "/single-image-edit-policy/publish",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def publish_single_image_edit_policy(
    payload: SingleImageEditPolicyPayload,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: PolicyDependency,
) -> APIResponse | JSONResponse:
    """Atomically validate and activate one immutable single-image scene version."""

    try:
        await service.publish(session, payload, principal.id)
    except SingleImageEditPolicyValidationError as error:
        response, http_status = error_response(
            "单图编辑策略校验失败",
            error_code=error.error_code,
            status_code=422,
            validation_errors=[item.model_dump(mode="json") for item in error.validation_errors],
        )
        return JSONResponse(status_code=http_status, content=response.model_dump(mode="json"))
    return success_response(data={"published": True}, code=201)
