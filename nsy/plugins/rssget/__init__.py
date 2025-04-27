import feedparser
import httpx
from datetime import datetime
import time
from apscheduler.triggers.cron import CronTrigger
from bs4 import BeautifulSoup
from nonebot import on_command, get_bot, require, Bot
from nonebot.adapters.onebot.v11 import MessageSegment, Message
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.log import logger

from .functions import BaiDu, rss_get
from .models_method import DetailManger
from .models import Detail


__plugin_meta__ = PluginMetadata(
    name="Twitter RSS订阅",
    description="通过RSSHub获取Twitter用户最新动态并发送图片",
    usage="/rss [用户名]  # 获取指定用户最新推文",
    type="application",
    homepage="https://github.com/your/repo",
)
B = BaiDu()  # 初始化翻译类
R = rss_get()  # 初始化rss类
sheet1 = ["aibaaiai","aimi_sound","kudoharuka910","Sae_Otsuka","aoki__hina","Yuki_Nakashim","ttisrn_0710","tanda_hazuki",
          "bang_dream_info","sasakirico","Hina_Youmiya","Riko_kohara","okada_mei0519","AkaneY_banu","Kanon_Takao",
          "Kanon_Shizaki","bushi_creative","amane_bushi","hitaka_mashiro","kohinatamika","AyAsA_violin"]


# 配置项（按需修改）
RSSHUB_HOST = "https://rsshub.app"  # RSSHub 实例地址
TIMEOUT = 30  # 请求超时时间
MAX_IMAGES = 10  # 最多发送图片数量

scheduler = require("nonebot_plugin_apscheduler").scheduler

rss_cmd = on_command("rss",priority=10,block=True)



async def fetch_feed(url: str) -> dict:
    """异步获取并解析RSS内容"""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return feedparser.parse(resp.content)
    except Exception as e:
        logger.error(f"RSS请求失败: {str(e)}")
        return {"error": f"获取内容失败: {str(e)}"}


def extract_content(entry) -> dict:
    """提取推文内容结构化数据"""
    published = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")

    # 清理文本内容
    clean_text = BeautifulSoup(entry.description, "html.parser").get_text("\n").strip()
    trans_text = B.main(BeautifulSoup(entry.description, "html.parser").get_text(" "))

    # 提取图片（优先媒体内容）
    images = []
    for media in getattr(entry, "media_content", []):
        if media.get("type", "").startswith("image/"):
            images.append(media["url"])

    # 如果媒体内容为空，尝试从附件获取
    if not images:
        for enc in getattr(entry, "enclosures", []):
            if enc.get("type", "").startswith("image/"):
                images.append(enc.href)

    if hasattr(entry, 'description'):
        soup = BeautifulSoup(entry.description, 'html.parser')
        for img in soup.find_all('img', src=True):
            images.append(img['src'])

    return {
        "title": entry.title,
        "time": published,
        "link": entry.link,
        "text": clean_text,
        "trans_title": B.main(entry.title),
        "trans_text": trans_text,
        "images": images[:MAX_IMAGES]
    }


async def send_onebot_image(img_url: str):
    """OneBot 专用图片发送方法"""
    bot = get_bot()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # 下载图片数据
            resp = await client.get(img_url)
            resp.raise_for_status()

            # 构造图片消息段
            image_seg = MessageSegment.image(resp.content)

            # 发送图片
            await rss_cmd.send(image_seg)

    except httpx.HTTPError as e:
        logger.error(f"图片下载失败: {str(e)}")
        await rss_cmd.send(f"图片下载失败：{e}")
    except Exception as e:
        logger.error(f"图片发送失败: {str(e)}")
        await rss_cmd.send(f"图片发送失败：{e}")


@rss_cmd.handle()
async def handle_rss(args: Message = CommandArg()):
    username = args.extract_plain_text().strip()
    if not username:
        await rss_cmd.finish("请输入Twitter用户名，例如：/rss aibaaiai")
    elif username not in sheet1:
        await rss_cmd.finish("请求被否决")
    else:
        feed_url = f"{RSSHUB_HOST}/twitter/user/{username}"

        # 获取数据
        data = await fetch_feed(feed_url)
        if "error" in data:
            await rss_cmd.finish(data["error"])

        if not data.get("entries"):
            await rss_cmd.finish("该用户暂无动态或不存在")

        # 处理最新一条推文
        latest = data.entries[0]
        content = extract_content(latest)

        # 构建文字消息
        msg = [
            f"🐦 用户 {username} 最新动态",
            f"📌 {content['title']}",
            f"⏰ {content['time']}",
            f"🔗 {content['link']}",
            "\n📝 正文：",
            content['text'],
            f"📌 {content['trans_title']}"
            "\n📝 翻译：",
            content["trans_text"],
        ]

        # 先发送文字内容
        await rss_cmd.send("\n".join(msg))

        # 发送图片（单独处理）
        if content["images"]:
            await rss_cmd.send(f"🖼️ 检测到 {len(content['images'])} 张图片...")
            for index, img_url in enumerate(content["images"], 1):
                await send_onebot_image(img_url)


@scheduler.scheduled_job(CronTrigger(minute="*/10"))
async def auto_update_func():
    await R.handle_rss("aibaaiai", 1016925587)
    time.sleep(3)
    await R.handle_rss("bang_dream_info", 1016925587)
    time.sleep(3)
    await R.handle_rss("bang_dream_info", 824993838)
    time.sleep(3)
    await R.handle_rss("kohinatamika", 824993838)
    time.sleep(3)
    await R.handle_rss("AyAsA_violin", 824993838)
    time.sleep(3)
    await R.handle_rss("aimi_sound", 824993838)
