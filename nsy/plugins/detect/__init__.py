from time import monotonic

import httpx
from apscheduler.triggers.cron import CronTrigger
from nonebot import get_bot, get_driver, get_plugin_config, logger, require
from nonebot.adapters.qq import Bot, MessageSegment
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

# QQ Gateway 会主动要求客户端重连。NoneBot 会在重连窗口触发一次断开和
# 一次连接回调，因此记录开始时间，将它呈现为一次网关切换而不是故障告警。
gateway_switch_started_at: dict[str, float] = {}


@scheduler.scheduled_job(CronTrigger(minute="*/5"), misfire_grace_time=60)
async def detect():
    try:
        bot = get_bot()
        if isinstance(bot, Bot) and bot.ready:
            logger.info(f"🟢 QQ Bot {bot.self_id} | 健康检查通过，已完成鉴权")
            async with httpx.AsyncClient() as client:
                await client.get(plugin_config.detect_url, timeout=10)
            logger.info("📡 状态检测请求已发送")
        else:
            logger.error("🔴 QQ Bot | 未就绪或连接断开")

    except Exception as e:
        logger.error(f"❌ 无法获取 Bot 状态: {e}")


driver = get_driver()


@driver.on_bot_connect
async def handle_bot_connect(bot):
    switch_started_at = gateway_switch_started_at.pop(bot.self_id, None)

    if switch_started_at is not None:
        elapsed = monotonic() - switch_started_at
        logger.info(f"✅ QQ Bot {bot.self_id} | 网关切换完成，会话已恢复（{elapsed:.1f} 秒）")
        return

    logger.info(f"🟢 QQ Bot {bot.self_id} | 已上线并完成鉴权")
    if isinstance(bot, Bot) and plugin_config.target_group_openid:
        await bot.send_to_group(
            group_openid=plugin_config.target_group_openid,
            message=MessageSegment.markdown(
                "# 🟢 nsybot 已上线\n\nQQ 官方 Bot 已连接并完成鉴权。"
            ),
        )


@driver.on_bot_disconnect
async def handle_bot_disconnect(bot):
    gateway_switch_started_at[bot.self_id] = monotonic()
    logger.info(f"🔄 QQ Bot {bot.self_id} | 网关要求重连，正在恢复会话…")
