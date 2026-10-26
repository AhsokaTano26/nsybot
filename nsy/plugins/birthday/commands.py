"""生日命令；使用独立前缀，避免与 RSS 的订阅、成员和帮助命令冲突。"""

from __future__ import annotations

import csv
import re
import shlex
from pathlib import Path

from .core import NAME_TEMPLATES, code_block, tomorrow_in_shanghai, validate_date
from .service import preview
from .store import BirthdayStore

HELP = """# 🎂 生日助手

每天北京时间 23:00 检查明天的生日，需要改名时发送可复制的群昵称；生日结束后提醒恢复原名。

本群设置（群内所有成员可用）：
> `生日 群名 <原群昵称>` — 设置或修改原名
> `生日 订阅 <标签> <格式1-3>` — 订阅本群生日提醒
> `生日 退订 <标签>` — 取消订阅
> `生日 状态` — 查看本群设置
> `生日 预览` — 查看明天建议，不改变提醒状态

查询：
> `生日 成员 [月份1-12]`
> `生日 标签`

超管管理：
> `生日 导入预设` — 导入参考仓库的角色、声优生日
> `生日 增加成员 <名字> <MM-DD> [备注]`
> `生日 修改成员 <名字> <新名字或MM-DD>`
> `生日 删除成员 <名字>`
> `生日 批量导入 名字1 MM-DD, 名字2 MM-DD`
> `生日 增加标签 <标签>` / `生日 删除标签 <标签>`
> `生日 关联标签 <名字> <标签>` / `生日 取消关联 <名字> <标签>`
> `生日 查看订阅` — 查看全部生日群订阅
> `发送生日语录` — 引用消息后发送，支持富文本；群发至所有生日订阅群，自动排除来源群

三种格式：
1. 群名🎉@名字生日快乐🎉
2. 群名(@名字生日快乐!)
3. 群名(@名字生日快乐🎂)

名称含空格时用英文双引号包住；群名最长 40 个字符，为生日后缀预留空间。
"""

GLOBAL_MUTATIONS = {
    "增加成员", "修改成员", "删除成员", "批量导入", "导入预设",
    "增加标签", "删除标签", "关联标签", "取消关联", "查看订阅",
}
GROUP_COMMANDS = {"群名", "订阅", "退订", "状态", "预览"}


