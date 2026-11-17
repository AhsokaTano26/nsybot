import asyncio
import re

from nonebot import on_command
from nonebot.adapters import Event
from nonebot.adapters.qq import Bot, MessageSegment
from nonebot.adapters.qq.event import GroupMessageCreateEvent
from nonebot.rule import Rule
from nonebot.plugin import PluginMetadata
from nonebot.log import logger


NICKNAME_TIMEOUT = 5

__plugin_meta__ = PluginMetadata(
    name="群信息",
    description="获取当前群和发送人的 OpenID，尝试获取发送人昵称",
    usage="群信息 / group-info",
)

async def is_group_message(event: Event) -> bool:
    """仅允许 QQ 群消息进入群信息命令。"""
    return isinstance(event, GroupMessageCreateEvent)


# 不使用 to_me 规则，因此无需 @ 机器人。
group_info = on_command(
    "群信息",
    aliases={"group-info"},
    priority=10,
    rule=Rule(is_group_message),
    block=True,
)


@group_info.handle()
async def reply_group_message_info(bot: Bot, event: GroupMessageCreateEvent) -> None:
    """保留可复制的群/发送人 ID，昵称获取失败不影响回复。"""
    nickname = (event.author.username or "").strip()
    if not nickname:
        try:
            member = await asyncio.wait_for(
                bot.get_group_member(
                    group_openid=event.group_openid, member_openid=event.get_user_id(),
                ),
                timeout=NICKNAME_TIMEOUT,
            )
            nickname = (member.username or "").strip()
        except Exception as exc:
            logger.debug(f"获取发送人昵称失败，仍返回 OpenID：{type(exc).__name__}")
    nickname = re.sub(r"([\\`*_\[\]<>])", r"\\\1", " ".join((nickname or "未知").split()))
    await bot.send(
        event,
        MessageSegment.markdown(
            "# ℹ️ 当前群信息\n\n"
            "群 OpenID（可复制）：\n"
            f"```\n{event.group_openid}\n```\n\n"
            "发送人 OpenID（可复制）：\n"
            f"```\n{event.get_user_id()}\n```\n\n"
            f"发送人昵称：{nickname}"
        ),
    )
