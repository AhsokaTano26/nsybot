import asyncio
from datetime import datetime, timedelta

import feedparser
import httpx
from apscheduler.triggers.cron import CronTrigger
from bs4 import BeautifulSoup
from nonebot import get_bot, get_plugin_config, on_command, require
from nonebot.adapters.onebot.v11 import (GROUP_ADMIN, GROUP_OWNER,
                                         GroupMessageEvent, Message,
                                         MessageSegment)
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.rule import to_me
from nonebot_plugin_orm import get_session
from sqlalchemy.exc import SQLAlchemyError

from nsy.plugins.rssget.models import User

from .config import Config
from .encrypt import encrypt
from .following_import import fetch_and_match
from .functions import rss_get
from .get_id import get_id
from .models import Detail
from .models_method import (ContentManager, DetailManager, GroupconfigManager,
                            PlantformManager, SubscribeManager, UserManager)
from .translation import Ali, BaiDu, DeepSeek, Ollama
from .update_text import get_text, update_text

__plugin_meta__ = PluginMetadata(
    name="Twitter RSS订阅",
    description="通过RSSHub获取Twitter用户最新动态并发送图片",
    usage="rss [用户名]  # 获取指定用户最新推文",
    type="QQbot",
    homepage="https://github.com/AhsokaTano26/nsybot",
)

B = DeepSeek()  # 初始化DeepSeek翻译类
# B = Ali()     # 初始化阿里翻译类
# B = BaiDu()  # 初始化百度翻译类
# B = Ollama() # 初始化Ollama翻译类

R = rss_get()  # 初始化rss类
config = get_plugin_config(Config)
logger.add("data/log/info_log.txt", level="INFO",rotation="5 MB", retention="10 days")
logger.add("data/log/error_log.txt", level="ERROR",rotation="5 MB")

TIMEOUT = 30  # 请求超时时间
MAX_CHAR_PER_NODE = 2000

scheduler = require("nonebot_plugin_apscheduler").scheduler

async def ignore_group(event: GroupMessageEvent) -> bool:
    """检查是否在忽略的群中"""
    a = int(event.group_id)
    if a in config.ignored_groups:
        return False
    return True


def _split_args(command: str) -> list[str]:
    return command.split()


def _parse_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def _get_joined_group_ids() -> set[str]:
    bot = get_bot()
    response = await bot.call_api("get_group_list")
    groups = response.get("data", response) if isinstance(response, dict) else response

    joined_group_ids: set[str] = set()
    for group in groups or []:
        if isinstance(group, dict):
            group_id = group.get("group_id")
        else:
            group_id = getattr(group, "group_id", None)
        if group_id is not None:
            joined_group_ids.add(str(group_id))

    return joined_group_ids

async def User_get() -> set:
    async with (get_session() as db_session):
        sheet1 = await UserManager.get_all_student_id(db_session)
        return sheet1

async def User_name_get(id) -> User | None:
    async with (get_session() as db_session):
        sheet1 = await UserManager.get_Sign_by_student_id(db_session,id)
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

def is_current_time_in_period(start_time_str, end_time_str):
    """
    判断当前时间是否在指定的时间段内

    Args:
        start_time_str (str): 开始时间，格式为"HH:MM"或"HH:MM:SS"
        end_time_str (str): 结束时间，格式为"HH:MM"或"HH:MM:SS"

    Returns:
        bool: 当前时间是否在时间段内
    """
    # 获取当前时间
    now = datetime.now().time()

    # 将字符串时间转换为time对象
    start_time = datetime.strptime(start_time_str, "%H:%M").time()
    end_time = datetime.strptime(end_time_str, "%H:%M").time()

    # 处理跨天情况（结束时间小于开始时间表示跨天）
    if end_time < start_time:
        # 当前时间在开始时间之后或结束时间之前
        return now >= start_time or now <= end_time
    else:
        # 当前时间在开始时间和结束时间之间
        return start_time <= now <= end_time