def parse_args(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        raise ValueError("参数引号未闭合；名称含空格时用英文双引号包住。") from None


def require_count(args: list[str], count: int, usage: str) -> None:
    if len(args) != count:
        raise ValueError(f"用法：生日 {usage}")


async def import_preset(store: BirthdayStore) -> int:
    """从参考仓库 CSV 导入，一人一条；保留已经手动录入/修改的生日。"""
    records: dict[str, tuple[str, set[str]]] = {}
    with (Path(__file__).parent / "data" / "bangdream.csv").open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            records[row["角色名称"]] = (validate_date(row["生日"]), {"BanG Dream", "角色"})
            names = [name.strip() for name in row["中之人"].split(",") if name.strip()]
            dates = [value.strip() for value in row["中之人生日"].split(",") if value.strip()]
            if len(names) != len(dates):
                raise ValueError("预设数据中的声优姓名与生日数量不一致。")
            for name, birthday in zip(names, dates):
                records[name] = (validate_date(birthday), {"BanG Dream", "声优"})
    existing_tags = {tag.name for tag in await store.list_tags()}
    for tag in ("BanG Dream", "角色", "声优"):
        if tag not in existing_tags:
            await store.add_tag(tag)
    existing_members = {member.name for member in await store.list_members()}
    added = 0
    for name, (birthday, tags) in records.items():
        if name not in existing_members:
            await store.add_member(name, birthday)
            added += 1
        for tag in sorted(tags):
            await store.bind_tag(name, tag)
    return added


async def execute_command(
    store: BirthdayStore, text: str, group_id: str | None, is_superuser: bool,
) -> str:
    text = text.strip()
    if not text or text in ("帮助", "help"):
        return HELP
    # 支持 QQ 输入框粘贴的换行/制表符作为命令与参数之间的空白。
    parts = text.split(None, 1)
    command, rest = parts[0], parts[1] if len(parts) > 1 else ""
    if command in GLOBAL_MUTATIONS and not is_superuser:
        raise ValueError("只有超级管理员可以管理全局生日数据或查看全群订阅。")
    if command in GROUP_COMMANDS and group_id is None:
        raise ValueError("请在目标 QQ 群内使用本群生日命令。")
    args = parse_args(rest)

    if command == "群名":
        if not rest.strip():
            raise ValueError("用法：生日 群名 <原群昵称>")
        name = args[0] if len(args) == 1 else rest.strip()
        await store.set_group_name(group_id, name)
        return f"本群原昵称已保存：\n{code_block(name)}\n\n接着发送：生日 订阅 <标签> <格式1-3>。"
    if command == "订阅":
        require_count(args, 2, "订阅 <标签> <格式1-3>")
        if args[1] not in ("1", "2", "3"):
            raise ValueError("生日格式必须是 1、2 或 3。")
        await store.subscribe(group_id, args[0], int(args[1]))
        return f"本群已订阅「{args[0]}」，格式 {args[1]}。每天 23:00 需要改名时提醒。"
    if command == "退订":
        require_count(args, 1, "退订 <标签>")
        await store.unsubscribe(group_id, args[0])
        return f"本群已退订「{args[0]}」。如之前已发过生日昵称，仍会提醒恢复原名。"
    if command == "状态":
        require_count(args, 0, "状态")
        group = await store.get_group(group_id)
        tags = "、".join(tag.name for tag in group.subscribed_tags) or "暂无订阅"
        template = NAME_TEMPLATES[group.birthday_type].format(group_name=group.group_name, name="名字")
        return (
            f"本群订阅：{tags}\n\n原群昵称：\n{code_block(group.group_name)}\n\n"
            f"生日格式 {group.birthday_type}：\n{code_block(template)}\n\n"
            f"上次成功发送的建议：\n{code_block(group.last_suggested_name)}"
        )
    if command == "预览":
        require_count(args, 0, "预览")
        return await preview(store, group_id, tomorrow_in_shanghai())
    if command == "成员":
        if len(args) > 1 or (args and not args[0].isdigit()):
            raise ValueError("用法：生日 成员 [月份1-12]")
        members = await store.list_members(month=int(args[0]) if args else None)
        lines = [f"{member.date} {member.name}" + (f" [{' / '.join(tag.name for tag in member.tags)}]" if member.tags else "") for member in members]
        return "\n".join(lines) or "暂无生日成员，请由超管导入预设或增加成员。"
    if command == "标签":
        require_count(args, 0, "标签")
        return "、".join(tag.name for tag in await store.list_tags()) or "暂无标签。"
    if command == "增加成员":
        if len(args) < 2:
            raise ValueError("用法：生日 增加成员 <名字> <MM-DD> [备注]")
        await store.add_member(args[0], args[1], " ".join(args[2:]))
        return f"已增加生日成员：{args[0]}（{args[1]}）。"
    if command == "修改成员":
        require_count(args, 2, "修改成员 <名字> <新名字或MM-DD>")
        await store.update_member(*args)
        return f"已修改成员「{args[0]}」。"
    if command == "删除成员":
        require_count(args, 1, "删除成员 <名字>")
        await store.delete_member(args[0])
        return f"已删除成员「{args[0]}」及其标签关联。"
    if command == "批量导入":
        members = []
        for item in re.split(r"[,，\n]", rest):
            if not item.strip():
                continue
            pair = parse_args(item)
            require_count(pair, 2, "批量导入 名字1 MM-DD, 名字2 MM-DD")
            members.append(tuple(pair))
        if not members:
            raise ValueError("用法：生日 批量导入 名字1 MM-DD, 名字2 MM-DD")
        added, updated = await store.upsert_members(members)
        return f"生日导入完成：新增 {added} 人，更新 {updated} 人，其余日期相同的成员保持不变。"
    if command == "导入预设":
        require_count(args, 0, "导入预设")
        added = await import_preset(store)
        return f"预设导入完成，新增 {added} 人；已存在的生日保持不变。可订阅：BanG Dream、角色、声优。"
    if command in ("增加标签", "删除标签"):
        require_count(args, 1, f"{command} <标签>")
        if command == "增加标签":
            await store.add_tag(args[0])
        else:
            await store.delete_tag(args[0])
        return f"已{command}「{args[0]}」。"
    if command in ("关联标签", "取消关联"):
        require_count(args, 2, f"{command} <名字> <标签>")
        await store.bind_tag(*args, remove=command == "取消关联")
        return f"已{command}：{args[0]} / {args[1]}。"
    if command == "查看订阅":
        require_count(args, 0, "查看订阅")
        groups = await store.list_groups()
        return "\n".join(
            f"{group.group_id}（{group.group_name}）：" + ("、".join(tag.name for tag in group.subscribed_tags) or "暂无订阅")
            for group in groups
        ) or "暂无生日群配置。"
    raise ValueError("未知生日命令。发送「生日 帮助」查看用法。")
