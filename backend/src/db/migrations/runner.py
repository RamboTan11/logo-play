"""Run immutable schema migrations and development seed data."""

from datetime import UTC, datetime

from sqlalchemy import select
from src.config import AppSettings
from src.db.migrations import (
    v0001_infrastructure,
    v0002_model_connection_secrets,
    v0003_batch_generation_policy,
    v0004_single_image_edit_policy,
    v0005_batch_generation_runtime,
    v0006_single_image_edit_runtime,
    v0007_batch_optional_reference,
    v0008_auth_customer_access,
    v0009_customer_decisions,
    v0010_task_delivery_image,
    v0011_customer_task_exclusivity,
    v0012_lark_notifications,
    v0013_notification_outbox_claims,
    v0014_generation_domain_parts,
    v0015_kie_provider_tasks,
    v0016_batch_generation_policy_draft,
    v0017_t027_source_images_and_delta,
    v0018_t027_source_image_foreign_keys,
    v0019_backfill_model_input_image_capacity,
    v0020_t028_reminder_pause,
    v0021_t030_lark_mention_all,
    v0022_model_connection_retirement,
    v0023_task_feedback_rating,
    v0024_batch_style_catalog_selection,
)
from src.db.models import Customer, SchemaMigration
from src.db.session import DatabaseRuntime
from src.services.auth_service import AuthService

MIGRATIONS = (
    v0001_infrastructure,
    v0002_model_connection_secrets,
    v0003_batch_generation_policy,
    v0004_single_image_edit_policy,
    v0005_batch_generation_runtime,
    v0006_single_image_edit_runtime,
    v0007_batch_optional_reference,
    v0008_auth_customer_access,
    v0009_customer_decisions,
    v0010_task_delivery_image,
    v0011_customer_task_exclusivity,
    v0012_lark_notifications,
    v0013_notification_outbox_claims,
    v0014_generation_domain_parts,
    v0015_kie_provider_tasks,
    v0016_batch_generation_policy_draft,
    v0017_t027_source_images_and_delta,
    v0018_t027_source_image_foreign_keys,
    v0019_backfill_model_input_image_capacity,
    v0020_t028_reminder_pause,
    v0021_t030_lark_mention_all,
    v0022_model_connection_retirement,
    v0023_task_feedback_rating,
    v0024_batch_style_catalog_selection,
)


async def initialize_database(runtime: DatabaseRuntime, settings: AppSettings) -> None:
    """Apply missing migrations and ensure the one development customer exists."""

    async with runtime.engine.begin() as connection:
        await connection.run_sync(SchemaMigration.__table__.create, checkfirst=True)
        applied = {
            row[0] for row in (await connection.execute(select(SchemaMigration.version))).all()
        }
        for migration in MIGRATIONS:
            if migration.VERSION not in applied:
                await migration.upgrade(connection)
                await connection.execute(
                    SchemaMigration.__table__.insert().values(
                        version=migration.VERSION,
                        applied_at=datetime.now(UTC),
                    )
                )

    async with runtime.session_factory() as session:
        await AuthService(settings).initialize_shared_administrator(session)
        await session.commit()

    if settings.app_env.strip().lower() != "development" or not settings.enable_development_seeds:
        return

    async with runtime.session_factory() as session:
        seed_customer = await session.get(Customer, settings.development_customer_id)
        if seed_customer is None:
            session.add(
                Customer(
                    id=settings.development_customer_id,
                    name="Development seed customer",
                    is_development_seed=True,
                )
            )
            await session.commit()
