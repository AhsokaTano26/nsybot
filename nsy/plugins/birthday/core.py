"""生日日期、群名称模板和提醒正文；不依赖 NoneBot 或数据库。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
NAME_TEMPLATES = {
    1: "{group_name}🎉@{name}生日快乐🎉",
    2: "{group_name}(@{name}生日快乐!)",
    3: "{group_name}(@{name}生日快乐🎂)",
}


def validate_date(value: str) -> str:
    """使用闰年校验，允许 02-29，但要求严格的 MM-DD 格式。"""
    if not re.fullmatch(r"[0-9]{2}-[0-9]{2}", value):
        raise ValueError("日期应为 MM-DD，例如 01-15。")
    try:
        date(2000, *map(int, value.split("-")))
    except ValueError:
        raise ValueError(f"无效生日日期：{value}。") from None
    return value


def validate_name(value: str, limit: int = 64) -> str:
    value = value.strip()
    if not value or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"名称需要 1–{limit} 个字符，不能包含换行或控制字符。")
    return value


def validate_group_name(value: str) -> str:
    # 为生日后缀留出空间；输出采用参考插件的 60 字符上限。
    return validate_name(value, 40)


def tomorrow_in_shanghai(now: datetime | None = None) -> date:
    now = now or datetime.now(SHANGHAI)
    if now.tzinfo is None:
        raise ValueError("当前时间需要包含时区。")
    return now.astimezone(SHANGHAI).date() + timedelta(days=1)


def birthday_name(group_name: str, names: list[str], style: int) -> str:
    validate_group_name(group_name)
    if style not in NAME_TEMPLATES:
        raise ValueError("生日格式必须是 1、2 或 3。")
    if not names:
        return group_name
    template = NAME_TEMPLATES[style]
    budget = 60 - len(template.format(group_name=group_name, name=""))
    joined = "&".join(names)
    if len(joined) > budget:
        suffix = f"等{len(names)}人" if len(names) > 1 else "…"
        joined = joined[:budget - len(suffix)].rstrip("&") + suffix
    return template.format(group_name=group_name, name=joined)


def code_block(value: str) -> str:
    return "```\n" + value.replace("```", "``\u200b`") + "\n```"


@dataclass(frozen=True)
class Reminder:
    group_id: str
    target_date: date
    names: tuple[str, ...]
    suggested_name: str
    previous_name: str

    @property
    def needs_change(self) -> bool:
        return self.suggested_name != self.previous_name

    def render(self) -> str:
        if self.names:
            reason = "明天过生日：" + "、".join(self.names)
            action = "请手动修改群昵称。"
        else:
            reason = "明天没有本群订阅的生日，请恢复原群昵称。"
            action = "请手动恢复群昵称。"
        return (
            f"# 🎂 生日群昵称提醒\n\n"
            f"日期：{self.target_date.isoformat()}\n\n"
            f"{action}\n\n"
            f"修改后的群昵称（可复制）：\n{code_block(self.suggested_name)}\n\n"
            # 把完整昵称放在名单之前，确保共享 Markdown 截断保留改名所需信息。
            f"{reason}"
        )
