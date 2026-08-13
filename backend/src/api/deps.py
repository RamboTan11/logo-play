"""Route-level authentication dependencies for admin and customer sessions."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.errors import ApplicationHTTPException
from src.core.development_seed import DevelopmentPrincipal, DevelopmentSeedRegistry
from src.db.session import get_db
from src.services.auth_service import (
    ADMIN_SESSION_COOKIE,
    CUSTOMER_SESSION_COOKIE,
    AuthConfigurationError,
    AuthenticatedPrincipal,
    AuthService,
)

security = HTTPBearer(auto_error=False)


def get_seed_registry(request: Request) -> DevelopmentSeedRegistry:
    """Read the registry initialized by the application factory."""

    return request.app.state.development_seed_registry


async def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    registry: Annotated[DevelopmentSeedRegistry, Depends(get_seed_registry)],
) -> DevelopmentPrincipal:
    """Resolve a development principal from a Bearer credential."""

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    principal = registry.principal_for(credentials.credentials)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid development credential",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


async def require_admin(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    registry: Annotated[DevelopmentSeedRegistry, Depends(get_seed_registry)],
) -> AuthenticatedPrincipal:
    """Require a real admin cookie, with explicit development Bearer fallback only."""

    principal = await _admin_from_cookie(request, session)
    if principal is not None:
        return principal
    if credentials is not None:
        development = registry.principal_for(credentials.credentials)
        if development is not None:
            if development.role == "admin":
                return AuthenticatedPrincipal(development.id, development.role)
            raise ApplicationHTTPException(
                status.HTTP_403_FORBIDDEN,
                "Administrator permission required",
                "forbidden",
            )
    raise ApplicationHTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Administrator session required",
        "admin_session_required",
        clear_cookie=ADMIN_SESSION_COOKIE,
    )


async def require_customer(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    registry: Annotated[DevelopmentSeedRegistry, Depends(get_seed_registry)],
) -> AuthenticatedPrincipal:
    """Require a real customer cookie, with explicit development Bearer fallback only."""

    principal = await _customer_from_cookie(request, session)
    if principal is not None:
        return principal
    if credentials is not None:
        development = registry.principal_for(credentials.credentials)
        if development is not None:
            if development.role == "customer":
                return AuthenticatedPrincipal(development.id, development.role)
            raise ApplicationHTTPException(
                status.HTTP_403_FORBIDDEN,
                "Customer permission required",
                "forbidden",
            )
    raise ApplicationHTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Customer session required",
        "customer_session_required",
        clear_cookie=CUSTOMER_SESSION_COOKIE,
    )


async def require_admin_session(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuthenticatedPrincipal:
    """Require the real shared-admin cookie without development fallback."""

    principal = await _admin_from_cookie(request, session)
    if principal is None:
        raise ApplicationHTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Administrator session required",
            "admin_session_required",
            clear_cookie=ADMIN_SESSION_COOKIE,
        )
    return principal


async def require_customer_session(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuthenticatedPrincipal:
    """Require the real customer cookie without development fallback."""

    principal = await _customer_from_cookie(request, session)
    if principal is None:
        raise ApplicationHTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Customer session required",
            "customer_session_required",
            clear_cookie=CUSTOMER_SESSION_COOKIE,
        )
    return principal


async def _admin_from_cookie(
    request: Request, session: AsyncSession
) -> AuthenticatedPrincipal | None:
    try:
        return await AuthService(request.app.state.settings).get_admin_principal(
            session, request.cookies.get(ADMIN_SESSION_COOKIE)
        )
    except AuthConfigurationError as error:
        raise ApplicationHTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Authentication configuration is unavailable",
            "auth_configuration_unavailable",
        ) from error


async def _customer_from_cookie(
    request: Request, session: AsyncSession
) -> AuthenticatedPrincipal | None:
    try:
        return await AuthService(request.app.state.settings).get_customer_principal(
            session, request.cookies.get(CUSTOMER_SESSION_COOKIE)
        )
    except AuthConfigurationError as error:
        raise ApplicationHTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Authentication configuration is unavailable",
            "auth_configuration_unavailable",
        ) from error
