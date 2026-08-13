"""Docker production entry point for the API-only container."""

from pathlib import Path

from fastapi import FastAPI

from src.config import load_settings
from src.main import create_application


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "backend" / "config"


def docker_config_path() -> Path:
    """Prefer the operator-mounted app.toml, with the repository default as fallback."""

    app_config = CONFIG_DIR / "app.toml"
    return app_config if app_config.is_file() else CONFIG_DIR / "app.production.toml"


def create_app() -> FastAPI:
    """Create the API with production settings without serving the frontend."""

    return create_application(load_settings(docker_config_path()))
