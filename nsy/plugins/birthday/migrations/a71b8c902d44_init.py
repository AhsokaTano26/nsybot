"""Create independent birthday tables and delivery state.

Revision ID: a71b8c902d44
Revises: None
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "a71b8c902d44"
down_revision = None
branch_labels = ("birthday",)
depends_on = None


def upgrade(name: str = "") -> None:
    if name:
        return
    op.create_table(
        "birthday_tag",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_birthday_tag")),
        sa.UniqueConstraint("name", name=op.f("uq_birthday_tag_name")),
        info={"bind_key": "birthday"},
    )
    op.create_table(
        "birthday_member",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("date", sa.String(5), nullable=False),
        sa.Column("extra", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_birthday_member")),
        sa.UniqueConstraint("name", name=op.f("uq_birthday_member_name")),
        info={"bind_key": "birthday"},
    )
    op.create_index(op.f("ix_birthday_member_date"), "birthday_member", ["date"])
    op.create_table(
        "birthday_group",
        sa.Column("group_id", sa.String(255), nullable=False),
        sa.Column("group_name", sa.String(40), nullable=False),
        sa.Column("birthday_type", sa.Integer(), nullable=False),
        sa.Column("last_suggested_name", sa.String(60), nullable=False),
        sa.PrimaryKeyConstraint("group_id", name=op.f("pk_birthday_group")),
        info={"bind_key": "birthday"},
    )
    op.create_table(
        "birthday_member_tag",
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["birthday_member.id"], name=op.f("fk_birthday_member_tag_member_id_birthday_member"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["birthday_tag.id"], name=op.f("fk_birthday_member_tag_tag_id_birthday_tag"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("member_id", "tag_id", name=op.f("pk_birthday_member_tag")),
        info={"bind_key": "birthday"},
    )
    op.create_table(
        "birthday_group_tag",
        sa.Column("group_id", sa.String(255), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["birthday_group.group_id"], name=op.f("fk_birthday_group_tag_group_id_birthday_group"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["birthday_tag.id"], name=op.f("fk_birthday_group_tag_tag_id_birthday_tag"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "tag_id", name=op.f("pk_birthday_group_tag")),
        info={"bind_key": "birthday"},
    )


def downgrade(name: str = "") -> None:
    if name:
        return
    op.drop_table("birthday_group_tag")
    op.drop_table("birthday_member_tag")
    op.drop_table("birthday_group")
    op.drop_index(op.f("ix_birthday_member_date"), table_name="birthday_member")
    op.drop_table("birthday_member")
    op.drop_table("birthday_tag")
