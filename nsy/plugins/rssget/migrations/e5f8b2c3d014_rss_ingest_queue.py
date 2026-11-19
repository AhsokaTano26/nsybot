"""Persist fetched articles before Content/ImageSync writes.

Revision ID: e5f8b2c3d014
Revises: d4e7a1b2c903
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op

revision = "e5f8b2c3d014"
down_revision = "d4e7a1b2c903"
branch_labels = None
depends_on = None


def upgrade(name: str = "") -> None:
    if name:
        return
    op.create_table(
        "rss_ingest_queue",
        sa.Column("id", sa.String(255), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("entry", sa.Text(), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rss_ingest_queue")),
        info={"bind_key": "rssget"},
    )
    op.create_index(op.f("ix_rss_ingest_queue_next_retry_at"), "rss_ingest_queue", ["next_retry_at"])


def downgrade(name: str = "") -> None:
    if name:
        return
    op.drop_index(op.f("ix_rss_ingest_queue_next_retry_at"), table_name="rss_ingest_queue")
    op.drop_table("rss_ingest_queue")
