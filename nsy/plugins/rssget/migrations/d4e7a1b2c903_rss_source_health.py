"""Persist Twitter collector state and its notification outbox.

Revision ID: d4e7a1b2c903
Revises: c2a6e8f102b3
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op

revision = "d4e7a1b2c903"
down_revision = "c2a6e8f102b3"
branch_labels = None
depends_on = None


def upgrade(name: str = "") -> None:
    if name:
        return
    op.create_table(
        "rss_source_status",
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("retry_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("source", name=op.f("pk_rss_source_status")),
        info={"bind_key": "rssget"},
    )
    op.create_table(
        "rss_source_notice",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rss_source_notice")),
        sqlite_autoincrement=True,
        info={"bind_key": "rssget"},
    )


def downgrade(name: str = "") -> None:
    if name:
        return
    op.drop_table("rss_source_notice")
    op.drop_table("rss_source_status")
