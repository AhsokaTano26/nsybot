import feedparser
import httpx
from datetime import datetime, timedelta
import time
from apscheduler.triggers.cron import CronTrigger
from bs4 import BeautifulSoup
from nonebot import on_command, get_bot, require, Bot, get_plugin_config
from nonebot.adapters.onebot.v11 import MessageSegment, Message, GroupMessageEvent, GROUP_ADMIN, GROUP_OWNER
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.log import logger
from nonebot.rule import to_me
from nonebot_plugin_orm import get_session
from sqlalchemy.exc import SQLAlchemyError
import os

from .functions import BaiDu, rss_get
from .models_method import DetailManger, SubscribeManger, UserManger, ContentManger, PlantformManger
from .models import Detail
from .encrypt import encrypt
from .update_text import update_text, get_text
from .get_id import get_id
from .config import Config


__plugin_meta__ = PluginMetadata(
    name="Twitter RSS订阅",
    description="通过RSSHub获取Twitter用户最新动态并发送图片",
    usage="/rss [用户名]  # 获取指定用户最新推文",
    type="QQbot",
    homepage="https://github.com/your/repo",
)
B = BaiDu()  # 初始化翻译类
R = rss_get()  # 初始化rss类
config = get_plugin_config(Config)
logger.add("data/log/info_log.txt", level="DEBUG",rotation="10 MB")
logger.add("data/log/error_log.txt", level="ERROR",rotation="10 MB")
REFRESH_TIME = int(os.getenv('REFRESH_TIME'))
# 配置项（按需修改）
RSSHUB_HOST = os.getenv('RSSHUB_HOST')  # RSSHub 实例地址 例如：http://127.0.0.1:1200
TIMEOUT = 30  # 请求超时时间
MAX_IMAGES = 10  # 最多发送图片数量

scheduler = require("nonebot_plugin_apscheduler").scheduler

async def ignore_group(event: GroupMessageEvent) -> bool:
    """检查是否在忽略的群中"""
    a = int(event.group_id)
    if a in config.ignored_groups:
        return False
    return True

async def User_get() -> set:
    async with (get_session() as db_session):
        sheet1 = await UserManger.get_all_student_id(db_session)
        return sheet1

async def User_name_get(id) -> set:
    async with (get_session() as db_session):
        sheet1 = await UserManger.get_Sign_by_student_id(db_session,id)
        return sheet1


async def fetch_feed(url: str) -> dict:
    """异步获取并解析RSS内容"""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return feedparser.parse(resp.content)
    except Exception as e:
        logger.opt(exception=False).error(f"RSS请求失败: {str(e)}")
        return {"error": f"获取内容失败: {str(e)}"}


def extract_content(entry,if_need_trans) -> dict:
    """提取推文内容结构化数据"""
    publish_time = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
    dt = datetime.strptime(publish_time, "%Y-%m-%d %H:%M")
    # 增加指定小时
    new_dt = dt + timedelta(hours=8)
    # 格式化为字符串
    published = new_dt.strftime("%Y-%m-%d %H:%M")

    # 清理文本内容
    clean_text = BeautifulSoup(entry.description, "html.parser").get_text("\n").strip()
    if if_need_trans == 1:
        trans_text1 = B.main(BeautifulSoup(entry.description, "html.parser").get_text("+"))
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


async def send_onebot_image(img_url: str):
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
            await rss_cmd.send(image_seg)

    except httpx.HTTPError as e:
        logger.opt(exception=False).error(f"图片下载失败: {str(e)}")
        await rss_cmd.send(f"图片下载失败：{e}")
    except httpx.TimeoutException as e:
        logger.opt(exception=False).error(f"连接超时|图片下载失败: {str(e)}")
        await rss_cmd.send(f"连接超时|图片下载失败：{e}")
    except Exception as e:
        logger.opt(exception=False).error(f"意外错误|图片发送失败: {str(e)}")
        await rss_cmd.send(f"意外错误|图片发送失败：{e}")



rss_cmd = on_command("rss",priority=10,block=True,rule=ignore_group)

@rss_cmd.handle()
async def handle_rss(event: GroupMessageEvent,args: Message = CommandArg()):
    logger.info(f"从群 {event.group_id} 发起RSS_Hub请求")

    command = args.extract_plain_text().strip()
    userid = command.split(" ")[0]
    try:
        num = int(command.split(" ")[1])
    except:
        num = 0
    sheet1 = await User_get()
    if not userid:
        await rss_cmd.finish("请输入Twitter用户名，例如：/rss aibaaiai")
    elif userid not in sheet1:
        await rss_cmd.finish("请求被否决")
    else:
        async with (get_session() as db_session):
            plantform = await UserManger.get_Sign_by_student_id(db_session, userid)
            plantform = plantform.Plantform
            plantform_name = await PlantformManger.get_Sign_by_student_id(db_session, plantform)
            url = plantform_name.url
            if_need_trans = int(plantform_name.need_trans)
            feed_url = f"{RSSHUB_HOST}{url}{userid}"
            user = await User_name_get(userid)
            username = user.User_Name

            # 获取数据
            data = await fetch_feed(feed_url)
            if "error" in data:
                await rss_cmd.finish(data["error"])

            if not data.get("entries"):
                await rss_cmd.finish("该用户暂无动态或不存在")

            # 处理最新一条推文
            latest = data.entries[num]
            trueid = await get_id(latest)
            try:
                async with (get_session() as db_session):
                    existing_lanmsg = await ContentManger.get_Sign_by_student_id(
                        db_session, trueid)
                    if existing_lanmsg:  # 如有记录
                        logger.info(f"该 {trueid} 推文已存在")
                        content = await get_text(trueid)    #从本地数据库获取信息
                        msg = [
                            f"🐦 用户 {username} 最新动态",
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
                                content["trans_text"]
                            ]
                        # 先发送文字内容
                        await rss_cmd.send("\n".join(msg))
                        if if_need_trans == 1:
                            await rss_cmd.send("\n".join(trans_msg))

                        # 发送图片（单独处理）
                        if int(content["image_num"]) != 0:
                            await rss_cmd.send(f"🖼️ 检测到 {int(content['image_num'])} 张图片...")
                            for index, img_url in enumerate(content["images"], 1):
                                await send_onebot_image(img_url)
                    else:   #从RSSHUB获取信息
                        content = extract_content(latest,if_need_trans)
                        content["username"] = username
                        content["id"] = trueid
                        await update_text(content)
                        # 构建文字消息
                        msg = [
                            f"🐦 用户 {username} 最新动态",
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
                                content["trans_text"]
                            ]
                        # 先发送文字内容
                        await rss_cmd.send("\n".join(msg))
                        if if_need_trans == 1:
                            await rss_cmd.send("\n".join(trans_msg))

                        # 发送图片（单独处理）
                        if content["images"]:
                            await rss_cmd.send(f"🖼️ 检测到 {len(content['images'])} 张图片...")
                            for index, img_url in enumerate(content["images"], 1):
                                await send_onebot_image(img_url)
            except Exception as e:
                logger.opt(exception=False).error(f"数据库操作错误: {e}")


rss_sub = on_command("rss_sub", aliases={"订阅"}, priority=10, permission=SUPERUSER | GROUP_OWNER |GROUP_ADMIN,rule=ignore_group)
rss_unsub = on_command("rss_unsub", aliases={"取消订阅"}, priority=10, permission=SUPERUSER |GROUP_OWNER |GROUP_ADMIN,rule=ignore_group)
rss_list = on_command("rss_list", aliases={"订阅列表"}, priority=10,rule=ignore_group)

