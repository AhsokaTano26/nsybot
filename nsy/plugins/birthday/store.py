"""生日数据操作；事务由调用方管理，所有查询会在会话关闭前预加载标签。"""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .core import validate_date, validate_group_name, validate_name
from .models import (BirthdayGroup, BirthdayGroupTag, BirthdayMember,
                     BirthdayMemberTag, BirthdayTag)


class BirthdayStore:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_member(self, name: str) -> BirthdayMember:
        member = await self.session.scalar(
            select(BirthdayMember).where(BirthdayMember.name == name)
        )
        if member is None:
            raise ValueError(f"成员「{name}」不存在。")
        return member

    async def get_tag(self, name: str) -> BirthdayTag:
        tag = await self.session.scalar(
            select(BirthdayTag).where(BirthdayTag.name == name)
        )
        if tag is None:
            raise ValueError(f"标签「{name}」不存在。")
        return tag

    async def get_group(self, group_id: str) -> BirthdayGroup:
        group = await self.session.get(BirthdayGroup, group_id)
        if group is None:
            raise ValueError("请先发送：生日 群名 <原群昵称>。")
        return group

    async def add_member(self, name: str, birthday: str, extra: str = "") -> None:
        name = validate_name(name)
        validate_date(birthday)
        if len(extra) > 255:
            raise ValueError("备注不能超过 255 个字符。")
        if await self.session.scalar(select(BirthdayMember.id).where(BirthdayMember.name == name)):
            raise ValueError(f"成员「{name}」已存在。")
        self.session.add(BirthdayMember(name=name, date=birthday, extra=extra, tags=[]))
        await self.session.flush()

    async def update_member(self, name: str, value: str) -> None:
        member = await self.get_member(name)
        if "-" in value and value.replace("-", "").isdigit():
            member.date = validate_date(value)
        else:
            new_name = validate_name(value)
            duplicate = await self.session.scalar(
                select(BirthdayMember.id).where(BirthdayMember.name == new_name)
            )
            if duplicate and duplicate != member.id:
                raise ValueError(f"成员「{new_name}」已存在。")
            member.name = new_name
        await self.session.flush()

    async def upsert_members(self, members: list[tuple[str, str]]) -> tuple[int, int]:
        # 全部验证通过后才开始写入，避免批量操作的前半部分意外入库。
        for name, birthday in members:
            validate_name(name)
            validate_date(birthday)
        added = updated = 0
        for name, birthday in members:
            member = await self.session.scalar(
                select(BirthdayMember).where(BirthdayMember.name == name)
            )
            if member is None:
                await self.add_member(name, birthday)
                added += 1
            elif member.date != birthday:
                member.date = birthday
                updated += 1
        await self.session.flush()
        return added, updated

    async def delete_member(self, name: str) -> None:
        member = await self.get_member(name)
        # 由 ORM 清理已预加载的多对多关系，避免手动 DELETE 后再次删除关联行。
        member.tags.clear()
        await self.session.delete(member)

    async def list_members(self, month: int | None = None, birthday: str | None = None):
        stmt = select(BirthdayMember).order_by(BirthdayMember.date, BirthdayMember.name)
        if month is not None:
            if not 1 <= month <= 12:
                raise ValueError("月份应为 1–12。")
            stmt = stmt.where(BirthdayMember.date.like(f"{month:02d}-%"))
        if birthday is not None:
            stmt = stmt.where(BirthdayMember.date == birthday)
        return list((await self.session.scalars(stmt)).all())

    async def add_tag(self, name: str) -> None:
        name = validate_name(name)
        if await self.session.scalar(select(BirthdayTag.id).where(BirthdayTag.name == name)):
            raise ValueError(f"标签「{name}」已存在。")
        self.session.add(BirthdayTag(name=name))
        await self.session.flush()

    async def delete_tag(self, name: str) -> None:
        tag = await self.get_tag(name)
        for model in (BirthdayMemberTag, BirthdayGroupTag):
            await self.session.execute(delete(model).where(model.tag_id == tag.id))
        await self.session.delete(tag)

    async def list_tags(self):
        return list((await self.session.scalars(select(BirthdayTag).order_by(BirthdayTag.name))).all())

    async def bind_tag(self, member_name: str, tag_name: str, remove: bool = False) -> None:
        member = await self.get_member(member_name)
        tag = await self.get_tag(tag_name)
        if remove:
            if tag in member.tags:
                member.tags.remove(tag)
        elif tag not in member.tags:
            member.tags.append(tag)
        await self.session.flush()

    async def set_group_name(self, group_id: str, name: str) -> None:
        name = validate_group_name(name)
        group = await self.session.get(BirthdayGroup, group_id)
        if group is None:
            self.session.add(BirthdayGroup(
                group_id=group_id, group_name=name, birthday_type=1,
                last_suggested_name=name, subscribed_tags=[],
            ))
        else:
            group.group_name = name
        await self.session.flush()

    async def subscribe(self, group_id: str, tag_name: str, style: int) -> None:
        if style not in (1, 2, 3):
            raise ValueError("生日格式必须是 1、2 或 3。")
        group = await self.get_group(group_id)
        tag = await self.get_tag(tag_name)
        group.birthday_type = style
        if tag not in group.subscribed_tags:
            group.subscribed_tags.append(tag)
        await self.session.flush()

    async def unsubscribe(self, group_id: str, tag_name: str) -> None:
        group = await self.get_group(group_id)
        tag = await self.get_tag(tag_name)
        if tag not in group.subscribed_tags:
            raise ValueError(f"本群未订阅「{tag_name}」。")
        group.subscribed_tags.remove(tag)
        # 保留群配置和上次建议，用于最后一个标签退订后的恢复提醒。
        await self.session.flush()

    async def list_groups(self):
        return list((await self.session.scalars(select(BirthdayGroup).order_by(BirthdayGroup.group_id))).all())

    async def record_delivery(self, group_id: str, suggested_name: str) -> None:
        await self.session.execute(
            update(BirthdayGroup).where(BirthdayGroup.group_id == group_id)
            .values(last_suggested_name=suggested_name)
        )

    async def delete_group(self, group_id: str) -> None:
        await self.session.execute(delete(BirthdayGroupTag).where(BirthdayGroupTag.group_id == group_id))
        await self.session.execute(delete(BirthdayGroup).where(BirthdayGroup.group_id == group_id))
