"""独立于 RSS 的生日表、标签和官方群订阅。"""

from __future__ import annotations

from nonebot_plugin_orm import Model
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship


class BirthdayMemberTag(Model):
    __tablename__ = "birthday_member_tag"
    member_id: Mapped[int] = mapped_column(
        ForeignKey("birthday_member.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("birthday_tag.id", ondelete="CASCADE"), primary_key=True
    )


class BirthdayGroupTag(Model):
    __tablename__ = "birthday_group_tag"
    group_id: Mapped[str] = mapped_column(
        ForeignKey("birthday_group.group_id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("birthday_tag.id", ondelete="CASCADE"), primary_key=True
    )


class BirthdayTag(Model):
    __tablename__ = "birthday_tag"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)


class BirthdayMember(Model):
    __tablename__ = "birthday_member"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    date: Mapped[str] = mapped_column(String(5), index=True)
    extra: Mapped[str] = mapped_column(String(255), default="")
    tags: Mapped[list[BirthdayTag]] = relationship(
        secondary="birthday_member_tag", lazy="selectin"
    )


class BirthdayGroup(Model):
    __tablename__ = "birthday_group"
    group_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    group_name: Mapped[str] = mapped_column(String(40))
    birthday_type: Mapped[int] = mapped_column(default=1)
    # 记录已成功发送的建议，不代表用户已经在 QQ 客户端完成改名。
    last_suggested_name: Mapped[str] = mapped_column(String(60))
    subscribed_tags: Mapped[list[BirthdayTag]] = relationship(
        secondary="birthday_group_tag", lazy="selectin"
    )