@rss_sub.handle()
async def handle_rss(args: Message = CommandArg()):
    command = args.extract_plain_text().strip()
    username = str(command.split(" ")[0])
    group_id = str(command.split(" ")[1])
    try:
        group_id = int(group_id)
        group_id = str(group_id)
    except:
        await rss_sub.finish("群号格式错误")
    sheet1 = await User_get()
    if username not in sheet1:
        await rss_sub.finish(f"用户名 {username} 不在可访问列表中")
    true_id = username + "-" + group_id
    async with (get_session() as db_session):
        try:
            # 检查数据库中是否已存在该 Student_id 的记录
            existing_lanmsg = await SubscribeManger.get_Sign_by_student_id(
                db_session, true_id)
            if existing_lanmsg:  # 更新记录
                logger.info(f"群{group_id}对于{username}的订阅已存在")
                await rss_sub.send(f"群{group_id}对于{username}的订阅已存在")
            else:
                try:
                    # 写入数据库
                    await SubscribeManger.create_signmsg(
                        db_session,
                        id=true_id,
                        username=username,
                        group=group_id,
                    )
                    await rss_sub.send(
                        f"✅ 订阅成功\n"
                        f"用户名: {username}\n"
                        f"推送群组: {group_id}\n"
                    )
                except Exception as e:
                    logger.opt(exception=False).error(f"创建群{group_id}对于{username}的订阅时发生错误: {e}")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")

@rss_unsub.handle()
async def handle_rss(args: Message = CommandArg()):
    command = args.extract_plain_text().strip()
    username = str(command.split(" ")[0])
    group_id = str(command.split(" ")[1])
    true_id = username + "-" + group_id
    async with (get_session() as db_session):
        try:
            # 检查数据库中是否已存在该 Student_id 的记录
            existing_lanmsg = await SubscribeManger.get_Sign_by_student_id(
                db_session, true_id)
            if not existing_lanmsg:  # 更新记录
                logger.info(f"群{group_id}对于{username}的订阅不存在")
                await rss_sub.send(f"群{group_id}对于{username}的订阅不存在")
            else:
                try:
                    # 写入数据库
                    await SubscribeManger.delete_id(db_session,id=true_id)
                    await rss_unsub.send(
                        f"✅ 订阅取消成功\n"
                        f"用户名: {username}\n"
                        f"推送群组: {group_id}\n"
                    )
                except Exception as e:
                    logger.opt(exception=False).error(f"取消群{group_id}对于{username}的订阅时发生错误: {e}")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")

@rss_list.handle()
async def handle_rss(args: Message = CommandArg()):
    async with (get_session() as db_session):
        msg = "📋 当前订阅列表：\n"
        sub_list = {}
        try:
            flag = await SubscribeManger.is_database_empty(db_session)
            if flag:
                await rss_list.send("当前无订阅")
            else:
                all = await SubscribeManger.get_all_student_id(db_session)
                for id in all:
                    try:
                        data1 = await SubscribeManger.get_Sign_by_student_id(db_session, id)
                        username = data1.username
                        sub_list[username] = []
                    except Exception as e:
                        logger.opt(exception=False).error(f"对于{username}的订阅时发生错误: {e}")
                logger.success("已获取所有用户名")
                for id in all:
                    try:
                        data1 = await SubscribeManger.get_Sign_by_student_id(db_session, id)
                        username = data1.username
                        group = int(data1.group)
                        sub_list.get(username).append(group)
                    except Exception as e:
                        logger.opt(exception=False).error(f"群{group}对于{username}的订阅时发生错误: {e}")
                logger.success("已获取所有群号")
                for user in sub_list:
                    user_datil = await UserManger.get_Sign_by_student_id(db_session, user)
                    user_name = user_datil.User_Name
                    msg += f"用户ID: {user}\n"
                    msg += f"用户名: {user_name}\n"
                    for group in sub_list[user]:
                        msg += f"    推送群组: {group}\n"
                    msg += "\n"
                await rss_unsub.send(msg,end="")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")



