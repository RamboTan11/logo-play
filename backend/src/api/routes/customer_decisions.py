"""Customer saved Logo, adoption, task, and protected snapshot endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.deps import require_customer_session
from src.db.session import get_db
from src.models.customer_decision import AdoptLogoRequestDto, SaveLogoRequestDto, UpdateSavedLogoRequestDto
from src.services.auth_service import AuthenticatedPrincipal
from src.services.customer_decision_service import (
    CustomerDecisionError,
    CustomerDecisionService,
    DecisionResult,
)

from pycore.api import success_response
from pycore.api.responses import APIResponse, error_response

router = APIRouter(prefix="/api/v1", tags=["customer-decisions"])

CustomerDependency = Annotated[
    AuthenticatedPrincipal, Depends(require_customer_session)
]
DatabaseDependency = Annotated[AsyncSession, Depends(get_db)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key")]


def get_customer_decision_service(request: Request) -> CustomerDecisionService:
    service = getattr(request.app.state, "customer_decision_service", None)
    if service is None:
        service = CustomerDecisionService(request.app.state.settings.asset_root)
        request.app.state.customer_decision_service = service
    return service


ServiceDependency = Annotated[
    CustomerDecisionService, Depends(get_customer_decision_service)
]


def _error_response(error: CustomerDecisionError) -> JSONResponse:
    body, http_status = error_response(
        str(error), error_code=error.code, status_code=error.status_code
    )
    return JSONResponse(status_code=http_status, content=body.model_dump())


def _decision_response(result: DecisionResult) -> JSONResponse:
    if result.error_code is not None:
        body, http_status = error_response(
            result.message or "Request failed",
            error_code=result.error_code,
            status_code=result.status_code,
        )
        return JSONResponse(status_code=http_status, content=body.model_dump())
    body = success_response(data=result.data or {}, code=result.status_code)
    return JSONResponse(status_code=result.status_code, content=body.model_dump())


@router.post("/saved-logos", response_model=None)
async def save_logo(
    payload: SaveLogoRequestDto,
    idempotency_key: IdempotencyKey,
    principal: CustomerDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> JSONResponse:
    try:
        result = await service.save_logo(
            session,
            customer_id=principal.id,
            logo_version_id=payload.logo_version_id,
            idempotency_key=idempotency_key,
        )
    except CustomerDecisionError as error:
        return _error_response(error)
    return _decision_response(result)


@router.get("/saved-logos", response_model=None)
async def list_saved_logos(
    principal: CustomerDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> JSONResponse:
    result = await service.list_saved_logos(session, principal.id)
    body = success_response(data=result.model_dump(mode="json"))
    return JSONResponse(
        content=body.model_dump(mode="json"),
        headers={"Cache-Control": "private, no-store", "Pragma": "no-cache"},
    )


@router.patch("/saved-logos/{saved_logo_id}", response_model=None)
async def update_saved_logo(
    saved_logo_id: str,
    payload: UpdateSavedLogoRequestDto,
    idempotency_key: IdempotencyKey,
    principal: CustomerDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> JSONResponse:
    try:
        result = await service.update_saved_logo(
            session,
            customer_id=principal.id,
            saved_logo_id=saved_logo_id,
            logo_version_id=payload.logo_version_id,
            idempotency_key=idempotency_key,
        )
    except CustomerDecisionError as error:
        return _error_response(error)
    return _decision_response(result)


@router.get("/saved-logos/{saved_logo_id}/image/content", response_model=None)
async def get_saved_logo_image(
    saved_logo_id: str,
    principal: CustomerDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
    thumbnail: bool = Query(False),
) -> Response | JSONResponse:
    try:
        media_type, content = await service.read_saved_logo(
            session, principal.id, saved_logo_id, thumbnail=thumbnail
        )
    except CustomerDecisionError as error:
        return _error_response(error)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/design-tasks/adopt", response_model=None)
async def adopt_logo(
    payload: AdoptLogoRequestDto,
    idempotency_key: IdempotencyKey,
    principal: CustomerDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> JSONResponse:
    try:
        result = await service.adopt_logo(
            session,
            customer_id=principal.id,
            logo_version_id=payload.logo_version_id,
            adoption_suggestion=payload.adoption_suggestion,
            confirm_replace_active_task=payload.confirm_replace_active_task,
            idempotency_key=idempotency_key,
        )
    except CustomerDecisionError as error:
        return _error_response(error)
    return _decision_response(result)


@router.get("/my/tasks", response_model=None)
async def list_my_tasks(
    principal: CustomerDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse:
    result = await service.list_tasks(session, principal.id)
    return success_response(data=result.model_dump(mode="json"))


@router.get("/my/tasks/{task_id}", response_model=None)
async def get_my_task(
    task_id: str,
    principal: CustomerDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse | JSONResponse:
    try:
        result = await service.task_detail(session, principal.id, task_id)
    except CustomerDecisionError as error:
        return _error_response(error)
    return success_response(data=result.model_dump(mode="json"))


@router.get("/my/tasks/{task_id}/adopted-image/content", response_model=None)
async def get_my_task_adopted_image(
    task_id: str,
    principal: CustomerDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
    thumbnail: bool = Query(False),
) -> Response | JSONResponse:
    return await _task_image_response(
        task_id, principal, session, service, initial=False, thumbnail=thumbnail
    )


@router.get("/my/tasks/{task_id}/initial-image/content", response_model=None)
async def get_my_task_initial_image(
    task_id: str,
    principal: CustomerDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
    thumbnail: bool = Query(False),
) -> Response | JSONResponse:
    return await _task_image_response(
        task_id, principal, session, service, initial=True, thumbnail=thumbnail
    )


@router.get("/my/tasks/{task_id}/delivery-image/content", response_model=None)
async def get_my_task_delivery_image(
    task_id: str,
    principal: CustomerDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
    thumbnail: bool = Query(False),
) -> Response | JSONResponse:
    try:
        media_type, content = await service.read_task_delivery_image(
            session, principal.id, task_id, thumbnail=thumbnail
        )
    except CustomerDecisionError as error:
        return _error_response(error)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )


async def _task_image_response(
    task_id: str,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
    service: CustomerDecisionService,
    *,
    initial: bool,
    thumbnail: bool,
) -> Response | JSONResponse:
    try:
        media_type, content = await service.read_task_image(
        session, principal.id, task_id, initial=initial, thumbnail=thumbnail
        )
    except CustomerDecisionError as error:
        return _error_response(error)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )
