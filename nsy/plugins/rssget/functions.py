import feedparser
import httpx
from datetime import datetime, timedelta
import time
from bs4 import BeautifulSoup
from nonebot import get_bot, get_plugin_config
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.log import logger
from nonebot_plugin_orm import get_session
from sqlalchemy.exc import SQLAlchemyError
import os

from .models_method import DetailManger, UserManger, ContentManger, PlantformManger, GroupconfigManger
from .get_id import get_id
from .update_text import get_text
from .update_text import update_text
from .trans_msg import if_trans, if_self_trans, remove_html_tag_soup
from .translation import BaiDu, Ollama, Ali
from .config import Config


async def User_get():
    async with (get_session() as db_session):
        sheet1 = await UserManger.get_all_student_id(db_session)
        return sheet1

async def User_name_get(id):
    async with (get_session() as db_session):
        sheet1 = await UserManger.get_Sign_by_student_id(db_session,id)
        return sheet1

# 配置项（按需修改）
try:
    RSSHUB_HOST = os.getenv('RSSHUB_HOST')  # RSSHub 实例地址 例如：http://127.0.0.1:1200
except:
    RSSHUB_HOST = "https://rsshub.app"

try:
    MODEL_NAME = os.getenv('MODEL_NAME')
except:
    MODEL_NAME = "None"
TIMEOUT = 30  # 请求超时时间
MAX_IMAGES = 10  # 最多发送图片数量
config = get_plugin_config(Config)



async def extract_content(entry,if_need_trans) -> dict:
    """提取推文内容结构化数据"""

    B = Ali()  # 初始化阿里翻译类
    # B = BaiDu()  # 初始化百度翻译类
    # B = Ollama() # 初始化Ollama翻译类

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
        trans_text = BeautifulSoup(clean_text_old, "html.parser").get_text("\n") #为翻译段落划分
        trans_text1 = B.main(trans_text)
        trans_text = trans_text1.replace("+", "\n")
    else:
        trans_text = None

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
        logger.opt(exception=False).error(f"RSS请求失败: {str(e)}")
        return {"error": f"获取内容失败: {str(e)}"}


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
            logger.opt(exception=False).error(f"意外错误|图片发送失败: {str(e)}  第 {num} 次重试")
            if num <= 3:
                await self.send_onebot_image(img_url, group_id, num)
            else:
                await bot.call_api("send_group_msg", **{
                    "group_id": group_id,
                    "message": f"意外错误|图片下载失败：{e} 已达到最大重试次数"
                })

    async def send_text(self,
                        group_id: int,
                        content: dict,
                        if_need_trans: int,
                        if_is_self_trans: bool,
                        if_is_trans: bool
                        ):

        async with (get_session() as db_session):
            bot = get_bot()
            if_need_trans = True if if_need_trans == 1 else False
            try:
                group_config = await GroupconfigManger.get_Sign_by_group_id(db_session, group_id)
                if group_config:
                    if_need_user_trans = group_config.if_need_trans
                    if_need_self_trans = group_config.if_need_self_trans
                    if_need_translate = group_config.if_need_translate
                    if_need_photo_num_mention = group_config.if_need_photo_num_mention
                else:
                    if_need_user_trans = True
                    if_need_self_trans = False
                    if_need_translate = True
                    if_need_photo_num_mention = True
            except SQLAlchemyError:
                logger.opt(exception=False).error(f"数据库错误")
                return
            if not ((if_is_self_trans and if_need_self_trans) or (if_is_trans and if_need_user_trans)):
                # 构建文字消息
                msg = [
                    f"🐦 用户 {content["username"]} 最新动态",
                    f"⏰ {content['time']}",
                    f"🔗 {content['link']}",
                    "\n📝 正文：",
                    content['text']
                ]

                await bot.call_api("send_group_msg", **{
                    "group_id": group_id,
                    "message": "\n".join(msg)
                })

                if if_need_trans and if_need_translate:
                    trans_msg = [
                        "📝 翻译：",
                        content["trans_text"],
                        f"【翻译由{MODEL_NAME}提供】"
                    ]

                    await bot.call_api("send_group_msg", **{
                        "group_id": group_id,
                        "message": "\n".join(trans_msg)
                    })

                logger.info("成功发送文字信息")

                # 发送图片（单独处理）
                if content["images"]:
                    if if_need_photo_num_mention:
                        await bot.call_api("send_group_msg", **{
                            "group_id": group_id,
                            "message": f"🖼️ 检测到 {len(content['images'])} 张图片..."
                        })
                    for index, img_url in enumerate(content["images"], 1):
                        await self.send_onebot_image(img_url, group_id, num=0)

                logger.info("成功发送图片信息")



    async def handle_rss(self,userid: str, group_id_list: list):
        """处理RSS推送"""
        async with (get_session() as db_session):
            sheet1 = await User_get()
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
                    logger.opt(exception=False).error(data["error"])

                if not data.get("entries"):
                    logger.info("该用户暂无动态或不存在")

                # 处理最新五条推文
                for data_number in range(0,3):
                    logger.info(f"正在处理 {userid} | {username} 的第 {data_number + 1} 条数据")
                    latest = data.entries[data_number]
                    trueid = await get_id(latest)
                    for group_id in group_id_list:
                        try:
                            logger.info(f"正在处理 {group_id} 对 {userid} | {username}的订阅")
                            id_with_group = trueid + "-" + str(group_id)
                            if_is_self_trans = await if_self_trans(username,latest)
                            if_is_trans = await if_trans(latest)
                            try:
                                existing_lanmsg = await ContentManger.get_Sign_by_student_id(
                                    db_session, trueid)
                                if existing_lanmsg:  # 本地数据库是否有推文内容
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
                                                if config.if_first_time_start:
                                                    logger.info("第一次启动，跳过发送")
                                                    logger.debug(f"if_first_time_start：{config.if_first_time_start}")
                                                else:
                                                    logger.debug(f"if_first_time_start：{config.if_first_time_start}")

                                                    await self.send_text(group_id=group_id,
                                                                         content=content,
                                                                         if_need_trans=if_need_trans,
                                                                         if_is_self_trans=if_is_self_trans,
                                                                         if_is_trans=if_is_trans,
                                                                         )

                                            except Exception as e:
                                                logger.opt(exception=False).error(
                                                    f"处理 {content.get('id')} 时发生错误: {e}")
                                    except SQLAlchemyError as e:
                                        logger.opt(exception=False).error(f"数据库操作错误: {e}")
                                else:  # 本地数据库没有推文内容
                                    logger.info(f"该 {trueid} 推文本地不存在")
                                    try:
                                        # 检查数据库中是否已存在该 id 的记录
                                        existing_lanmsg = await DetailManger.get_Sign_by_student_id(
                                            db_session, id_with_group)
                                        if existing_lanmsg:  # 更新记录
                                            logger.info(f"{id_with_group}已发送")
                                        else:
                                            content = await extract_content(latest, if_need_trans)
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
                                                if config.if_first_time_start:
                                                    logger.info("第一次启动，跳过发送")
                                                    logger.debug(f"if_first_time_start：{config.if_first_time_start}")
                                                else:
                                                    logger.debug(f"if_first_time_start：{config.if_first_time_start}")

                                                    await self.send_text(group_id=group_id,
                                                                         content=content,
                                                                         if_need_trans=if_need_trans,
                                                                         if_is_self_trans=if_is_self_trans,
                                                                         if_is_trans=if_is_trans,
                                                                         )

                                            except Exception as e:
                                                logger.opt(exception=False).error(
                                                    f"处理 {content.get('id')} 时发生错误: {e}")
                                    except SQLAlchemyError as e:
                                        logger.opt(exception=False).error(f"数据库操作错误: {e}")

                            except Exception as e:
                                logger.opt(exception=False).error(f"处理 {latest.get('title')} 时发生错误: {e}")
                            else:
                                logger.info(f"该 {trueid} 推文为自我转发，不发送")
                        except Exception as e:
                            logger.opt(exception=False).error(f"处理 {group_id} 对 {userid} 的订阅时发生错误: {e}")
                        time.sleep(0.1)
    async def change_config(self):
        config.if_first_time_start = False
    async def get_signal(self):
        return str(config.if_first_time_start)