from nonebot import get_plugin_config, require, logger, get_driver, get_bot
from nonebot.plugin import PluginMetadata
import requests
from apscheduler.triggers.cron import CronTrigger

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="detect",
    description="此插件用于检测机器人连接状态",
    usage="",
    config=Config,
)

plugin_config = get_plugin_config(Config)

scheduler = require("nonebot_plugin_apscheduler").scheduler
@scheduler.scheduled_job(CronTrigger(minute="*/5"),misfire_grace_time=60)
async def test():
    if plugin_config.if_connected:
        requests.get('http://192.168.1.1:13001/api/push/gNtgnaJNoF?status=up&msg=OK&ping=')
        logger.info("成功发送请求")
    else:
        logger.debug("<机器人未连接>")

driver = get_driver()
@driver.on_bot_connect
async def handle_bot_connect(bot):
    # 当有新的机器人连接时触发
    plugin_config.if_connected = True
    logger.debug(f"机器人 {bot.self_id} 已连接！")
    bot = get_bot()
    await bot.call_api("send_group_msg", **{
        "group_id": plugin_config.target_groups,
        "message": f"nsybot已连接"
    })

@driver.on_bot_disconnect
async def handle_bot_disconnect(bot):
    plugin_config.if_connected = False
    logger.debug(f"机器人 {bot.self_id} 已断开连接！")