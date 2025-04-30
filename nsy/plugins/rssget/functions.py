import requests
import json
import feedparser
import httpx
from datetime import datetime
import time
from bs4 import BeautifulSoup
from nonebot import on_command, get_bot, require, Bot
from nonebot.adapters.onebot.v11 import MessageSegment, Message
from nonebot.log import logger
from nonebot_plugin_orm import get_session
from sqlalchemy.exc import SQLAlchemyError


from .models_method import DetailManger



sheet1 = ["aibaaiai","aimi_sound","kudoharuka910","Sae_Otsuka","aoki__hina","Yuki_Nakashim","ttisrn_0710","tanda_hazuki",
          "bang_dream_info","sasakirico","Hina_Youmiya","Riko_kohara","okada_mei0519","AkaneY_banu","Kanon_Takao",
          "Kanon_Shizaki","bushi_creative","amane_bushi","hitaka_mashiro","kohinatamika","AyAsA_violin","romance847",
          "yurishiibot","sakuragawa_megu"]


# 配置项（按需修改）
RSSHUB_HOST = "http://192.168.1.1:1200"  # RSSHub 实例地址
TIMEOUT = 30  # 请求超时时间
MAX_IMAGES = 10  # 最多发送图片数量
API_KEY = "oW4gFumamC9b6gx2ujAKsO1I"
SECRET_KEY = "5HB8M0ik4F2sP35iQVSp7W9fPpAH7dUA"


def extract_content(entry) -> dict:
    """提取推文内容结构化数据"""
    B = BaiDu()
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

async def fetch_feed(url: str) -> dict:
    """异步获取并解析RSS内容"""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            time.sleep(5)
            resp = await client.get(url)
            resp.raise_for_status()
            return feedparser.parse(resp.content)
    except Exception as e:
        logger.error(f"RSS请求失败: {str(e)}")
        return {"error": f"获取内容失败: {str(e)}"}



class BaiDu():
    def main(self, body=str):
        url = "https://aip.baidubce.com/rpc/2.0/mt/texttrans/v1?access_token=" + self.get_access_token()

        payload = json.dumps({
            "from": "jp",
            "to": "zh",
            "q": f"{body}"
        }, ensure_ascii=False)
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        response = requests.request("POST", url, headers=headers, data=payload.encode("utf-8"))

        json_result = response.text
        result = json.loads(json_result)

        # 提取单个 dst
        first_translation = result["result"]["trans_result"][0]["dst"]

        return first_translation


    def get_access_token(self):
        """
        使用 AK，SK 生成鉴权签名（Access Token）
        :return: access_token，或是None(如果错误)
        """
        url = "https://aip.baidubce.com/oauth/2.0/token"
        params = {"grant_type": "client_credentials", "client_id": API_KEY, "client_secret": SECRET_KEY}
        return str(requests.post(url, params=params).json().get("access_token"))



class rss_get():
    async def send_onebot_image(self,img_url: str, group_id):
        """OneBot 专用图片发送方法"""
        bot = get_bot()
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                # 下载图片数据
                resp = await client.get(img_url)
                resp.raise_for_status()

                # 构造图片消息段
                image_seg = MessageSegment.image(resp.content)

                # 发送图片
                await bot.call_api("send_group_msg", **{
                    "group_id": group_id,
                    "message": image_seg
                })

        except httpx.HTTPError as e:
            logger.error(f"图片下载失败: {str(e)}")
            await bot.call_api("send_group_msg", **{
                "group_id": group_id,
                "message": f"图片下载失败：{e}"
            })
        except Exception as e:
            logger.error(f"图片发送失败: {str(e)}")
            await bot.call_api("send_group_msg", **{
                "group_id": group_id,
                "message": f"图片下载失败：{e}"
            })

    async def handle_rss(self,username: str, group_id: int):
        """处理RSS推送"""
        async with (get_session() as db_session):
            bot = get_bot()
            if username in sheet1:
                feed_url = f"{RSSHUB_HOST}/twitter/user/{username}"
                # 获取数据
                data = await fetch_feed(feed_url)
                # 处理最新一条推文
                latest = data.entries[0]
                published = datetime(*latest.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
                trueid = published + str(group_id)
                try:
                    # 检查数据库中是否已存在该 Student_id 的记录
                    existing_lanmsg = await DetailManger.get_Sign_by_student_id(
                        db_session, trueid)
                    if existing_lanmsg:  # 更新记录
                        logger.info(f"{published}已存在")
                    else:
                        content = extract_content(latest)
                        try:
                            # 写入数据库
                            await DetailManger.create_signmsg(
                                db_session,
                                id=trueid,
                                summary=content['text'],
                            )
                            logger.info(f"创建数据: {content.get('time')}")
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
                            await bot.call_api("send_group_msg", **{
                                "group_id": group_id,
                                "message": "\n".join(msg)
                            })

                            # 发送图片（单独处理）
                            if content["images"]:
                                await bot.call_api("send_group_msg", **{
                                    "group_id": group_id,
                                    "message": f"🖼️ 检测到 {len(content['images'])} 张图片..."
                                })
                                for index, img_url in enumerate(content["images"], 1):
                                    await rss_get.send_onebot_image(self, img_url, group_id)
                        except Exception as e:
                            logger.error(f"处理 {content.get('time')} 时发生错误: {e}")
                except SQLAlchemyError as e:
                    logger.error(f"数据库操作错误: {e}")