user_sub = on_command("user_sub", aliases={"增加用户"}, priority=10, permission=SUPERUSER,rule=ignore_group)
user_unsub = on_command("user_unsub", aliases={"删除用户"}, priority=10, permission=SUPERUSER,rule=ignore_group)
user_list = on_command("user_list", aliases={"用户列表"}, priority=10,rule=ignore_group)
@user_sub.handle()
async def handle_rss(args: Message = CommandArg()):
    """
    增加可访问用户列表中用户
    """
    command = args.extract_plain_text().strip()
    user_id = str(command.split(" ")[0])
    user_name = str(command.split(" ")[1])
    Plantform = str(command.split(" ")[2])
    async with (get_session() as db_session):
        try:
            Plantform_in_list = await PlantformManger.get_Sign_by_student_id(
                db_session, Plantform)
            if not Plantform_in_list:
                await rss_sub.send(f"平台 {Plantform} 不存在")
                return
            # 检查数据库中是否已存在该 Student_id 的记录
            existing_lanmsg = await UserManger.get_Sign_by_student_id(
                db_session, user_id)
            if existing_lanmsg:  # 更新记录
                logger.info(f"用户{user_name}已在可访问列表")
                await rss_sub.send(f"用户{user_name}已在可访问列表")
            else:
                try:
                    # 写入数据库
                    await UserManger.create_signmsg(
                        db_session,
                        User_ID=user_id,
                        User_Name=user_name,
                        Plantform=Plantform
                    )
                    await rss_sub.send(
                        f"✅ 增加用户成功\n"
                        f"用户名: {user_name}\n"
                        f"用户ID: {user_id}\n"
                        f"平台：{Plantform}"
                    )
                except Exception as e:
                    logger.opt(exception=False).error(f"创建用户{user_name}至在可访问列表时发生错误: {e}")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")

@user_unsub.handle()
async def handle_rss(args: Message = CommandArg()):
    """
    删除可访问用户列表中用户
    """
    command = args.extract_plain_text().strip()
    user_id = str(command.split(" ")[0])
    user_name = str(command.split(" ")[1])
    async with (get_session() as db_session):
        try:
            # 检查数据库中是否已存在该 Student_id 的记录
            existing_lanmsg = await UserManger.get_Sign_by_student_id(
                db_session, user_id)
            if not existing_lanmsg:  # 更新记录
                logger.info(f"用户{user_name}不在可访问列表")
                await rss_sub.send(f"用户{user_name}不在可访问列表")
            else:
                try:
                    # 写入数据库
                    await UserManger.delete_id(db_session,id=user_id)
                    await rss_unsub.send(
                        f"✅ 用户删除成功\n"
                        f"用户名: {user_name}\n"
                        f"用户ID: {user_id}\n"
                    )
                except Exception as e:
                    logger.opt(exception=False).error(f"将用户{user_name}移出可访问列表时发生错误: {e}")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")

@user_list.handle()
async def handle_rss(args: Message = CommandArg()):
    """
    查询当前可访问用户列表
    """
    async with (get_session() as db_session):
        msg = "📋 当前可访问用户列表：\n"
        try:
            flag = await UserManger.is_database_empty(db_session)
            if flag:
                await rss_list.send("当前无可访问用户")
            else:
                all = await UserManger.get_all_student_id(db_session)
                for id in all:
                    data1 = await UserManger.get_Sign_by_student_id(db_session, id)
                    username = data1.User_ID
                    user_id = data1.User_Name
                    msg += f"用户名: {username}\n"
                    msg += f" 用户ID: {user_id}\n"
                await rss_unsub.send(msg,end="")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")


