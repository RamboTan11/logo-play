"""Local-only identities used before the real customer-link flow is implemented."""

from dataclasses import dataclass
from hmac import compare_digest

from src.config import AppSettings


@dataclass(frozen=True, slots=True)
class DevelopmentPrincipal:
    """A minimal principal exposed to route dependencies."""

    id: str
    role: str


class DevelopmentSeedRegistry:
    """Resolves local development credentials without introducing account login."""

    def __init__(self, settings: AppSettings) -> None:
        self._admin = DevelopmentPrincipal(id=settings.development_admin_id, role="admin")
        self._customer = DevelopmentPrincipal(
            id=settings.development_customer_id,
            role="customer",
        )
        self._admin_token = settings.development_admin_token
        self._customer_access_link = settings.development_customer_access_link
        self._enabled = (
            settings.app_env.strip().lower() == "development"
            and settings.enable_development_seeds
        )

    def principal_for(self, credential: str) -> DevelopmentPrincipal | None:
        """Return a local principal when its development credential matches exactly."""

        if not self._enabled:
            return None
        if compare_digest(credential, self._admin_token):
            return self._admin
        if compare_digest(credential, self._customer_access_link):
            return self._customer
        return None
