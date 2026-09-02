"""change group_id to string

迁移 ID: f3f0bf01c555
父迁移: 76942fe5b1a4
创建时间: 2026-09-01 00:06:49.117678
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "f3f0bf01c555"
down_revision: str | Sequence[str] | None = "76942fe5b1a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade(name: str = "") -> None:
    if name:
        return

    # SQLite 不支持直接 ALTER COLUMN TYPE，
    # 使用 Alembic batch 模式重建表并保留原有数据。
    with op.batch_alter_table("Group_config", schema=None) as batch_op:
        batch_op.alter_column(
            "group_id",
            existing_type=sa.INTEGER(),
            type_=sa.String(length=255),
            existing_nullable=False,
        )


def downgrade(name: str = "") -> None:
    if name:
        return

    # 回滚时将 group_id 从 VARCHAR(255) 改回 INTEGER。
    with op.batch_alter_table("Group_config", schema=None) as batch_op:
        batch_op.alter_column(
            "group_id",
            existing_type=sa.String(length=255),
            type_=sa.INTEGER(),
            existing_nullable=False,
        )