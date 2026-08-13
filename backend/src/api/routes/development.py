"""Temporary local-only routes used to verify the T-007 dependency boundary."""

from typing import Annotated

from fastapi import Depends, HTTPException
from src.api.deps import get_current_principal
from src.core.development_seed import DevelopmentPrincipal

from pycore.api import APIRouter, success_response
from pycore.api.responses import APIResponse


def create_development_router() -> APIRouter:
    """Build local development routes after the application logger is configured."""

    router = APIRouter(prefix="/api/v1/development", tags=["development"])

    @router.get("/identity")
    async def get_development_identity(
        principal: Annotated[DevelopmentPrincipal, Depends(get_current_principal)],
    ) -> APIResponse:
        """Confirm a seeded local credential without exposing any credential value."""

        return success_response(data={"id": principal.id, "role": principal.role})

    @router.get("/admin-only")
    async def get_admin_only_resource(
        principal: Annotated[DevelopmentPrincipal, Depends(get_current_principal)],
    ) -> APIResponse:
        """Exercise the explicit administrator permission boundary."""

        if principal.role != "admin":
            raise HTTPException(status_code=403, detail="Administrator permission required")
        return success_response(data={"id": principal.id, "role": principal.role})

    return router
