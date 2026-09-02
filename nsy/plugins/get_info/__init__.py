from nonebot import on_command
from nonebot.adapters import Event
from nonebot.adapters.qq import Bot, MessageSegment
from nonebot.adapters.qq.event import GroupMessageCreateEvent
from nonebot.rule import Rule
from nonebot.plugin import PluginMetadata



__plugin_meta__ = PluginMetadata(
    name="群信息",
    description="此插件用于获取群聊id",
    usage="",
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
    """仅以可复制的 Markdown 代码块返回群 ID。"""
    await bot.send(
        event,
        MessageSegment.markdown(
            "# ℹ️ 当前群信息\n\n"
            "群 OpenID（可复制）：\n"
            f"```\n{event.group_openid}\n```"
        ),
    )
