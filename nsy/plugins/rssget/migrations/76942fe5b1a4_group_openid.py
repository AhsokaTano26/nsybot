"""Store QQ official group OpenIDs.

Revision ID: 76942fe5b1a4
Revises: 1b51e394adf2
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "76942fe5b1a4"
down_revision = "1b51e394adf2"
branch_labels = None
depends_on = None


def upgrade(name: str = "") -> None:
    if name:
        return
    with op.batch_alter_table("Group_config") as batch_op:
        batch_op.alter_column(
            "group_id",
            existing_type=sa.INTEGER(),
            type_=sa.String(length=255),
            existing_nullable=False,
        )


def downgrade(name: str = "") -> None:
    if name:
        return
    with op.batch_alter_table("Group_config") as batch_op:
        batch_op.alter_column(
            "group_id",
            existing_type=sa.String(length=255),
            type_=sa.INTEGER(),
            existing_nullable=False,
        )
