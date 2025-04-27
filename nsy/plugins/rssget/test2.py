import json
import os
import httpx
import feedparser
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from bs4 import BeautifulSoup
from nonebot import get_bot, require, on_command
from nonebot.adapters.onebot.v11 import MessageSegment, Message
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.log import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler

require("apscheduler")
scheduler = AsyncIOScheduler()

__plugin_meta__ = PluginMetadata(
    name="Twitter定时推送",
    description="定时推送Twitter用户动态到指定群聊",
    usage=(
        "添加订阅: /rss_sub <用户名> <群号> <间隔分钟>\n"
        "移除订阅: /rss_unsub <用户名> <群号>\n"
        "列出订阅: /rss_list\n"
        "示例: /rss_sub aibaaiai 123456 60"
    ),
    type="application",
    homepage="https://github.com/your/repo",
)

# 配置文件路径
DATA_PATH = Path("data/twitter_rss")
SUB_FILE = DATA_PATH / "subscriptions.json"

# 初始化数据目录
DATA_PATH.mkdir(parents=True, exist_ok=True)

# 配置项
RSSHUB_HOST = "https://rsshub.app"  # RSSHub实例
CHECK_INTERVAL = 30  # 默认检查间隔（秒）
MAX_HISTORY = 5  # 最大历史记录存储数量


class SubscriptionManager:
    def __init__(self):
        self.subscriptions: Dict[str, List[dict]] = {}
        self.history: Dict[str, List[str]] = {}
        self.load_data()

    def load_data(self):
        """加载订阅数据"""
        try:
            if SUB_FILE.exists():
                with open(SUB_FILE, "r") as f:
                    data = json.load(f)
                    self.subscriptions = data.get("subscriptions", {})
                    self.history = data.get("history", {})
        except Exception as e:
            logger.error(f"加载订阅数据失败: {e}")

    def save_data(self):
        """保存订阅数据"""
        try:
            with open(SUB_FILE, "w") as f:
                json.dump({
                    "subscriptions": self.subscriptions,
                    "history": self.history
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存订阅数据失败: {e}")

    def add_subscription(self, username: str, group_id: str, interval: int):
        """添加订阅"""
        key = f"{username}_{group_id}"
        job_id = f"rss_job_{key}"

        # 移除现有任务
        self.remove_subscription(username, group_id)

        # 添加新任务
        scheduler.add_job(
            self.check_update,
            "interval",
            minutes=interval,
            id=job_id,
            args=(username, group_id),
            replace_existing=True
        )

        # 更新订阅数据
        self.subscriptions[key] = {
            "username": username,
            "group_id": group_id,
            "interval": interval,
            "last_checked": datetime.now().isoformat()
        }
        self.save_data()

    def remove_subscription(self, username: str, group_id: str):
        """移除订阅"""
        key = f"{username}_{group_id}"
        job_id = f"rss_job_{key}"

        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        if key in self.subscriptions:
            del self.subscriptions[key]
            self.save_data()
            return True
        return False

    async def check_update(self, username: str, group_id: str):
        """执行检查更新"""
        try:
            feed_url = f"{RSSHUB_HOST}/twitter/user/{username}"

            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(feed_url)
                feed = feedparser.parse(resp.content)

            if not feed.entries:
                return

            latest_entry = feed.entries[0]
            entry_id = latest_entry.id

            # 检查是否新内容
            history = self.history.get(username, [])
            if entry_id in history:
                return

            # 处理新内容
            content = self.parse_entry(latest_entry)
            await self.send_to_group(group_id, content)

            # 更新历史记录
            self.update_history(username, entry_id)

        except Exception as e:
            logger.error(f"定时任务执行失败: {e}")

    def update_history(self, username: str, entry_id: str):
        """更新历史记录"""
        self.history.setdefault(username, [])
        self.history[username].append(entry_id)
        # 保持最大历史记录数量
        if len(self.history[username]) > MAX_HISTORY:
            self.history[username] = self.history[username][-MAX_HISTORY:]
        self.save_data()

    def parse_entry(self, entry) -> dict:
        """解析推文内容"""
        published = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")

        clean_text = BeautifulSoup(entry.description, "html.parser").get_text("\n").strip()

        images = []
        for media in getattr(entry, "media_content", []):
            if media.get("type", "").startswith("image/"):
                images.append(media["url"])

        return {
            "title": entry.title,
            "time": published,
            "link": entry.link,
            "text": clean_text,
            "images": images[:3]
        }

    async def send_to_group(self, group_id: str, content: dict):
        """发送消息到群聊"""
        try:
            bot = get_bot()
            # 文字消息
            msg = [
                f"🐦 新推文推送 [{content['time']}]",
                f"📌 {content['title']}",
                f"🔗 {content['link']}",
                "\n📝 内容：",
                content['text']
            ]
            await bot.send_group_msg(group_id=int(group_id), message="\n".join(msg))

            # 图片消息
            for img_url in content["images"]:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(img_url)
                    img_seg = MessageSegment.image(resp.content)
                    await bot.send_group_msg(group_id=int(group_id), message=img_seg)

        except Exception as e:
            logger.error(f"群消息发送失败: {e}")


# 初始化订阅管理器
sub_manager = SubscriptionManager()

# 命令处理器
rss_sub = on_command("rss_sub", aliases={"订阅推特"}, priority=10)
rss_unsub = on_command("rss_unsub", aliases={"取消订阅"}, priority=10)
rss_list = on_command("rss_list", aliases={"订阅列表"}, priority=10)


@rss_sub.handle()
async def handle_subscribe(args: Message = CommandArg()):
    """添加订阅"""
    params = args.extract_plain_text().strip().split()
    if len(params) != 3:
        await rss_sub.finish("参数格式错误，正确格式：/rss_sub <用户名> <群号> <间隔分钟>")

    username, group_id, interval = params
    if not interval.isdigit():
        await rss_sub.finish("间隔时间必须为整数分钟")

    sub_manager.add_subscription(username, group_id, int(interval))
    await rss_sub.send(
        f"✅ 订阅成功\n"
        f"用户名: {username}\n"
        f"推送群组: {group_id}\n"
        f"检查间隔: {interval}分钟"
    )


@rss_unsub.handle()
async def handle_unsubscribe(args: Message = CommandArg()):
    """取消订阅"""
    params = args.extract_plain_text().strip().split()
    if len(params) != 2:
        await rss_unsub.finish("参数格式错误，正确格式：/rss_unsub <用户名> <群号>")

    username, group_id = params
    if sub_manager.remove_subscription(username, group_id):
        await rss_unsub.send(f"✅ 已取消 {username} 对群组 {group_id} 的订阅")
    else:
        await rss_unsub.send("❌ 未找到对应的订阅记录")


@rss_list.handle()
async def handle_list():
    """列出订阅"""
    if not sub_manager.subscriptions:
        await rss_list.finish("当前没有活跃订阅")

    msg = ["📋 当前订阅列表："]
    for sub in sub_manager.subscriptions.values():
        msg.append(
            f"· {sub['username']} → 群组 {sub['group_id']} "
            f"(每 {sub['interval']} 分钟检查)"
        )

    await rss_list.send("\n".join(msg))


# 启动定时任务
scheduler.start()
logger.info("Twitter定时推送服务已启动")


# 插件卸载时保存数据
def on_unload():
    sub_manager.save_data()