"""定时推送插件。

按「群注册表」向指定群聊定时发送活动消息：代号到 group_openid 的映射来自配置
（``GROUP_<代号>``），消息内容来自 :mod:`nsy.plugins.broadcast.messages`。
"""

from apscheduler.triggers.cron import CronTrigger
from nonebot import get_bot, get_driver, get_plugin_config, on_command, require
from nonebot.adapters.qq import Event, Message
from nonebot.log import logger
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from nsy.qq_utils import (download_image, error, file_image, markdown,
                          send_group_message, success, user_openid)

from .config import Config
from .messages import MESSAGES, BroadcastMessage

__plugin_meta__ = PluginMetadata(
    name="定时推送",
    description="按群注册表向指定群聊定时发送活动消息",
    usage="推送 <代号>  # 超管手动触发一次定时推送",
    type="QQbot",
    config=Config,
)

config = get_plugin_config(Config)
scheduler = require("nonebot_plugin_apscheduler").scheduler


async def is_superuser(event: Event) -> bool:
    """仅超级管理员可手动触发推送。"""
    try:
        return user_openid(event) in set(get_driver().config.superusers)
    except ValueError:
        return False


async def send_broadcast(key: str) -> bool:
    """向该代号登记的群发送一条推送，供定时任务与手动命令共用。

    先发 Markdown 文本，再逐张发图片。文本发送失败即中止——没有配文时发图
    没有意义；单张图片失败只记日志并继续下一张。

    返回 ``True`` 仅表示 Markdown 文本已成功发出（后续图片仍可能失败）；
    未知代号、未配置群 OpenID、拿不到 bot 实例、文本发送失败均返回 ``False``。
    """
    message: BroadcastMessage | None = MESSAGES.get(key)
    if message is None:
        logger.error(f"未知的推送代号: {key}")
        return False

    group_id = config.group_registry.get(key)
    if not group_id:
        logger.error(f"推送 {key} 未配置群 OpenID，已跳过")
        return False

    try:
        bot = get_bot()
    except ValueError as e:
        logger.error(f"推送 {key} 未能获取 bot 实例: {e}")
        return False

    try:
        await send_group_message(bot, group_id, markdown(message.render()))
    except Exception as e:
        logger.opt(exception=True).error(f"推送 {key} 文本发送失败: {e}")
        return False

    failed_images = 0
    for index, url in enumerate(message.images, start=1):
        try:
            data, file_name = await download_image(url)
            await send_group_message(bot, group_id, file_image(data, file_name))
        except Exception as e:
            failed_images += 1
            logger.opt(exception=True).error(
                f"推送 {key} 第 {index} 张图片发送失败: {e}"
            )

    if failed_images:
        logger.warning(
            f"推送 {key} 文本已发送，但有 {failed_images} 张图片失败，"
            f"目标群 {group_id}"
        )
    else:
        logger.info(f"推送 {key} 已完成，目标群 {group_id}")
    return True


def _register_jobs() -> None:
    """登记定时任务；未配置群 OpenID 或未开启推送的代号会被跳过。"""
    for key, message in MESSAGES.items():
        if not config.group_registry.get(key):
            logger.warning(f"定时推送 {key} 未配置群 OpenID，跳过注册")
            continue
        if not config.push_enabled(key):
            logger.info(f"定时推送 {key} 未启用，跳过注册")
            continue
        scheduler.add_job(
            send_broadcast,
            CronTrigger(hour=",".join(map(str, message.hours)), minute=0),
            args=[key],
            id=f"broadcast:{key}",
            misfire_grace_time=60,
            replace_existing=True,
        )
        logger.info(f"已注册定时推送 {key}，每日 {message.hours} 时发送")


_register_jobs()


broadcast_cmd = on_command("推送", priority=10, block=True, rule=Rule(is_superuser))


@broadcast_cmd.handle()
async def handle_broadcast(args: Message = CommandArg()) -> None:
    """超管手动触发一次推送，不受推送开关限制。"""
    key = args.extract_plain_text().strip().upper()
    if key not in MESSAGES:
        available = "、".join(MESSAGES)
        await broadcast_cmd.finish(
            error(f"未知推送代号：{key or '（空）'}\n可用代号：{available}")
        )

    if not await send_broadcast(key):
        await broadcast_cmd.finish(
            error(
                f"推送 {key} 未发出。请确认该代号的群 OpenID 已配置"
                f"（GROUP_{key}），并查看日志中该次推送的具体原因。"
            )
        )
    await broadcast_cmd.finish(success(f"已向 {key} 登记的群发送推送"))
