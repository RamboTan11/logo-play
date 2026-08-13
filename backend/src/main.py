"""FastAPI application entry point for local backend development."""

import logging
from typing import cast

from fastapi import FastAPI
from src.api.errors import register_exception_handlers
from src.api.routes.auth import router as auth_router
from src.api.routes.batch_generation_policy import router as batch_generation_policy_router
from src.api.routes.customer_decisions import router as customer_decisions_router
from src.api.routes.customers import router as customers_router
from src.api.routes.development import create_development_router
from src.api.routes.generations import router as generations_router
from src.api.routes.generations import source_asset_router
from src.api.routes.lark_notifications import router as lark_notifications_router
from src.api.routes.model_connections import router as model_connections_router
from src.api.routes.single_image_edit_policy import router as single_image_edit_policy_router
from src.api.routes.task_center import router as task_center_router
from src.config import AppSettings, load_settings
from src.core.development_seed import DevelopmentSeedRegistry
from src.db.migrations.runner import initialize_database
from src.db.session import create_database_runtime
from src.services.lark_worker import LarkWorker
from src.services.lark_secret_service import LarkSecretService
from src.services.model_secret_service import ModelConnectionSecretService
from src.services.single_image_edit_service import SingleImageEditService

from pycore.api import APIConfig, APIServer
from pycore.core import Logger, LoggerConfig

logger = logging.getLogger(__name__)


def create_application(settings: AppSettings | None = None) -> FastAPI:
    """Create an API application from explicit local configuration."""

    active_settings = settings or load_settings()
    Logger.configure(
        LoggerConfig(
            console_enabled=True,
            file_enabled=False,
            app_name="logo_generated",
        )
    )
    server = APIServer(
        APIConfig(
            title=active_settings.app_title,
            version=active_settings.api_version,
            debug=active_settings.debug,
            cors_origins=active_settings.cors_origins,
        )
    )
    application = cast(FastAPI, server.app)
    application.state.settings = active_settings
    application.state.development_seed_registry = DevelopmentSeedRegistry(active_settings)
    application.state.database_runtime = create_database_runtime(active_settings)

    @server.on_startup
    async def initialize_application_database() -> None:
        await initialize_database(application.state.database_runtime, active_settings)
        application.state.single_image_edit_service = SingleImageEditService(
            application.state.database_runtime,
            active_settings.asset_root,
            active_settings.model_connection_secret_encryption_key,
            provider=getattr(application.state, "single_image_edit_provider", None),
        )
        if ModelConnectionSecretService(active_settings.model_connection_secret_encryption_key).is_configured:
            await application.state.single_image_edit_service.resume_pending()
        else:
            logger.warning("Model secret encryption is not configured; generation remains unavailable until configured in admin.")
        lark_secret_ready = LarkSecretService(active_settings.lark_config_encryption_key).is_configured
        if active_settings.lark_worker_enabled and lark_secret_ready:
            application.state.lark_worker = LarkWorker(
                application.state.database_runtime, active_settings
            )
            application.state.lark_worker.start()
        elif active_settings.lark_worker_enabled:
            logger.warning("Lark encryption is not configured; Lark worker remains disabled until configured in admin.")

    @server.on_shutdown
    async def dispose_application_database() -> None:
        worker = getattr(application.state, "lark_worker", None)
        if worker is not None:
            await worker.stop()
        await application.state.database_runtime.dispose()

    register_exception_handlers(application)
    server.include_router(create_development_router())
    server.include_router(auth_router)
    server.include_router(customers_router)
    server.include_router(customer_decisions_router)
    server.include_router(model_connections_router)
    server.include_router(batch_generation_policy_router)
    server.include_router(single_image_edit_policy_router)
    server.include_router(source_asset_router)
    server.include_router(generations_router)
    server.include_router(task_center_router)
    server.include_router(lark_notifications_router)
    return application


app = create_application()
