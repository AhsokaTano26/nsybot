import requests
import json
import feedparser
import httpx
from datetime import datetime, timedelta
import time
from bs4 import BeautifulSoup
from nonebot import on_command, get_bot, require, Bot
from nonebot.adapters.onebot.v11 import MessageSegment, Message
from nonebot.log import logger
from nonebot_plugin_orm import get_session
from sqlalchemy.exc import SQLAlchemyError
import os


from .encrypt import encrypt
from .models_method import DetailManger, UserManger, ContentManger, PlantformManger
from .get_id import get_id
from .update_text import get_text
from .update_text import update_text
from .trans_msg import if_trans, if_self_trans, remove_html_tag_soup


async def User_get():
    async with (get_session() as db_session):
        sheet1 = await UserManger.get_all_student_id(db_session)
        return sheet1

async def User_name_get(id):
    async with (get_session() as db_session):
        sheet1 = await UserManger.get_Sign_by_student_id(db_session,id)
        return sheet1

# 配置项（按需修改）
RSSHUB_HOST = "http://192.168.1.1:1200"  # RSSHub 实例地址
TIMEOUT = 30  # 请求超时时间
MAX_IMAGES = 10  # 最多发送图片数量
API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')
#API_KEY = "oW4gFumamC9b6gx2ujAKsO1I"
#SECRET_KEY = "5HB8M0ik4F2sP35iQVSp7W9fPpAH7dUA"


