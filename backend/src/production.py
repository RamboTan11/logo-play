"""Production entry point serving the API and built frontend from one origin."""

from pathlib import Path
from typing import cast

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from src.config import AppSettings, load_settings
from src.main import create_application

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_CONFIG_PATH = PROJECT_ROOT / "backend" / "config" / "app.production.toml"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def create_production_application(
    settings: AppSettings,
    frontend_dist: Path = FRONTEND_DIST,
) -> FastAPI:
    """Create the API and attach a traversal-safe SPA fallback."""

    static_root = frontend_dist.resolve()
    index_path = static_root / "index.html"
    if not index_path.is_file():
        raise RuntimeError(
            f"Frontend build is missing at {index_path}. Run npm.cmd run build:real first."
        )

    application = cast(FastAPI, create_application(settings))

    def static_response(path: Path) -> FileResponse:
        response = FileResponse(path)
        if path == index_path:
            response.headers["Cache-Control"] = "no-store"
        elif "assets" in path.relative_to(static_root).parts:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    @application.get("/", include_in_schema=False)
    async def frontend_index() -> FileResponse:
        return static_response(index_path)

    @application.get("/{full_path:path}", include_in_schema=False)
    async def frontend_route(full_path: str) -> FileResponse:
        first_segment = full_path.partition("/")[0]
        if first_segment in {"api", "health", "ws"}:
            raise HTTPException(status_code=404, detail="Not Found")

        requested_path = (static_root / full_path).resolve()
        if requested_path.is_relative_to(static_root) and requested_path.is_file():
            return static_response(requested_path)

        if first_segment == "assets" or Path(full_path).suffix:
            raise HTTPException(status_code=404, detail="Not Found")
        return static_response(index_path)

    return application


def create_app() -> FastAPI:
    """Uvicorn factory for the production configuration."""

    return create_production_application(load_settings(PRODUCTION_CONFIG_PATH))
