"""Application configuration with TOML defaults and explicit environment overrides."""

import os
from pathlib import Path
from typing import cast

from pycore.core import BaseSettings as PyCoreBaseSettings
from pycore.core import ConfigManager


class FileSettings(PyCoreBaseSettings):
    """Settings read from the explicit PyCore TOML configuration file."""

    app_title: str
    api_version: str
    debug: bool
    cors_origins: list[str]
    development_admin_id: str
    development_admin_token: str
    development_customer_id: str
    development_customer_access_link: str
    database_path: str = "data/logo_generated.db"
    asset_root: str = "data/assets"
    app_env: str = "development"
    enable_development_seeds: bool = False
    model_connection_secret_encryption_key: str | None = None
    enable_real_model_smoke_tests: bool = False
    initial_admin_username: str | None = None
    initial_admin_password: str | None = None
    auth_session_secret: str | None = None
    customer_access_token_encryption_key: str | None = None
    customer_frontend_base_url: str | None = None
    admin_frontend_base_url: str = "http://127.0.0.1:5199"
    lark_worker_enabled: bool = True
    lark_worker_interval_seconds: int = 5
    lark_delivery_max_attempts: int = 3
    lark_claim_lease_seconds: int = 60
    lark_config_encryption_key: str | None = None


class PrivateSettings(PyCoreBaseSettings):
    """Only the untracked deployment-local values needed by the application."""

    model_connection_secret_encryption_key: str | None = None
    app_env: str | None = None
    enable_real_model_smoke_tests: bool | None = None
    initial_admin_username: str | None = None
    initial_admin_password: str | None = None
    auth_session_secret: str | None = None
    customer_access_token_encryption_key: str | None = None
    customer_frontend_base_url: str | None = None
    admin_frontend_base_url: str | None = None
    lark_config_encryption_key: str | None = None


class AppSettings(PyCoreBaseSettings):
    """Runtime settings loaded from explicit backend-local TOML configuration."""

    app_title: str
    api_version: str
    debug: bool
    cors_origins: list[str]
    development_admin_id: str
    development_admin_token: str
    development_customer_id: str
    development_customer_access_link: str
    database_path: str = "data/logo_generated.db"
    asset_root: str = "data/assets"
    app_env: str = "development"
    enable_development_seeds: bool = False
    model_connection_secret_encryption_key: str | None = None
    enable_real_model_smoke_tests: bool = False
    initial_admin_username: str | None = None
    initial_admin_password: str | None = None
    auth_session_secret: str | None = None
    customer_access_token_encryption_key: str | None = None
    customer_frontend_base_url: str | None = None
    admin_frontend_base_url: str = "http://127.0.0.1:5199"
    lark_worker_enabled: bool = True
    lark_worker_interval_seconds: int = 5
    lark_delivery_max_attempts: int = 3
    lark_claim_lease_seconds: int = 60
    lark_config_encryption_key: str | None = None


def default_config_path() -> Path:
    """Return the backend-local configuration path independent of the working directory."""

    return Path(__file__).resolve().parents[1] / "config" / "app.toml"


def local_config_path() -> Path:
    """Resolve an optional deployment-local override without exposing its contents."""

    configured_path = os.environ.get("LOGO_PRIVATE_CONFIG_PATH", "").strip()
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return default_config_path().with_name("app.local.toml")


def load_settings(config_path: Path | None = None) -> AppSettings:
    """Load public configuration and optional untracked private configuration."""

    manager = ConfigManager[FileSettings]()
    manager.load(FileSettings, config_path or default_config_path())
    file_settings = cast(FileSettings, manager.settings)
    values = file_settings.model_dump()
    private_path = local_config_path()
    if private_path.exists():
        private_manager = ConfigManager[PrivateSettings]()
        private_manager.load(PrivateSettings, private_path)
        private_settings = cast(PrivateSettings, private_manager.settings)
        values.update(private_settings.model_dump(exclude_none=True))
    runtime_data_dir = os.environ.get("LOGO_RUNTIME_DATA_DIR", "").strip()
    if runtime_data_dir:
        data_root = Path(runtime_data_dir).expanduser().resolve()
        values["database_path"] = str(data_root / "logo_generated.db")
        values["asset_root"] = str(data_root / "assets")
    return AppSettings(**values)
