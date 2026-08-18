"""Administrator task-center endpoints backed by the persistent task workflow."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.deps import require_admin_session
from src.db.session import get_db
from src.services.auth_service import AuthenticatedPrincipal
from src.services.task_center_service import (
    TaskCenterError,
    TaskCenterService,
    validate_delivery_upload,
)

from pycore.api import success_response
from pycore.api.responses import APIResponse, error_response

router = APIRouter(prefix="/api/v1/design-tasks", tags=["task-center"])

AdminDependency = Annotated[AuthenticatedPrincipal, Depends(require_admin_session)]
DatabaseDependency = Annotated[AsyncSession, Depends(get_db)]


def get_task_center_service(request: Request) -> TaskCenterService:
    service = getattr(request.app.state, "task_center_service", None)
    if service is None:
        service = TaskCenterService(request.app.state.settings.asset_root, request.app.state.settings)
        request.app.state.task_center_service = service
    return service


ServiceDependency = Annotated[TaskCenterService, Depends(get_task_center_service)]


def _error_response(error: TaskCenterError) -> JSONResponse:
    body, http_status = error_response(
        str(error), error_code=error.code, status_code=error.status_code
    )
    return JSONResponse(status_code=http_status, content=body.model_dump())


@router.get("", response_model=None)
async def list_tasks(
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
    status: Annotated[list[str] | None, Query()] = None,
    submitted_from: date | None = None,
    submitted_to: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=15)] = 15,
) -> APIResponse | JSONResponse:
    del principal
    try:
        result = await service.list_tasks(
            session,
            statuses=status or [],
            submitted_from=submitted_from,
            submitted_to=submitted_to,
            page=page,
            page_size=page_size,
        )
    except TaskCenterError as error:
        return _error_response(error)
    return success_response(data=result.model_dump(mode="json"))


@router.get("/export", response_model=None)
async def export_tasks(
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
    status: Annotated[list[str] | None, Query()] = None,
    submitted_from: date | None = None,
    submitted_to: date | None = None,
) -> Response | JSONResponse:
    del principal
    try:
        content = await service.export_tasks(
            session,
            statuses=status or [],
            submitted_from=submitted_from,
            submitted_to=submitted_to,
        )
    except TaskCenterError as error:
        return _error_response(error)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=design-tasks.xlsx",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/{task_id}", response_model=None)
async def get_task(
    task_id: str,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse | JSONResponse:
    del principal
    try:
        result = await service.detail(session, task_id)
    except TaskCenterError as error:
        return _error_response(error)
    return success_response(data=result.model_dump(mode="json"))


@router.post("/{task_id}/accept", response_model=None)
async def accept_task(
    task_id: str,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
) -> APIResponse | JSONResponse:
    try:
        result = await service.accept(session, task_id=task_id, administrator_id=principal.id)
    except TaskCenterError as error:
        return _error_response(error)
    return success_response(data={"task": result.model_dump(mode="json")})


@router.post("/{task_id}/delivery-image", response_model=None)
async def upload_delivery_image(
    task_id: str,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
    image: Annotated[UploadFile, File()],
) -> APIResponse | JSONResponse:
    content = await image.read(10 * 1024 * 1024 + 1)
    try:
        upload = validate_delivery_upload(image.filename, image.content_type, content)
        result = await service.deliver(
            session,
            task_id=task_id,
            administrator_id=principal.id,
            upload=upload,
        )
    except TaskCenterError as error:
        return _error_response(error)
    finally:
        await image.close()
    return success_response(data={"task": result.model_dump(mode="json")})


@router.get("/{task_id}/adopted-image/content", response_model=None)
async def get_adopted_image(
    task_id: str,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
    thumbnail: bool = Query(False),
) -> Response | JSONResponse:
    del principal
    try:
        media_type, content = await service.read_adopted_image(session, task_id, thumbnail=thumbnail)
    except TaskCenterError as error:
        return _error_response(error)
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "private, no-store"})


@router.get("/{task_id}/delivery-image/content", response_model=None)
async def get_delivery_image(
    task_id: str,
    principal: AdminDependency,
    session: DatabaseDependency,
    service: ServiceDependency,
    thumbnail: bool = Query(False),
) -> Response | JSONResponse:
    del principal
    try:
        media_type, content = await service.read_delivery_image(session, task_id, thumbnail=thumbnail)
    except TaskCenterError as error:
        return _error_response(error)
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "private, no-store"})
