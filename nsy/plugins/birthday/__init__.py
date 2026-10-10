"""独立生日插件：每日 23:00 提醒手动修改群昵称。"""

from apscheduler.triggers.cron import CronTrigger
from nonebot import get_bot, get_driver, get_plugin_config, on_command, on_type, require
from nonebot.adapters.qq import Event, GroupDelRobotEvent, GroupMessageCreateEvent, Message
from nonebot.log import logger
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from sqlalchemy.exc import SQLAlchemyError

require("nonebot_plugin_orm")
from nonebot_plugin_orm import get_session

from nsy.qq_utils import error, info, markdown, send_group_message, user_openid

from .commands import HELP, execute_command
from .config import Config
from .service import run_reminders
from .store import BirthdayStore

__plugin_meta__ = PluginMetadata(
    name="生日提醒",
    description="按标签订阅生日，每日 23:00 提醒手动修改或恢复群昵称",
    usage=HELP,
    type="application",
    config=Config,
)

config = get_plugin_config(Config)
scheduler = require("nonebot_plugin_apscheduler").scheduler


async def birthday_remind() -> None:
    try:
        bot = get_bot()
    except ValueError:
        logger.warning("生日提醒未找到在线 Bot，本次任务跳过")
        return

    async def sender(group_id: str, message: str):
        return await send_group_message(bot, group_id, markdown(message))

    try:
        sent, failed = await run_reminders(sender, get_session)
        logger.info(f"生日提醒本次完成：已发送 {sent} 群，失败 {failed} 群")
    except SQLAlchemyError:
        logger.exception("生日提醒读取数据库失败")


if config.birthday_reminder_enabled:
    scheduler.add_job(
        birthday_remind,
        CronTrigger(hour=23, minute=0, timezone="Asia/Shanghai"),
        id="birthday:remind",
        replace_existing=True,
        misfire_grace_time=60,
        coalesce=True,
        max_instances=1,
    )

birthday_cmd = on_command("生日", aliases={"生日帮助"}, priority=10, block=True)


@birthday_cmd.handle()
async def handle_birthday(event: Event, args: Message = CommandArg()) -> None:
    group_id = str(event.group_openid) if isinstance(event, GroupMessageCreateEvent) else None
    try:
        is_superuser = user_openid(event) in set(get_driver().config.superusers)
        async with get_session() as session, session.begin():
            result = await execute_command(
                BirthdayStore(session), args.extract_plain_text(), group_id, is_superuser
            )
    except ValueError as exc:
        await birthday_cmd.finish(error(str(exc), "🎂 生日助手"))
    except SQLAlchemyError:
        logger.exception("生日命令数据库操作失败")
        await birthday_cmd.finish(error("生日数据操作失败，请查看日志后重试。", "🎂 生日助手"))
    await birthday_cmd.finish(markdown(result) if result.startswith("# ") else info(result, "🎂 生日助手"))


group_removed = on_type(GroupDelRobotEvent, priority=20, block=False)


@group_removed.handle()
async def handle_group_removed(event: GroupDelRobotEvent) -> None:
    async with get_session() as session, session.begin():
        await BirthdayStore(session).delete_group(str(event.group_openid))
    logger.info(f"已清理移出群 {event.group_openid} 的生日订阅及提醒状态")
