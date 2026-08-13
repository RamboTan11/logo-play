"""Docker production entry point for the API-only container."""

from pathlib import Path

from fastapi import FastAPI

from src.config import load_settings
from src.main import create_application


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_CONFIG_PATH = PROJECT_ROOT / "backend" / "config" / "app.production.toml"


def create_app() -> FastAPI:
    """Create the API with production settings without serving the frontend."""

    return create_application(load_settings(PRODUCTION_CONFIG_PATH))