find = on_command("查询", priority=10, permission=SUPERUSER |GROUP_OWNER |GROUP_ADMIN, rule=ignore_group)
@find.handle()
async def handle_rss(args: Message = CommandArg()):
    """
    订阅情况查询
    """
    async with (get_session() as db_session):
        command = args.extract_plain_text().strip()
        if command.startswith("群组"):
            group_id = str(command.split(" ")[1])
            msg = f"📋 群 {group_id} 当前订阅列表：\n"
            try:
                flag = await UserManger.is_database_empty(db_session)
                if flag:
                    await rss_list.send("当前无订阅")
                else:
                    all = await SubscribeManger.get_all_student_id(db_session)
                    for id in all:
                        data1 = await SubscribeManger.get_Sign_by_student_id(db_session, id)
                        username = data1.username
                        if group_id == data1.group:
                            msg += f"{username}\n"
                    await find.send(msg,end="")
            except SQLAlchemyError as e:
                logger.opt(exception=False).error(f"数据库操作错误: {e}")
        elif command.startswith("用户"):
            user_id = str(command.split(" ")[1])
            msg = f"📋 用户 {user_id} 推送群组列表：\n"
            try:
                flag = await SubscribeManger.is_database_empty(db_session)
                if flag:
                    await rss_list.send("当前无订阅")
                else:
                    all = await SubscribeManger.get_all_student_id(db_session)
                    for id in all:
                        data1 = await SubscribeManger.get_Sign_by_student_id(db_session, id)
                        group_id = data1.group
                        if user_id == data1.username:
                            msg += f"{group_id}\n"
                    await find.send(msg,end="")
            except SQLAlchemyError as e:
                logger.opt(exception=False).error(f"数据库操作错误: {e}")
        else:
            await find.finish("请输入正确的命令")


list = on_command("list", aliases={"文章列表"}, priority=10,rule=ignore_group)
@list.handle()
async def handle_rss(event: GroupMessageEvent,args: Message = CommandArg()):
    """
    查询用户文章列表
    """
    logger.info(f"从群 {event.group_id} 发起List请求")

    userid = args.extract_plain_text().strip()
    sheet1 = await User_get()
    if not userid:
        await rss_cmd.finish("请输入Twitter用户名，例如：文章列表 aibaaiai")
    elif userid not in sheet1:
        await rss_cmd.finish("请求被否决")
    else:
        async with (get_session() as db_session):
            plantform = await UserManger.get_Sign_by_student_id(db_session, userid)
            plantform = plantform.Plantform
            plantform_name = await PlantformManger.get_Sign_by_student_id(db_session, plantform)
            url = plantform_name.url
            if_need_trans = int(plantform_name.need_trans)
            feed_url = f"{RSSHUB_HOST}{url}{userid}"
            user = await User_name_get(userid)
            username = user.User_Name

            # 获取数据
            data = await fetch_feed(feed_url)
            if "error" in data:
                await rss_cmd.finish(data["error"])

            if not data.get("entries"):
                await rss_cmd.finish("该用户暂无动态或不存在")

            # 处理最新一条推文
            msg = (f"用户 {username} 的推文列表：\n")
            num = len(data.get("entries"))
            for i in range(0,num):
                latest = data.get("entries")[i]
                content = extract_content(latest, if_need_trans)
                if not content['trans_title'] == None:
                    msg += (f"\n序号  {i}\n"
                            f"  标题  {content['title']}\n"
                            f"  标题翻译  {content['trans_title']}\n")
                else:
                    msg += (f"\n序号  {i}\n"
                            f"  标题  {content['title']}\n")
            await list.send(msg, end="")

