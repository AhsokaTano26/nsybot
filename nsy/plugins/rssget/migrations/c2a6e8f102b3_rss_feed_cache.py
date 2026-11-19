"""Persist the latest RSS window independently from QQ delivery.

Revision ID: c2a6e8f102b3
Revises: 8d0e4a6b9c12
Create Date: 2026-11-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c2a6e8f102b3"
down_revision = "8d0e4a6b9c12"
branch_labels = None
depends_on = None


def upgrade(name: str = "") -> None:
    if name:
        return
    op.create_table(
        "rss_feed_cache",
        sa.Column("account_id", sa.String(255), nullable=False),
        sa.Column("entries", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("account_id", name=op.f("pk_rss_feed_cache")),
        info={"bind_key": "rssget"},
    )


def downgrade(name: str = "") -> None:
    if name:
        return
    op.drop_table("rss_feed_cache")