async def extract_content(entry,if_need_trans) -> dict:
    """提取推文内容结构化数据"""
    B = BaiDu()
    publish_time = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
    dt = datetime.strptime(publish_time, "%Y-%m-%d %H:%M")
    # 增加指定小时
    new_dt = dt + timedelta(hours=8)
    # 格式化为字符串
    published = new_dt.strftime("%Y-%m-%d %H:%M")

    # 清理文本内容
    await if_trans(entry)
    clean_text_old = await remove_html_tag_soup(entry.description)
    clean_text = BeautifulSoup(clean_text_old, "html.parser").get_text("\n").strip()
    if if_need_trans == 1:
        trans_text1 = B.main(BeautifulSoup(clean_text_old, "html.parser").get_text("+"))
        trans_text = trans_text1.replace("+", "\n")
        trans_title = B.main(entry.title)
    else:
        trans_text = None
        trans_title = None

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
        "trans_title": trans_title,
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
            "from": "auto",
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
    async def send_onebot_image(self,img_url: str, group_id, num):
        """OneBot 专用图片发送方法"""
        bot = get_bot()
        num += 1
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

        except Exception as e:
            logger.error(f"意外错误|图片发送失败: {str(e)}  第 {num} 次重试")
            if num <= 3:
                await self.send_onebot_image(img_url, group_id, num)
            else:
                await bot.call_api("send_group_msg", **{
                    "group_id": group_id,
                    "message": f"意外错误|图片下载失败：{e} 已达到最大重试次数"
                })

    async def handle_rss(self,userid: str, group_id_list: list):
        """处理RSS推送"""
        async with (get_session() as db_session):
            sheet1 = await User_get()
            bot = get_bot()
            if userid in sheet1:
                plantform = await UserManger.get_Sign_by_student_id(db_session,userid)
                plantform = plantform.Plantform
                plantform_name = await PlantformManger.get_Sign_by_student_id(db_session,plantform)
                url = plantform_name.url
                if_need_trans = int(plantform_name.need_trans)
                feed_url = f"{RSSHUB_HOST}{url}{userid}"
                user = await User_name_get(userid)
                username = user.User_Name
                # 获取数据
                data = await fetch_feed(feed_url)

                if "error" in data:
                    logger.error(data["error"])

                if not data.get("entries"):
                    logger.error("该用户暂无动态或不存在")

                # 处理最新一条推文
                latest = data.entries[0]
                trueid = await get_id(latest)
                for group_id in group_id_list:
                    try:
                        logger.info(f"正在处理 {group_id} 对 {userid} 的订阅")
                        id_with_group = trueid + "-" + str(group_id)
                        flag = await if_self_trans(username,latest)
                        if flag != False:
                            try:
                                existing_lanmsg = await ContentManger.get_Sign_by_student_id(
                                    db_session, trueid)
                                if existing_lanmsg:     #本地数据库是否有推文内容
                                    logger.info(f"该 {trueid} 推文本地已存在")
                                    content = await get_text(trueid)
                                    try:
                                        # 检查数据库中是否已存在该 id 的记录
                                        existing_lanmsg = await DetailManger.get_Sign_by_student_id(
                                            db_session, id_with_group)
                                        if existing_lanmsg:  # 更新记录
                                            logger.info(f"{id_with_group} 已发送")
                                        else:
                                            try:
                                                # 写入数据库
                                                await DetailManger.create_signmsg(
                                                    db_session,
                                                    id=id_with_group,
                                                    summary=content['text'],
                                                    updated=datetime.now(),
                                                )
                                                logger.info(f"创建数据: {content.get('id')}")
                                                # 构建文字消息
                                                msg = [
                                                    f"🐦 用户 {content["username"]} 最新动态",
                                                    f"📌 {content['title']}",
                                                    f"⏰ {content['time']}",
                                                    f"🔗 {content['link']}",
                                                    "\n📝 正文：",
                                                    content['text']
                                                ]

                                                if if_need_trans == 1:
                                                    trans_msg = [
                                                        f"📌 {content['trans_title']}"
                                                        "\n📝 翻译：",
                                                        content["trans_text"],
                                                        "【翻译由百度文本翻译-通用版提供】"
                                                    ]

                                                # 先发送文字内容
                                                await bot.call_api("send_group_msg", **{
                                                    "group_id": group_id,
                                                    "message": "\n".join(msg)
                                                })
                                                if if_need_trans == 1:
                                                    await bot.call_api("send_group_msg", **{
                                                        "group_id": group_id,
                                                        "message": "\n".join(trans_msg)
                                                    })

                                                # 发送图片（单独处理）
                                                if content["images"]:
                                                    await bot.call_api("send_group_msg", **{
                                                        "group_id": group_id,
                                                        "message": f"🖼️ 检测到 {len(content['images'])} 张图片..."
                                                    })
                                                    for index, img_url in enumerate(content["images"], 1):
                                                        await rss_get.send_onebot_image(self, img_url, group_id,num=0)
                                            except Exception as e:
                                                logger.error(f"处理 {content.get('id')} 时发生错误: {e}")
                                    except SQLAlchemyError as e:
                                        logger.error(f"数据库操作错误: {e}")
                                else:   #本地数据库没有推文内容
                                    logger.info(f"该 {trueid} 推文本地不存在")
                                    try:
                                        # 检查数据库中是否已存在该 id 的记录
                                        existing_lanmsg = await DetailManger.get_Sign_by_student_id(
                                            db_session, id_with_group)
                                        if existing_lanmsg:  # 更新记录
                                            logger.info(f"{id_with_group}已发送")
                                        else:
                                            content = await extract_content(latest,if_need_trans)
                                            content["username"] = username
                                            content["id"] = trueid
                                            await update_text(content)
                                            try:
                                                # 写入数据库
                                                await DetailManger.create_signmsg(
                                                    db_session,
                                                    id=id_with_group,
                                                    summary=content['text'],
                                                    updated=datetime.now(),

                                                )
                                                logger.info(f"创建数据: {content.get('id')}")
                                                # 构建文字消息
                                                msg = [
                                                    f"🐦 用户 {content["username"]} 最新动态",
                                                    f"📌 {content['title']}",
                                                    f"⏰ {content['time']}",
                                                    f"🔗 {content['link']}",
                                                    "\n📝 正文：",
                                                    content['text']
                                                ]

                                                if if_need_trans == 1:
                                                    trans_msg = [
                                                        f"📌 {content['trans_title']}"
                                                        "\n📝 翻译：",
                                                        content["trans_text"],
                                                        "【翻译由百度文本翻译-通用版提供】"
                                                    ]

                                                # 先发送文字内容
                                                await bot.call_api("send_group_msg", **{
                                                    "group_id": group_id,
                                                    "message": "\n".join(msg)
                                                })
                                                if if_need_trans == 1:
                                                    await bot.call_api("send_group_msg", **{
                                                        "group_id": group_id,
                                                        "message": "\n".join(trans_msg)
                                                    })

                                                # 发送图片（单独处理）
                                                if content["images"]:
                                                    await bot.call_api("send_group_msg", **{
                                                        "group_id": group_id,
                                                        "message": f"🖼️ 检测到 {len(content['images'])} 张图片..."
                                                    })
                                                    for index, img_url in enumerate(content["images"], 1):
                                                        await rss_get.send_onebot_image(self, img_url, group_id, num=0)
                                            except Exception as e:
                                                logger.error(f"处理 {content.get('id')} 时发生错误: {e}")
                                    except SQLAlchemyError as e:
                                        logger.error(f"数据库操作错误: {e}")

                            except Exception as e:
                                logger.error(f"处理 {latest.get('title')} 时发生错误: {e}")
                        else:
                            logger.info(f"该 {trueid} 推文为自我转发，不发送")
                    except Exception as e:
                        logger.error(f"处理 {group_id} 对 {userid} 的订阅时发生错误: {e}")
                    time.sleep(3)