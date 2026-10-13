import os
import asyncio
from datetime import datetime, timedelta

from bs4 import BeautifulSoup
from nonebot import get_plugin_config
from nonebot.log import logger

from .config import Config
from .trans_msg import if_trans, remove_html_tag_soup
from .translation import Ali, BaiDu, DeepSeek, Ollama

config = get_plugin_config(Config)
MODEL_NAME = os.getenv('MODEL_NAME', None)


def _get_trans_platform() -> int:
    try:
        return int(os.getenv("TRANS_PLATFORM", "9"))
    except ValueError:
        return 0


TRANS_PLATFORM = _get_trans_platform()

PLATFORMS = {
    0: DeepSeek(),
    1: Ollama(),
    2: Ali(),
    3: BaiDu(),
    9: None,
}

TRANSLATION_TIMEOUT = 60


class Format:
    def __init__(self):
        pass

    async def format_content(self, content: dict) -> dict:
        text = dict()
        text["msg"] = [
            f"🐦 用户 {content['username']} 最新动态\n"
            f"⏰ {content['time']}\n"
            f"🔗 {content['link']}\n"
            f"{content['text']}"
        ]

        text["trans_msg"] = [
            f"{content['trans_text']}\n"
            f"翻译由{MODEL_NAME}提供】"
        ]

        text["images"] = content["images"]

        return text

    async def extract_content(self, entry, if_need_trans, translator=None) -> dict:
        """提取推文内容结构化数据"""

        parsed_date = entry.get("published_parsed") or entry.get("updated_parsed")
        try:
            dt = datetime(*parsed_date[:6]) + timedelta(hours=8)
            published = dt.strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, IndexError):
            published = entry.get("published") or entry.get("updated") or "未知时间"

        # 清理文本内容
        await if_trans(entry)
        description = entry.get("description") or entry.get("summary") or ""
        if not description and entry.get("content"):
            description = entry["content"][0].get("value", "")
        clean_text_old = await remove_html_tag_soup(description)
        clean_text = BeautifulSoup(clean_text_old, "html.parser").get_text("\n").strip()
        clean_text = clean_text or entry.get("title") or ""
        trans_text_final = None
        if if_need_trans == 1 and clean_text:
            trans = translator or PLATFORMS.get(TRANS_PLATFORM) or PLATFORMS[0]
            try:
                translated = await asyncio.wait_for(trans.main(clean_text), timeout=TRANSLATION_TIMEOUT)
                if translated:
                    trans_text_final = translated.replace("+", "\n")
            except Exception as exc:
                logger.warning(f"翻译暂不可用，将发送原文：{type(exc).__name__}")

        # 提取图片（优先媒体内容）
        images = []
        for media in entry.get("media_content", []):
            if media.get("type", "").startswith("image/") and media.get("url"):
                images.append(media["url"])

        # 如果媒体内容为空，尝试从附件获取
        if not images:
            for enc in entry.get("enclosures", []):
                url = enc.get("href") or enc.get("url")
                if enc.get("type", "").startswith("image/") and url:
                    images.append(url)

        if description:
            soup = BeautifulSoup(description, 'html.parser')
            for img in soup.find_all('img', src=True):
                images.append(img['src'])
        images = list(dict.fromkeys(images))

        return {
            "title": entry.get("title") or None,
            "time": published or None,
            "link": entry.get("link") or None,
            "text": clean_text or None,
            "trans_text": trans_text_final or None,
            "images": images or None,
        }
