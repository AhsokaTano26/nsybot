"""Index existing image posts in stable ingestion order.

Revision ID: 8d0e4a6b9c12
Revises: 7c6b8d2e40a1
Create Date: 2026-11-12
"""

from __future__ import annotations

import ast
import logging

import sqlalchemy as sa
from alembic import op

revision = "8d0e4a6b9c12"
down_revision = "7c6b8d2e40a1"
branch_labels = None
depends_on = None


def upgrade(name: str = "") -> None:
    if name:
        return
    index = op.create_table(
        "rss_image_sync",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("content_id", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(["content_id"], ["Content.id"], name=op.f("fk_rss_image_sync_content_id_Content")),
        sa.UniqueConstraint("content_id", name=op.f("uq_rss_image_sync_content_id")),
        sqlite_autoincrement=True,
        info={"bind_key": "rssget"},
    )
    connection = op.get_bind()
    content = sa.table("Content", sa.column("id", sa.String(255)), sa.column("images", sa.Text()))
    rows = connection.execute(sa.select(content.c.id, content.c.images).where(
        content.c.id.is_not(None), content.c.images.is_not(None),
    ).order_by(content.c.id)).mappings()
    pending = []
    for row in rows:
        try:
            images = ast.literal_eval(row["images"])
            if not isinstance(images, list) or not all(isinstance(url, str) for url in images):
                raise ValueError("invalid image list")
        except (ValueError, SyntaxError, TypeError):
            logging.getLogger(__name__).warning("文章 %s 图片缓存损坏，无法建立历史图片索引", row["id"])
            continue
        if images:
            pending.append({"content_id": row["id"]})
        if len(pending) == 500:
            connection.execute(index.insert(), pending)
            pending.clear()
    if pending:
        connection.execute(index.insert(), pending)


def downgrade(name: str = "") -> None:
    if name:
        return
    op.drop_table("rss_image_sync")
