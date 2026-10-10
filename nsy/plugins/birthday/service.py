"""逐群生成生日提醒，只有发送成功才持久化建议名称。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime

from nonebot.log import logger
from sqlalchemy.ext.asyncio import AsyncSession

from .core import Reminder, birthday_name, tomorrow_in_shanghai
from .models import BirthdayGroup, BirthdayMember
from .store import BirthdayStore


def make_reminder(
    group: BirthdayGroup, members: list[BirthdayMember], target_date: date,
) -> Reminder:
    tag_ids = {tag.id for tag in group.subscribed_tags}
    # 每个群仅使用自己订阅的成员；多标签命中的同一成员只出现一次。
    names = tuple(
        member.name for member in members
        if tag_ids.intersection(tag.id for tag in member.tags)
    )
    return Reminder(
        group_id=group.group_id,
        target_date=target_date,
        names=names,
        suggested_name=birthday_name(group.group_name, list(names), group.birthday_type),
        previous_name=group.last_suggested_name,
    )


async def preview(store: BirthdayStore, group_id: str, target_date: date) -> str:
    group = await store.get_group(group_id)
    members = await store.list_members(birthday=target_date.strftime("%m-%d"))
    reminder = make_reminder(group, members, target_date)
    text = reminder.render()
    if not reminder.needs_change:
        text += "\n\n建议名称与上次一致，定时任务不会重复提醒。"
    return text


async def run_reminders(
    sender: Callable[[str, str], Awaitable[object]],
    session_factory: Callable[[], AsyncSession],
    now: datetime | None = None,
) -> tuple[int, int]:
    """返回 (成功提醒数, 失败数)；日期始终取上海时区的明天。"""
    target_date = tomorrow_in_shanghai(now)
    async with session_factory() as session:
        store = BirthdayStore(session)
        members = await store.list_members(birthday=target_date.strftime("%m-%d"))
        reminders = [make_reminder(group, members, target_date) for group in await store.list_groups()]

    sent = failed = 0
    for reminder in reminders:
        if not reminder.needs_change:
            continue
        try:
            await sender(reminder.group_id, reminder.render())
            async with session_factory() as session, session.begin():
                await BirthdayStore(session).record_delivery(
                    reminder.group_id, reminder.suggested_name
                )
        except Exception as exc:
            failed += 1
            logger.warning(f"生日提醒发送或记录失败，群 {reminder.group_id}: {exc}")
            continue
        sent += 1
        logger.info(f"生日提醒已发送，群 {reminder.group_id}，目标日期 {target_date}")
    return sent, failed
