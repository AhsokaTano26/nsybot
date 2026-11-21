import os
import asyncio
import json
from datetime import datetime, timedelta

from bs4 import BeautifulSoup
from nonebot import get_plugin_config
from nonebot.log import logger

from .config import Config
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
_translation_capacity = asyncio.Semaphore(1)


def check_entry_size(entry):
    entry_bytes = len(json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
    if entry_bytes > config.rss_entry_max_bytes:
        raise ValueError("EntryTooLarge")


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

        check_entry_size(entry)

        parsed_date = entry.get("published_parsed") or entry.get("updated_parsed")
        try:
            dt = datetime(*parsed_date[:6]) + timedelta(hours=8)
            published = dt.strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, IndexError):
            published = entry.get("published") or entry.get("updated") or "未知时间"

        # 保留原始 HTML 中的全部图片，再移除引用正文；每条文章只解析一次。
        description = entry.get("description") or entry.get("summary") or ""
        if not description and entry.get("content"):
            description = entry["content"][0].get("value", "")
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

        soup = BeautifulSoup(description, "html.parser")
        try:
            for img in soup.find_all('img', src=True):
                images.append(img['src'])
            quotes = soup.find_all("div", class_="rsshub-quote")
            if quotes:
                logger.info("该推文为引用推文")
            for quote in quotes:
                quote.decompose()
            clean_text = soup.get_text("\n").strip() or entry.get("title") or ""
        finally:
            # BeautifulSoup 节点互相引用，主动释放后再等待翻译网络请求。
            soup.decompose()
        images = list(dict.fromkeys(images))

        trans_text_final = None
        if if_need_trans == 1 and clean_text:
            trans = translator or PLATFORMS.get(TRANS_PLATFORM) or PLATFORMS[0]
            try:
                async with _translation_capacity:
                    translated = await asyncio.wait_for(trans.main(clean_text), timeout=TRANSLATION_TIMEOUT)
                if translated:
                    trans_text_final = translated.replace("+", "\n")
            except Exception as exc:
                logger.warning(f"翻译暂不可用，将发送原文：{type(exc).__name__}")

        return {
            "title": entry.get("title") or None,
            "time": published or None,
            "link": entry.get("link") or None,
            "text": clean_text or None,
            "trans_text": trans_text_final or None,
            "images": images or None,
        }