help = on_command("/help", aliases={"/帮助"}, priority=10,rule=ignore_group & to_me())
@help.handle()
async def handle_rss(event: GroupMessageEvent):
    """
    bot帮助
    """
    bot = get_bot()
    group_id = event.group_id
    msg = "📋 nsy推文转发bot命令帮助：\n"
    msg += "注：{}内的内容为发起请求时填写内容 \n"
    msg += "推文查看: rss {用户名} {文章序列号(不填默认为0，即最新文章)}\n"
    msg += "订阅列表：订阅列表\n"
    msg += "开始订阅：订阅 {用户名} {推送群组}\n"
    msg += "查询用户推文列表：文章列表 {用户名}\n"
    msg += "取消订阅：取消订阅 {用户名} {推送群组}\n"
    msg += "增加用户：增加用户 {用户ID} {用户名} {平台名}\n"
    msg += "删除用户：删除用户 {用户ID} {用户名}\n"
    msg += "用户列表：用户列表\n"
    msg += "查询群组订阅：查询 群组 {群组ID} \n"
    msg += "查询用户被订阅：查询 用户 {用户ID} \n"
    msg += "本项目已开源，欢迎star\n"
    msg += "项目地址：https://github.com/AhsokaTano26/nsybot"

    try:
        with open('help.png', 'rb') as image_file:
            img = image_file.read()
            image_seg = MessageSegment.image(img)
            await bot.call_api("send_group_msg", **{
                        "group_id": group_id,
                        "message": image_seg
                    })
    except:
        await help.send(msg,end="")

send_msg = on_command("/send", aliases={"/发送"}, priority=10, permission=SUPERUSER,rule=ignore_group)
@send_msg.handle()
async def handle_rss(args: Message = CommandArg()):
    """
    向所有订阅群组发送通知
    """
    command = args.extract_plain_text().strip()
    msg = str(command.split("@")[0])
    group_list = []
    async with (get_session() as db_session):
        try:
            all = await SubscribeManger.get_all_student_id(db_session)
            bot = get_bot()
            for data in all:
                id = await SubscribeManger.get_Sign_by_student_id(db_session, data)
                if id.group not in group_list:
                    group_list.append(id.group)
            for group_id in group_list:
                group = int(group_id)
                await bot.send_group_msg(group_id=group,message=msg)
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")
        except Exception as e:
            logger.opt(exception=False).error(f"发送时发生错误: {e}")

signal = on_command("/信号", priority=10, permission=SUPERUSER,rule=ignore_group)
@signal.handle()
async def signal_():
    await signal.finish(str(config.if_first_time_start))

signal_on = on_command("/信号否", priority=10, permission=SUPERUSER,rule=ignore_group)
@signal.handle()
async def signal_on_():
    config.if_first_time_start = False
    await signal_on.finish(str(config.if_first_time_start))




#定时任务，发送最新推文
@scheduler.scheduled_job(CronTrigger(minute=f"*/{REFRESH_TIME}"),misfire_grace_time=60)
async def auto_update_func():
    """
    定时向订阅群组发送推文
    """
    logger.info(f"{datetime.now()} 开始处理订阅")
    async with (get_session() as db_session):
        try:
            flag = await SubscribeManger.is_database_empty(db_session)
            sub_list = {}
            if flag:
                logger.info("当前无订阅")
            else:
                all = await SubscribeManger.get_all_student_id(db_session)
                for id in all:
                    try:
                        data1 = await SubscribeManger.get_Sign_by_student_id(db_session, id)
                        username = data1.username
                        sub_list[username] = []
                    except Exception as e:
                        logger.opt(exception=False).error(f"对于{username}的订阅时发生错误: {e}")
                logger.success(f"{datetime.now()} 已获取所有用户名")
                for id in all:
                    try:
                        data1 = await SubscribeManger.get_Sign_by_student_id(db_session, id)
                        username = data1.username
                        group = int(data1.group)
                        sub_list.get(username).append(group)
                    except Exception as e:
                        logger.opt(exception=False).error(f"群{group}对于{username}的订阅时发生错误: {e}")
                logger.success(f"{datetime.now()} 已获取所有群号")
                for user in sub_list:
                    try:
                        logger.info(f"{datetime.now()} 开始处理对 {user} 的订阅")
                        await R.handle_rss(userid=user,group_id_list=sub_list.get(user))
                        time.sleep(1)
                    except Exception as e:
                        logger.opt(exception=False).error(f"对于{user}的订阅时发生错误: {e}")

                config.if_first_time_start = False
                logger.info(f"config.if_first_time_start：{config.if_first_time_start}")

                logger.info(f"{datetime.now()} 订阅处理完毕")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")