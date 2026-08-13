"""Add the recoverable single-image edit runtime and version-chain fields."""

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncConnection
from src.db.models import SingleImageEditRequest

VERSION = "0006_single_image_edit_runtime"


def _upgrade(connection: Connection) -> None:
    SingleImageEditRequest.__table__.create(connection, checkfirst=True)
    columns = {
        row[1]
        for row in connection.execute(text("PRAGMA table_info('logo_versions')")).fetchall()
    }
    if "single_edit_request_id" in columns:
        return

    connection.execute(
        text(
            """
            CREATE TABLE logo_versions_v0006 (
                id VARCHAR(64) NOT NULL PRIMARY KEY,
                customer_id VARCHAR(64) NOT NULL,
                domain VARCHAR(255) NOT NULL,
                generation_request_id VARCHAR(64),
                candidate_job_id VARCHAR(64) UNIQUE,
                single_edit_request_id VARCHAR(64) UNIQUE,
                parent_logo_version_id VARCHAR(64),
                root_logo_version_id VARCHAR(64),
                version_number INTEGER NOT NULL DEFAULT 1,
                asset_id VARCHAR(64) NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(customer_id) REFERENCES customers (id) ON DELETE RESTRICT,
                FOREIGN KEY(generation_request_id) REFERENCES generation_requests (id) ON DELETE RESTRICT,
                FOREIGN KEY(candidate_job_id) REFERENCES generation_candidate_jobs (id) ON DELETE RESTRICT,
                FOREIGN KEY(single_edit_request_id) REFERENCES single_image_edit_requests (id) ON DELETE RESTRICT,
                FOREIGN KEY(parent_logo_version_id) REFERENCES logo_versions (id) ON DELETE RESTRICT,
                FOREIGN KEY(root_logo_version_id) REFERENCES logo_versions (id) ON DELETE RESTRICT,
                FOREIGN KEY(asset_id) REFERENCES asset_records (asset_id) ON DELETE RESTRICT
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO logo_versions_v0006 (
                id, customer_id, domain, generation_request_id, candidate_job_id,
                single_edit_request_id, parent_logo_version_id, root_logo_version_id,
                version_number, asset_id, created_at
            )
            SELECT id, customer_id, domain, generation_request_id, candidate_job_id,
                   NULL, NULL, id, 1, asset_id, created_at
            FROM logo_versions
            """
        )
    )
    connection.execute(text("DROP TABLE logo_versions"))
    connection.execute(text("ALTER TABLE logo_versions_v0006 RENAME TO logo_versions"))
    for column in (
        "customer_id",
        "domain",
        "generation_request_id",
        "parent_logo_version_id",
        "root_logo_version_id",
        "created_at",
    ):
        connection.execute(
            text(f"CREATE INDEX ix_logo_versions_{column} ON logo_versions ({column})")
        )


async def upgrade(connection: AsyncConnection) -> None:
    await connection.run_sync(_upgrade)
