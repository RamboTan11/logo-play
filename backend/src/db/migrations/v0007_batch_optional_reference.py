"""Allow batch generation candidates to omit a template reference image."""

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncConnection

VERSION = "0007_batch_optional_reference"


def _upgrade(connection: Connection) -> None:
    columns = {
        row[1]: row
        for row in connection.execute(
            text("PRAGMA table_info('generation_candidate_jobs')")
        ).fetchall()
    }
    reference_column = columns.get("reference_image_asset_id")
    if reference_column is None or reference_column[3] == 0:
        return

    connection.execute(text("PRAGMA foreign_keys = OFF"))
    try:
        connection.execute(
            text(
                """
                CREATE TABLE generation_candidate_jobs_v0007 (
                    id VARCHAR(64) NOT NULL PRIMARY KEY,
                    request_id VARCHAR(64) NOT NULL,
                    ordinal INTEGER NOT NULL,
                    style_id VARCHAR(128) NOT NULL,
                    template_id VARCHAR(128) NOT NULL,
                    reference_image_asset_id VARCHAR(64),
                    status VARCHAR(24) NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    run_snapshot_json TEXT NOT NULL,
                    result_asset_id VARCHAR(64),
                    error_code VARCHAR(80),
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(request_id) REFERENCES generation_requests (id) ON DELETE RESTRICT,
                    FOREIGN KEY(reference_image_asset_id) REFERENCES asset_records (asset_id) ON DELETE RESTRICT,
                    FOREIGN KEY(result_asset_id) REFERENCES asset_records (asset_id) ON DELETE RESTRICT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO generation_candidate_jobs_v0007 (
                    id, request_id, ordinal, style_id, template_id,
                    reference_image_asset_id, status, attempt_count,
                    run_snapshot_json, result_asset_id, error_code,
                    created_at, updated_at
                )
                SELECT id, request_id, ordinal, style_id, template_id,
                       reference_image_asset_id, status, attempt_count,
                       run_snapshot_json, result_asset_id, error_code,
                       created_at, updated_at
                FROM generation_candidate_jobs
                """
            )
        )
        connection.execute(text("DROP TABLE generation_candidate_jobs"))
        connection.execute(
            text(
                "ALTER TABLE generation_candidate_jobs_v0007 "
                "RENAME TO generation_candidate_jobs"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX ix_generation_candidate_jobs_request_id "
                "ON generation_candidate_jobs (request_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX ix_generation_candidate_jobs_status "
                "ON generation_candidate_jobs (status)"
            )
        )
    finally:
        connection.execute(text("PRAGMA foreign_keys = ON"))


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
