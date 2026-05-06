import os
from datetime import datetime, timedelta

from bs4 import BeautifulSoup
from nonebot import get_plugin_config

from .config import Config
from .trans_msg import if_trans, remove_html_tag_soup
from .translation import Ali, BaiDu, DeepSeek, Ollama

config = get_plugin_config(Config)
MODEL_NAME = os.getenv('MODEL_NAME', None)
TRANS_PLATFORM = int(os.getenv('TRANS_PLATFORM', 9))

PLATFORMS = {
    0: DeepSeek(),
    1: Ollama(),
    2: Ali(),
    3: BaiDu(),
    9: None,
}

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

    async def extract_content(self, entry, if_need_trans) -> dict:
        """提取推文内容结构化数据"""

        trans = PLATFORMS.get(TRANS_PLATFORM)

        dt = datetime(*entry.published_parsed[:6]) + timedelta(hours=8)
        published = dt.strftime("%Y-%m-%d %H:%M")

        # 清理文本内容
        await if_trans(entry)
        clean_text_old = await remove_html_tag_soup(entry.description)
        clean_text = BeautifulSoup(clean_text_old, "html.parser").get_text("\n").strip()
        if if_need_trans == 1 and clean_text_old and trans:
            trans_text = BeautifulSoup(clean_text_old, "html.parser").get_text("\n")  # 为翻译段落划分
            trans_text1 = await trans.main(trans_text)
            trans_text_final = trans_text1.replace("+", "\n")
        else:
            trans_text_final = None

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
            "title": entry.title or None,
            "time": published or None,
            "link": entry.link or None,
            "text": clean_text or None,
            "trans_text": trans_text_final or None,
            "images": images or None,
        }