async def extract_content(entry,if_need_trans) -> dict:
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
        trans_text1 = await B.main(BeautifulSoup(entry.description, "html.parser").get_text("\n"))  #为翻译段落划分
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
        "images": images
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
    parts = _split_args(command)
    if not parts:
        await rss_cmd.finish("请输入Twitter用户名，例如：/rss aibaaiai")

    userid = parts[0]
    if len(parts) > 1:
        num = _parse_int(parts[1])
        if num is None:
            await rss_cmd.finish("文章序号必须是数字")
    else:
        num = 0
    sheet1 = await User_get()
    if not userid:
        await rss_cmd.finish("请输入Twitter用户名，例如：/rss aibaaiai")
    elif userid not in sheet1:
        await rss_cmd.finish("请求被否决")
    else:
        async with (get_session() as db_session):
            plantform = await UserManager.get_Sign_by_student_id(db_session, userid)
            plantform = plantform.Plantform
            plantform_name = await PlantformManager.get_Sign_by_student_id(db_session, plantform)
            url = plantform_name.url
            if_need_trans = int(plantform_name.need_trans)
            feed_url = f"{config.rsshub_host}{url}{userid}"
            user = await User_name_get(userid)
            username = user.User_Name

            # 获取数据
            data = await fetch_feed(feed_url)
            if "error" in data:
                await rss_cmd.finish(data["error"])

            if not data.get("entries"):
                await rss_cmd.finish("该用户暂无动态或不存在")

            if num < 0 or num >= len(data.entries):
                await rss_cmd.finish(f"文章序号超出范围，当前可用范围: 0-{len(data.entries) - 1}")

            # 处理最新一条推文
            latest = data.entries[num]
            trueid = await get_id(latest)
            try:

                async with (get_session() as db_session):
                    existing_lanmsg = await ContentManager.get_Sign_by_student_id(
                        db_session, trueid)

                    if existing_lanmsg:  # 如有记录
                        logger.info(f"该 {trueid} 推文已存在")
                        content = await get_text(trueid)    #从本地数据库获取信息
                        msg = [
                            f"🐦 用户 {username} 最新动态",
                            f"⏰ {content['time']}",
                            f"🔗 {content['link']}",
                            "\n📝 正文：",
                            content['text']
                        ]

                        if if_need_trans == 1:
                            trans_msg = [
                                "📝 翻译：",
                                content["trans_text"],
                                f"【翻译由{config.model_name}提供】"
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
                        logger.info(f"该 {trueid} 推文不存在")
                        content = await extract_content(latest,if_need_trans)
                        content["username"] = username
                        content["id"] = trueid
                        await update_text(content)
                        # 构建文字消息
                        logger.info(f"成功获取对于 {username} 的 {trueid} 推文")
                        msg = [
                            f"🐦 用户 {username} 最新动态",
                            f"⏰ {content['time']}",
                            f"🔗 {content['link']}",
                            "\n📝 正文：",
                            content['text']
                        ]

                        if if_need_trans == 1:
                            trans_msg = [
                                "📝 翻译：",
                                content["trans_text"],
                                f"【翻译由{config.model_name}提供】"
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


rss_sub = on_command("rss_sub", aliases={"订阅"}, priority=10, permission=SUPERUSER | GROUP_OWNER | GROUP_ADMIN,rule=ignore_group)
rss_unsub = on_command("rss_unsub", aliases={"取消订阅"}, priority=10, permission=SUPERUSER | GROUP_OWNER | GROUP_ADMIN,rule=ignore_group)
rss_list = on_command("rss_list", aliases={"订阅列表"}, priority=10,permission=SUPERUSER, rule=ignore_group)

@rss_sub.handle()
async def handle_rss(event: GroupMessageEvent,args: Message = CommandArg()):
    command = args.extract_plain_text().strip()
    parts = _split_args(command)
    if not parts:
        await rss_sub.finish("请输入用户名和群号，例如：订阅 aibaaiai 123456")
    username = parts[0]
    group_id = str(event.group_id)

    sheet1 = await User_get()
    if username not in sheet1:
        await rss_sub.finish(f"用户名 {username} 不在可访问列表中")
    true_id = username + "-" + group_id
    async with (get_session() as db_session):
        try:
            # 检查数据库中是否已存在该 Student_id 的记录
            existing_lanmsg = await SubscribeManager.get_Sign_by_student_id(
                db_session, true_id)
            if existing_lanmsg:  # 更新记录
                logger.info(f"群{group_id}对于{username}的订阅已存在")
                await rss_sub.send(f"群{group_id}对于{username}的订阅已存在")
            else:
                try:
                    # 写入数据库
                    await SubscribeManager.create_signmsg(
                        db_session,
                        id=true_id,
                        username=username,
                        group=group_id,
                    )
                    await rss_sub.send(
                        f"✅ 订阅成功\n"
                        f"用户ID: {username}\n"
                        f"推送群组: {group_id}\n"
                    )
                except Exception as e:
                    logger.opt(exception=False).error(f"创建群{group_id}对于{username}的订阅时发生错误: {e}")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")

@rss_unsub.handle()
async def handle_rss(event: GroupMessageEvent, args: Message = CommandArg()):
    command = args.extract_plain_text().strip()
    parts = _split_args(command)
    if not parts:
        await rss_unsub.finish("请输入用户名和群号，例如：取消订阅 aibaaiai 123456")
    username = parts[0]
    group_id = str(event.group_id)
    true_id = username + "-" + group_id
    async with (get_session() as db_session):
        try:
            # 检查数据库中是否已存在该 Student_id 的记录
            existing_lanmsg = await SubscribeManager.get_Sign_by_student_id(
                db_session, true_id)
            if not existing_lanmsg:  # 更新记录
                logger.info(f"群{group_id}对于{username}的订阅不存在")
                await rss_sub.send(f"群{group_id}对于{username}的订阅不存在")
            else:
                try:
                    # 写入数据库
                    await SubscribeManager.delete_id(db_session,id=true_id)
                    await rss_unsub.send(
                        f"✅ 订阅取消成功\n"
                        f"用户ID: {username}\n"
                        f"推送群组: {group_id}\n"
                    )
                except Exception as e:
                    logger.opt(exception=False).error(f"取消群{group_id}对于{username}的订阅时发生错误: {e}")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")


@rss_list.handle()
async def handle_rss(event: GroupMessageEvent):
    async with (get_session() as db_session):
        # 获取当前 bot 实例
        from nonebot import get_bot
        bot = get_bot()
        group_id = event.group_id
        self_id = int(bot.self_id)  # 用于合并转发节点显示

        sub_list = {}
        try:
            flag = await SubscribeManager.is_database_empty(db_session)
            if flag:
                await rss_list.send("当前无订阅")
                return

            # 一次查询获取所有订阅记录
            all_subscriptions = await SubscribeManager.get_all_subscriptions(db_session)

            # 在内存中构建 sub_list
            for sub in all_subscriptions:
                username = sub.username
                group = int(sub.group)
                if username not in sub_list:
                    sub_list[username] = []
                sub_list[username].append(group)

            logger.success("已获取所有订阅信息")

            # 批量获取所有用户信息
            user_ids = list(sub_list.keys())
            users_dict = await UserManager.get_users_by_ids(db_session, user_ids)

            # --- 关键修复：初始化变量 ---
            forward_nodes = []
            msg_buffer = "📋 当前订阅列表：\n"
            MAX_CHAR_PER_NODE = 5000  # 建议设置一个合理的阈值防止超限

            for user in sub_list:
                user_detail = users_dict.get(user)
                user_name = user_detail.User_Name if user_detail else "未知"

                # 构建单个用户的条目
                entry = f"\n用户ID: {user}\n用户名: {user_name}\n"
                for group in sub_list[user]:
                    entry += f"    推送群组: {group}\n"

                # 检查缓冲区长度，决定是否分节
                if len(msg_buffer) + len(entry) > MAX_CHAR_PER_NODE:
                    forward_nodes.append(
                        MessageSegment.node_custom(
                            user_id=self_id,
                            nickname="Ksm 初号机",
                            content=msg_buffer
                        )
                    )
                    msg_buffer = "📋 订阅列表 (续)：\n" + entry  # 重置并开始新节
                else:
                    msg_buffer += entry

            # 处理最后剩余的内容
            if msg_buffer:
                forward_nodes.append(
                    MessageSegment.node_custom(
                        user_id=self_id,
                        nickname="Ksm 初号机",
                        content=msg_buffer
                    )
                )

            # 将节点列表转换为 Message 对象
            forward_message = Message(forward_nodes)

            try:
                # 发送合并转发消息
                await bot.send_forward_msg(group_id=group_id, message=forward_message)
                logger.info(f"发送群 {group_id} 合并转发消息成功")
            except Exception as e:
                logger.error(f"发送群 {group_id} 合并转发消息失败: {e}")
                # 备选方案：如果转发失败，尝试直接发送文字（可选）
                # await rss_list.send("转发失败，可能是消息过长或频率受限")

        except SQLAlchemyError as e:
            logger.opt(exception=True).error(f"数据库操作错误: {e}")
            await rss_list.send("查询订阅列表时出现数据库错误")



user_sub = on_command("user_sub", aliases={"增加用户"}, priority=10, permission=SUPERUSER,rule=ignore_group)
user_unsub = on_command("user_unsub", aliases={"删除用户"}, priority=10, permission=SUPERUSER,rule=ignore_group)
user_list = on_command("user_list", aliases={"用户列表"}, priority=10,rule=ignore_group)
@user_sub.handle()
async def handle_rss(args: Message = CommandArg()):
    """
    增加可访问用户列表中用户
    """
    command = args.extract_plain_text().strip()
    parts = _split_args(command)
    if len(parts) < 3:
        await user_sub.finish("用法: 增加用户 <用户ID> <用户名> <平台名>")
    user_id = parts[0]
    user_name = parts[1]
    Plantform = parts[2]
    async with (get_session() as db_session):
        try:
            Plantform_in_list = await PlantformManager.get_Sign_by_student_id(
                db_session, Plantform)
            if not Plantform_in_list:
                await rss_sub.send(f"平台 {Plantform} 不存在")
                return
            # 检查数据库中是否已存在该 Student_id 的记录
            existing_lanmsg = await UserManager.get_Sign_by_student_id(
                db_session, user_id)
            if existing_lanmsg:  # 更新记录
                logger.info(f"用户{user_name}已在可访问列表")
                await rss_sub.send(f"用户{user_name}已在可访问列表")
            else:
                try:
                    # 写入数据库
                    await UserManager.create_signmsg(
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
    parts = _split_args(command)
    if len(parts) < 2:
        await user_unsub.finish("用法: 删除用户 <用户ID> <用户名>")
    user_id = parts[0]
    user_name = parts[1]
    async with (get_session() as db_session):
        try:
            # 检查数据库中是否已存在该 Student_id 的记录
            existing_lanmsg = await UserManager.get_Sign_by_student_id(
                db_session, user_id)
            if not existing_lanmsg:  # 更新记录
                logger.info(f"用户{user_name}不在可访问列表")
                await rss_sub.send(f"用户{user_name}不在可访问列表")
            else:
                try:
                    # 写入数据库
                    await UserManager.delete_id(db_session,id=user_id)
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
async def handle_rss(event: GroupMessageEvent):
    """
    查询当前可访问用户列表
    """
    async with (get_session() as db_session):
        bot = get_bot()
        group_id = event.group_id
        msg = ("📋 当前可访问用户列表：\n"
               "用户名(用户ID)\n")
        try:
            flag = await UserManager.is_database_empty(db_session)
            if flag:
                await rss_list.send("当前无可访问用户")
            else:
                all_users = await UserManager.get_all_users(db_session)
                msg_parts = ["📋 当前可访问用户列表：\n"]
                for user in all_users:
                    msg_parts.append(f"{user.User_Name}({user.User_ID})\n")

                node1_content = "".join(msg_parts)
                node1 = MessageSegment.node_custom(
                    user_id=config.self_id,
                    nickname="Ksm 初号机",
                    content=node1_content,
                )

                node2_content = "如需增加新用户，请联系管理员，或发邮件至：public@tano.asia"
                node2 = MessageSegment.node_custom(
                    user_id=config.self_id,
                    nickname="Ksm 初号机",
                    content=node2_content,
                )

                forward_nodes = [node1, node2]

                # 将节点列表转换为一个包含所有转发节点的 Message 对象
                forward_message = Message(forward_nodes)

                try:
                    # 发送合并打包消息
                    await bot.send_group_msg(group_id=group_id, message=forward_message)
                    logger.info(f"发送群 {group_id} 合并转发消息成功")
                except Exception as e:
                    logger.error(f"发送群 {group_id} 合并转发消息失败: {e}")

        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")


find = on_command("查询", priority=10, permission=SUPERUSER, rule=ignore_group)
@find.handle()
async def handle_rss(args: Message = CommandArg()):
    """
    订阅情况查询
    """
    async with (get_session() as db_session):
        command = args.extract_plain_text().strip()
        parts = _split_args(command)
        if command.startswith("群组"):
            if len(parts) < 2:
                await find.finish("用法: 查询 群组 <群号>")
            group_id = parts[1]
            try:
                # 直接按群组ID查询订阅
                subscriptions = await SubscribeManager.get_subscriptions_by_group(db_session, group_id)
                if not subscriptions:
                    await find.send(f"群 {group_id} 当前无订阅")
                else:
                    msg_parts = [f"📋 群 {group_id} 当前订阅列表：\n"]
                    for sub in subscriptions:
                        msg_parts.append(f"{sub.username}\n")
                    await find.send("".join(msg_parts))
            except SQLAlchemyError as e:
                logger.opt(exception=False).error(f"数据库操作错误: {e}")
        elif command.startswith("用户"):
            if len(parts) < 2:
                await find.finish("用法: 查询 用户 <用户ID>")
            user_id = parts[1]
            try:
                # 直接按用户名查询订阅
                subscriptions = await SubscribeManager.get_subscriptions_by_username(db_session, user_id)
                if not subscriptions:
                    await find.send(f"用户 {user_id} 当前无订阅")
                else:
                    msg_parts = [f"📋 用户 {user_id} 推送群组列表：\n"]
                    for sub in subscriptions:
                        msg_parts.append(f"{sub.group}\n")
                    await find.send("".join(msg_parts))
            except SQLAlchemyError as e:
                logger.opt(exception=False).error(f"数据库操作错误: {e}")
        else:
            await find.finish("请输入正确的命令")


# ==================== 导入关注功能 ====================
import_following = on_command(
    "import_following",
    aliases={"导入关注"},
    priority=10,
    permission=SUPERUSER | GROUP_OWNER | GROUP_ADMIN,
    rule=ignore_group
)

# 存储待确认的批量订阅 {group_id: [matched_users]}
pending_batch_subscribe: dict[int, list[str]] = {}


@import_following.handle()
async def handle_import_following(event: GroupMessageEvent, args: Message = CommandArg()):
    """
    导入X关注列表并匹配可订阅用户

    用法: 导入关注 <auth_token> <ct0> <x用户名>

    获取凭据方法:
    1. 登录 X (twitter.com)
    2. 打开浏览器开发者工具 (F12)
    3. 在 Application > Cookies 中找到 auth_token 和 ct0
    """
    command = args.extract_plain_text().strip()
    parts = command.split()

    if len(parts) < 3:
        await import_following.finish(
            "📖 用法: 导入关注 <auth_token> <ct0> <x用户名>\n\n"
            "获取凭据方法:\n"
            "1. 登录 X (twitter.com)\n"
            "2. 打开浏览器开发者工具 (F12)\n"
            "3. 切换到 Application 标签\n"
            "4. 在 Cookies > twitter.com 中找到:\n"
            "   - auth_token\n"
            "   - ct0\n\n"
            "⚠️ 注意: 凭据为敏感信息，建议在私聊中使用此命令"
        )

    auth_token = parts[0]
    ct0 = parts[1]
    screen_name = parts[2]
    group_id = event.group_id

    await import_following.send(f"🔄 正在获取 @{screen_name} 的关注列表，请稍候...")

    try:
        # 获取数据库中可订阅的用户列表
        available_users = await User_get()

        if not available_users:
            await import_following.finish("❌ 当前无可订阅用户")

        # 获取关注列表并匹配
        matched_users, fetched_count, total_count = await fetch_and_match(
            auth_token=auth_token,
            ct0=ct0,
            screen_name=screen_name,
            available_users=available_users,
            max_fetch=1000  # 限制最多获取1000个关注
        )

        if not matched_users:
            await import_following.finish(
                f"📊 已扫描 {fetched_count}/{total_count} 个关注\n"
                f"❌ 未找到匹配的可订阅用户"
            )

        # 检查哪些用户已经订阅
        async with get_session() as db_session:
            already_subscribed = []
            not_subscribed = []

            for user_id in matched_users:
                true_id = f"{user_id}-{group_id}"
                existing = await SubscribeManager.get_Sign_by_student_id(db_session, true_id)
                if existing:
                    already_subscribed.append(user_id)
                else:
                    not_subscribed.append(user_id)

        # 构建结果消息
        msg_parts = [
            f"📊 扫描完成 ({fetched_count}/{total_count} 个关注)\n",
            f"✅ 匹配到 {len(matched_users)} 个可订阅用户\n\n"
        ]

        if already_subscribed:
            msg_parts.append(f"📌 已订阅 ({len(already_subscribed)}):\n")
            msg_parts.append("  " + ", ".join(already_subscribed[:10]))
            if len(already_subscribed) > 10:
                msg_parts.append(f" ... 等{len(already_subscribed)}个")
            msg_parts.append("\n\n")

        if not_subscribed:
            msg_parts.append(f"🆕 可新增订阅 ({len(not_subscribed)}):\n")
            for i, user_id in enumerate(not_subscribed, 1):
                msg_parts.append(f"  [{i}] {user_id}\n")

            # 保存待确认列表
            pending_batch_subscribe[group_id] = not_subscribed

            msg_parts.append(f"\n💡 回复 \"确认订阅\" 一键订阅以上 {len(not_subscribed)} 个用户")
            msg_parts.append("\n💡 或回复 \"订阅编号 1 3 5\" 选择性订阅")
        else:
            msg_parts.append("✨ 所有匹配用户均已订阅")

        await import_following.finish("".join(msg_parts))

    except FinishedException:
        raise  # 让 FinishedException 正常传播
    except Exception as e:
        logger.opt(exception=True).error(f"导入关注失败: {e}")
        await import_following.finish(f"❌ 导入失败: {str(e)}")


# 确认批量订阅
confirm_batch_sub = on_command(
    "确认订阅",
    priority=10,
    permission=SUPERUSER | GROUP_OWNER | GROUP_ADMIN,
    rule=ignore_group
)


@confirm_batch_sub.handle()
async def handle_confirm_batch_sub(event: GroupMessageEvent):
    """确认批量订阅待确认列表中的所有用户"""
    group_id = event.group_id

    if group_id not in pending_batch_subscribe or not pending_batch_subscribe[group_id]:
        await confirm_batch_sub.finish("❌ 没有待确认的订阅，请先使用 \"导入关注\" 命令")

    users_to_subscribe = pending_batch_subscribe[group_id]
    success_count = 0
    fail_count = 0

    async with get_session() as db_session:
        for user_id in users_to_subscribe:
            true_id = f"{user_id}-{group_id}"
            try:
                existing = await SubscribeManager.get_Sign_by_student_id(db_session, true_id)
                if not existing:
                    await SubscribeManager.create_signmsg(
                        db_session,
                        id=true_id,
                        username=user_id,
                        group=str(group_id),
                    )
                    success_count += 1
                else:
                    success_count += 1  # 已存在也算成功
            except Exception as e:
                logger.error(f"批量订阅 {user_id} 失败: {e}")
                fail_count += 1

    # 清除待确认列表
    del pending_batch_subscribe[group_id]

    await confirm_batch_sub.finish(
        f"✅ 批量订阅完成\n"
        f"成功: {success_count} 个\n"
        f"失败: {fail_count} 个"
    )


# 按编号订阅
sub_by_index = on_command(
    "订阅编号",
    priority=10,
    permission=SUPERUSER | GROUP_OWNER | GROUP_ADMIN,
    rule=ignore_group
)


@sub_by_index.handle()
async def handle_sub_by_index(event: GroupMessageEvent, args: Message = CommandArg()):
    """按编号订阅待确认列表中的用户"""
    group_id = event.group_id

    if group_id not in pending_batch_subscribe or not pending_batch_subscribe[group_id]:
        await sub_by_index.finish("❌ 没有待确认的订阅，请先使用 \"导入关注\" 命令")

    command = args.extract_plain_text().strip()
    if not command:
        await sub_by_index.finish("📖 用法: 订阅编号 1 3 5 或 订阅编号 1-10")

    users_list = pending_batch_subscribe[group_id]

    # 解析编号
    indices = set()
    for part in command.split():
        if "-" in part:
            # 范围格式: 1-5
            try:
                start, end = map(int, part.split("-"))
                indices.update(range(start, end + 1))
            except ValueError:
                continue
        else:
            # 单个编号
            try:
                indices.add(int(part))
            except ValueError:
                continue

    # 过滤有效编号
    valid_indices = [i for i in indices if 1 <= i <= len(users_list)]
    if not valid_indices:
        await sub_by_index.finish(f"❌ 无效的编号，有效范围: 1-{len(users_list)}")

    # 获取对应用户
    users_to_subscribe = [users_list[i - 1] for i in sorted(valid_indices)]

    success_count = 0
    fail_count = 0
    subscribed_users = []

    async with get_session() as db_session:
        for user_id in users_to_subscribe:
            true_id = f"{user_id}-{group_id}"
            try:
                existing = await SubscribeManager.get_Sign_by_student_id(db_session, true_id)
                if not existing:
                    await SubscribeManager.create_signmsg(
                        db_session,
                        id=true_id,
                        username=user_id,
                        group=str(group_id),
                    )
                success_count += 1
                subscribed_users.append(user_id)
            except Exception as e:
                logger.error(f"订阅 {user_id} 失败: {e}")
                fail_count += 1

    # 从待确认列表中移除已订阅的用户
    pending_batch_subscribe[group_id] = [
        u for u in users_list if u not in subscribed_users
    ]
    if not pending_batch_subscribe[group_id]:
        del pending_batch_subscribe[group_id]

    await sub_by_index.finish(
        f"✅ 订阅完成\n"
        f"成功: {success_count} 个 ({', '.join(subscribed_users)})\n"
        f"失败: {fail_count} 个"
    )


list_article = on_command("list", aliases={"文章列表"}, priority=10,rule=ignore_group)
@list_article.handle()
async def handle_rss(event: GroupMessageEvent,args: Message = CommandArg()):
    """
    查询用户文章列表
    """
    logger.info(f"从群 {event.group_id} 发起List请求")
    bot = get_bot()
    group_id = event.group_id
    userid = args.extract_plain_text().strip()
    sheet1 = await User_get()
    if not userid:
        await list_article.finish("请输入Twitter用户名，例如：文章列表 aibaaiai")
    elif userid not in sheet1:
        await list_article.finish("请求被否决")
    else:
        async with (get_session() as db_session):
            plantform = await UserManager.get_Sign_by_student_id(db_session, userid)
            plantform = plantform.Plantform
            plantform_name = await PlantformManager.get_Sign_by_student_id(db_session, plantform)
            url = plantform_name.url
            if_need_trans = int(plantform_name.need_trans)
            feed_url = f"{config.rsshub_host}{url}{userid}"
            user = await User_name_get(userid)
            username = user.User_Name

            # 获取数据
            data = await fetch_feed(feed_url)
            if "error" in data:
                await list_article.finish(data["error"])

            if not data.get("entries"):
                await list_article.finish("该用户暂无动态或不存在")

            # 处理最新一条推文
            msg = (f"用户 {username} 的推文列表：\n")
            num = len(data.get("entries"))
            for i in range(0,num):
                latest = data.get("entries")[i]
                content = await extract_content(latest, if_need_trans)
                if content.get('trans_text') is not None:
                    msg += (f"\n序号  {i}\n"
                            f"  标题  {content['title']}\n"
                            f"  正文翻译  {content['trans_text']}\n")
                else:
                    msg += (f"\n序号  {i}\n"
                            f"  标题  {content['title']}\n")

            node1_content = msg
            node1 = MessageSegment.node_custom(
                user_id=config.self_id,
                nickname="Ksm 初号机",
                content=node1_content,
            )

            forward_nodes = [node1]

            # 将节点列表转换为一个包含所有转发节点的 Message 对象
            forward_message = Message(forward_nodes)

            try:
                # 发送合并打包消息
                await bot.send_group_msg(group_id=group_id, message=forward_message)
                logger.info(f"发送群 {group_id} 合并转发消息成功")
            except Exception as e:
                logger.error(f"发送群 {group_id} 合并转发消息失败: {e}")

group_config = on_command("群组配置", priority=10,  permission=SUPERUSER | GROUP_OWNER | GROUP_ADMIN, rule=ignore_group)
@group_config.handle()
async def group_config_(event: GroupMessageEvent, args: Message = CommandArg()):
    command = args.extract_plain_text().strip()
    group_id = event.group_id
    try:
        parts = _split_args(command)
        if not parts:
            parts = ["1", "0", "1", "1", "0"]
        if len(parts) != 5:
            await group_config.finish("用法: 群组配置 [1/0 1/0 1/0 1/0 1/0]")

        values = [_parse_int(item) for item in parts]
        if any(item is None or item not in (0, 1) for item in values):
            await group_config.finish("群组配置参数只能是 0 或 1")

        if_need_trans = True if values[0] == 1 else False
        if_need_self_trans = True if values[1] == 1 else False
        if_need_translate = True if values[2] == 1 else False
        if_need_photo_num_mention = True if values[3] == 1 else False
        if_need_merged_message = True if values[4] == 1 else False

        async with (get_session() as db_session):
            config_msg = await GroupconfigManager.get_Sign_by_group_id(db_session, group_id)
            if not config_msg:
                try:
                    await GroupconfigManager.create_signmsg(
                        db_session,
                        group_id=group_id,
                        if_need_trans=if_need_trans,
                        if_need_self_trans=if_need_self_trans,
                        if_need_translate=if_need_translate,
                        if_need_photo_num_mention=if_need_photo_num_mention,
                        if_need_merged_message=if_need_merged_message
                    )
                    await group_config.finish(f"创建群组 {group_id} 配置成功")
                except SQLAlchemyError as e:
                    logger.opt(exception=False).error(f"数据库操作错误: {e}")
                    await group_config.finish(f"创建群组 {group_id} 配置失败")
            else:
                try:
                    await GroupconfigManager.delete_id(db_session, group_id)
                    await group_config.send(f"删除群组 {group_id} 配置成功")
                    await GroupconfigManager.create_signmsg(
                        db_session,
                        group_id=group_id,
                        if_need_trans=if_need_trans,
                        if_need_self_trans=if_need_self_trans,
                        if_need_translate=if_need_translate,
                        if_need_photo_num_mention=if_need_photo_num_mention,
                        if_need_merged_message=if_need_merged_message
                    )
                    await group_config.finish(f"创建群组 {group_id} 配置成功")
                except SQLAlchemyError as e:
                    logger.opt(exception=False).error(f"数据库操作错误: {e}")
                    await group_config.finish(f"创建群组 {group_id} 配置失败")

    except IndexError:
        await group_config.finish("请输入正确的命令")


help = on_command("/help", aliases={"/帮助","help","帮助"}, priority=10,rule=ignore_group & to_me())
@help.handle()
async def handle_rss(event: GroupMessageEvent):
    """
    bot帮助
    """
    bot = get_bot()
    group_id = event.group_id
    node1_content = Message(config.help_msg_1)
    node1 = MessageSegment.node_custom(
        user_id=config.self_id,
        nickname="Ksm 初号机",
        content=node1_content,
    )

    node2_content = Message(config.help_msg_2)
    node2 = MessageSegment.node_custom(
        user_id=config.self_id,
        nickname="Ksm 初号机",
        content=node2_content,
    )

    forward_message_nodes = [node1, node2]
    try:
        # 使用 bot.call_api 直接调用 OneBot V11 的 send_group_forward_msg API
        result = await bot.call_api(
            "send_group_forward_msg",
            group_id=group_id,
            messages=forward_message_nodes
        )

        logger.info(f"合并转发消息发送成功！API 结果：{result}")
    except Exception as e:
        logger.error(f"发送合并转发消息失败！错误：{type(e).__name__}: {e}")

send_msg = on_command("/send", aliases={"/发送"}, priority=10, permission=SUPERUSER,rule=ignore_group)
@send_msg.handle()
async def handle_rss(args: Message = CommandArg()):
    """
    向所有订阅群组发送通知
    """
    command = args.extract_plain_text().strip()
    msg = str(command.split("*")[0])
    async with (get_session() as db_session):
        try:
            all_subscriptions = await SubscribeManager.get_all_subscriptions(db_session)
            bot = get_bot()

            # 去重
            group_set = {sub.group for sub in all_subscriptions}

            for group_id in group_set:
                group = int(group_id)
                try:
                    await bot.send_group_msg(group_id=group, message=msg)
                    logger.info(f"成功发送消息到群 {group_id}")
                except Exception as e:
                        logger.opt(exception=False).error(f"发送消息到群 {group_id} 失败: {e}")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")
        except Exception as e:
            logger.opt(exception=False).error(f"发送时发生错误: {e}")

signal = on_command("/信号", priority=10, permission=SUPERUSER,rule=ignore_group)
@signal.handle()
async def signal_():
    if_first_time_start = await rss_get().get_signal()
    await signal.finish(if_first_time_start)

signal_on = on_command("/信号否", priority=10, permission=SUPERUSER,rule=ignore_group)
@signal_on.handle()
async def signal_on_():
    await rss_get().change_config()
    if_first_time_start = await rss_get().get_signal()
    await signal_on.finish(if_first_time_start)

async def refresh_article():
    """
    定时刷新推送推文用函数
    """
    async with (get_session() as db_session):
        try:
            flag = await SubscribeManager.is_database_empty(db_session)
            sub_list = {}
            if flag:
                logger.info("当前无订阅")
            else:
                all_subscriptions = await SubscribeManager.get_all_subscriptions(db_session)

                for sub in all_subscriptions:
                    username = sub.username
                    group = int(sub.group)
                    if username not in sub_list:
                        sub_list[username] = []
                    sub_list[username].append(group)
                logger.success(f"{datetime.now()} 已获取所有订阅信息")

                # 预加载所有群组配置
                group_configs = await GroupconfigManager.get_all_configs(db_session)
                logger.info(f"已预加载 {len(group_configs)} 个群组配置")

                semaphore = asyncio.Semaphore(5)  # 控制rsshub请求并发数

                async def process_user(user, groups):
                    async with semaphore:
                        try:
                            logger.info(f"{datetime.now()} 开始处理对 {user} 的订阅")
                            await R.handle_rss(userid=user, group_id_list=groups, group_configs=group_configs)
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            logger.opt(exception=False).error(f"对于{user}的订阅时发生错误: {e}")

                tasks = [process_user(user, sub_list[user]) for user in sub_list]
                await asyncio.gather(*tasks)

            await rss_get().change_config()
            logger.info(f"config.if_first_time_start：{await rss_get().get_signal()}")

            logger.info(f"{datetime.now()} 订阅处理完毕")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")


refresh = on_command("refresh", priority=10, permission=SUPERUSER, rule=ignore_group)
@refresh.handle()
async def refresh_():
    """
    手动刷新推文
    """
    start_time = datetime.now()
    logger.info(f"{start_time} 开始刷新推文")
    await refresh_article()
    end_time = datetime.now()
    full_time = end_time - start_time
    await refresh.finish(f"刷新完成,共用时{full_time}")


cleanup_orphan_subscriptions = on_command(
    "清理失效订阅",
    aliases={"清理群订阅", "清理失效群订阅"},
    priority=10,
    permission=SUPERUSER,
    rule=ignore_group,
)


@cleanup_orphan_subscriptions.handle()
async def cleanup_orphan_subscriptions_():
    """清理 bot 已不在群内但仍存在订阅记录的群组订阅"""
    async with get_session() as db_session:
        try:
            joined_group_ids = await _get_joined_group_ids()
            all_subscriptions = await SubscribeManager.get_all_subscriptions(db_session)
            subscribed_group_ids = {str(sub.group) for sub in all_subscriptions}

            orphan_group_ids = sorted(subscribed_group_ids - joined_group_ids)
            if not orphan_group_ids:
                await cleanup_orphan_subscriptions.finish("当前没有需要清理的失效群订阅")

            deleted_count = 0
            for group_id in orphan_group_ids:
                deleted_count += await SubscribeManager.delete_by_group(db_session, group_id)

            await cleanup_orphan_subscriptions.finish(
                f"✅ 清理完成\n"
                f"已加入群聊数: {len(joined_group_ids)}\n"
                f"清理失效群数: {len(orphan_group_ids)}\n"
                f"删除订阅条数: {deleted_count}"
            )
        except Exception as e:
            logger.opt(exception=True).error(f"清理失效订阅失败: {e}")
            await cleanup_orphan_subscriptions.finish(f"❌ 清理失败: {e}")


@scheduler.scheduled_job('interval',minutes=config.refresh_time,misfire_grace_time=60)
async def auto_update_func():
    """
    定时任务，检查更新并向订阅群组发送推文
    """
    start_time = datetime.now()

    try:
        # 1. 尝试获取 bot
        bot = get_bot()
        if not bot:
            logger.error("未能获取到有效的 bot 实例")
            return

        # 2. 检查时间段
        if is_current_time_in_period("02:00", "08:00"):
            logger.info("当前为休息时间，跳过本次任务")
            return

        # 3. 执行核心刷新任务
        await refresh_article()

    except Exception as e:
        logger.exception(f"定时任务运行异常: {e}")
    finally:
        # 无论成功还是失败，最后记录耗时
        end_time = datetime.now()
        logger.info(f"任务结束，总耗时: {end_time - start_time}")
