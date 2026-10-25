"""Record current bot groups and backfill legacy evidence once.

Revision ID: 7c6b8d2e40a1
Revises: 2f7a9d8136c0
Create Date: 2026-10-25
"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "7c6b8d2e40a1"
down_revision = "2f7a9d8136c0"
branch_labels = None
depends_on = None


def upgrade(name: str = "") -> None:
    if name:
        return
    registry = op.create_table(
        "bot_group",
        sa.Column("group_openid", sa.String(255), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.PrimaryKeyConstraint("group_openid", name=op.f("pk_bot_group")),
        info={"bind_key": "rssget"},
    )
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    sources = []
    for table_name, column_name in (
        ("Subscribe", "group"), ("Group_config", "group_id"), ("birthday_group", "group_id"),
    ):
        if not inspector.has_table(table_name):
            continue
        legacy = sa.table(table_name, sa.column(column_name, sa.String(255)))
        group_id = sa.cast(legacy.c[column_name], sa.String(255))
        sources.append(sa.select(group_id.label("group_openid")).where(
            group_id.is_not(None), sa.func.trim(group_id) != "",
        ))
    if sources:
        history = sa.union(*sources).subquery()
        recorded_at = datetime.now(timezone.utc).replace(tzinfo=None)
        connection.execute(sa.insert(registry).from_select(
            ["group_openid", "joined_at", "recorded_at", "last_seen_at", "source"],
            sa.select(
                history.c.group_openid, sa.null(), sa.literal(recorded_at, type_=sa.DateTime()),
                sa.null(), sa.literal("history"),
            ),
        ))


def downgrade(name: str = "") -> None:
    if name:
        return
    op.drop_table("bot_group")
