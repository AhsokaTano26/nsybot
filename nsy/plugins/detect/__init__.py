import httpx
from apscheduler.triggers.cron import CronTrigger
from nonebot import get_bot, get_driver, get_plugin_config, logger, require
from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="detect",
    description="此插件用于检测机器人连接状态",
    usage="",
    config=Config,
)

plugin_config = get_plugin_config(Config)

scheduler = require("nonebot_plugin_apscheduler").scheduler


@scheduler.scheduled_job(CronTrigger(minute="*/5"), misfire_grace_time=60)
async def detect():
    try:
        bot = get_bot()
        status_data = await bot.get_status()
        is_online = status_data.get("online", False)
        is_good = status_data.get("good", False)

        if is_online and is_good:
            logger.info("🟢 OneBot 客户端运行良好，Bot 在线。")
            async with httpx.AsyncClient() as client:
                await client.get(plugin_config.detect_url, timeout=10)
            logger.info("成功发送状态检测请求")
        elif is_online and not is_good:
            logger.warning("🟡 Bot 在线，但客户端状态可能存在异常。")
        else:
            logger.error("🔴 OneBot 客户端已离线或连接断开。")

    except Exception as e:
        logger.error(f"❌ 无法获取 Bot 状态: {e}")


driver = get_driver()


@driver.on_bot_connect
async def handle_bot_connect(bot):
    logger.info(f"机器人 {bot.self_id} 已连接！")
    await bot.call_api("send_group_msg", **{
        "group_id": plugin_config.target_groups,
        "message": "nsybot已连接"
    })


@driver.on_bot_disconnect
async def handle_bot_disconnect(bot):
    logger.info(f"机器人 {bot.self_id} 已断开连接！")
