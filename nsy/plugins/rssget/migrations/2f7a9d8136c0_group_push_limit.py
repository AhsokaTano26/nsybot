"""Store the per-group RSS delivery window.

Revision ID: 2f7a9d8136c0
Revises: 76942fe5b1a4
Create Date: 2026-10-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "2f7a9d8136c0"
down_revision = "76942fe5b1a4"
branch_labels = None
depends_on = None


def upgrade(name: str = "") -> None:
    if name:
        return
    with op.batch_alter_table("Group_config") as batch_op:
        batch_op.add_column(sa.Column("push_limit", sa.Integer(), nullable=False, server_default="1"))
        batch_op.create_check_constraint(
            op.f("ck_Group_config_push_limit_range"),
            "push_limit IN (0, 1, 2, 3, 4, 5)",
        )


def downgrade(name: str = "") -> None:
    if name:
        return
    with op.batch_alter_table("Group_config") as batch_op:
        batch_op.drop_constraint(op.f("ck_Group_config_push_limit_range"), type_="check")
        batch_op.drop_column("push_limit")
