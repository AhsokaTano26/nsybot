import asyncio
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from apscheduler.triggers.cron import CronTrigger
from nonebot import get_bot, get_driver, on_command, on_type, require
from nonebot.adapters.qq import (C2CMessageCreateEvent, Event,
                                 GroupAddRobotEvent, GroupDelRobotEvent,
                                 GroupMessageCreateEvent, Message,
                                 MessageSegment)
from nonebot.log import logger
from nonebot.message import event_preprocessor
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot_plugin_orm import get_session
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from nsy.plugins.rssget.models import User

from .encrypt import encrypt
from .following_import import fetch_and_match
from .functions import config, rss_get, fetch_feed, _parse_group_config, _delivery_lock
from .format_json import Format
from .get_id import get_id
from .models import BotGroup, Detail, Groupconfig, Subscribe
from .group_registry import BotGroupManager
from .models_method import (ContentManager, DetailManager, GroupconfigManager,
                            PlantformManager, SubscribeManager, UserManager)
from .platforms import PLATFORM_USAGES, execute_platform_command
from .translation import Ali, BaiDu, DeepSeek, Ollama
from .update_text import get_text, update_text
from nsy import qq_utils
from nsy.qq_utils import (article_messages, command_keyboard, download_image,
                          error, file_image, group_openid, info, is_c2c_event,
                          is_group_event, markdown, quoted_card,
                          send_group_message, success, user_openid, warning)

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
logger.add("data/log/info_log.txt", level="INFO",rotation="5 MB", retention="10 days")
logger.add("data/log/error_log.txt", level="ERROR",rotation="5 MB")

scheduler = require("nonebot_plugin_apscheduler").scheduler

# 当前进程已收到的退群事件，防止延迟到达的旧消息重新登记已离开的群。
_departed_groups: dict[str, datetime] = {}


def _registry_event_time(value) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            value = None
    if not isinstance(value, datetime):
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _registry_display_time(value: datetime | None) -> str:
    if value is None:
        return "未知"
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return value.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


@event_preprocessor
async def track_group_message(event: Event) -> None:
    """所有普通/@群消息都登记，不依赖 RSS 指令、订阅或忽略名单。"""
    if not isinstance(event, GroupMessageCreateEvent):
        return
    group_id = str(event.group_openid)
    seen_at = _registry_event_time(event.timestamp)
    async with _delivery_lock(f"membership:{group_id}"):
        departed_at = _departed_groups.get(group_id)
        if departed_at and seen_at.replace(microsecond=0) <= departed_at.replace(microsecond=0):
            return
        try:
            async with get_session() as session, session.begin():
                await BotGroupManager.observe(session, group_id, seen_at)
            # 消息只能证明重新在群，不能清除用于隔离上一次成员关系的时间界限。
        except SQLAlchemyError as exc:
            logger.opt(exception=False).error(f"登记群 {group_id} 的消息事件失败，不阻断命令：{exc}")


async def ignore_group(event: Event) -> bool:
    """检查是否在忽略的群中"""
    return (
        isinstance(event, GroupMessageCreateEvent)
        and group_openid(event) not in set(config.ignored_group_openids)
    )


async def is_superuser(event: Event) -> bool:
    """Only the configured NoneBot superusers may access global admin shortcuts."""
    try:
        return user_openid(event) in set(get_driver().config.superusers)
    except ValueError:
        return False


group_rule = Rule(is_group_event, ignore_group)
private_rule = Rule(is_c2c_event)
superuser_group_rule = Rule(is_group_event, ignore_group, is_superuser)

PICKER_PAGE_SIZE = 25
PICKER_SESSION_TTL = timedelta(minutes=30)
# (群 OpenID、成员 OpenID、操作) -> (创建时间、当前页可操作的用户 ID)
picker_sessions: dict[tuple[str, str, str], tuple[datetime, list[str]]] = {}


def _split_args(command: str) -> list[str]:
    return command.split()


def _parse_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _picker_session_key(event: GroupMessageCreateEvent, operation: str) -> tuple[str, str, str]:
    return (group_openid(event), user_openid(event), operation)


def _get_picker_candidates(event: GroupMessageCreateEvent, operation: str) -> list[str] | None:
    """取得当前成员在当前群的选择面板，过期面板自动失效。"""
    key = _picker_session_key(event, operation)
    session = picker_sessions.get(key)
    if not session:
        return None
    created_at, candidates = session
    if datetime.now() - created_at > PICKER_SESSION_TTL:
        del picker_sessions[key]
        return None
    return candidates


def _set_picker_candidates(
    event: GroupMessageCreateEvent, operation: str, candidates: list[str]
) -> None:
    key = _picker_session_key(event, operation)
    if candidates:
        picker_sessions[key] = (datetime.now(), candidates)
    else:
        picker_sessions.pop(key, None)


def _parse_picker_indices(command: str, upper_bound: int) -> list[int]:
    """解析 ``1 3 5`` 与 ``1-5`` 形式的编号。"""
    indices: set[int] = set()
    for part in command.split():
        if "-" in part:
            try:
                start, end = map(int, part.split("-", 1))
                if start <= end:
                    indices.update(range(start, end + 1))
            except ValueError:
                continue
        else:
            index = _parse_int(part)
            if index is not None:
                indices.add(index)
    return sorted(index for index in indices if 1 <= index <= upper_bound)


async def _build_subscription_picker(
    event: GroupMessageCreateEvent, operation: str, page: int = 1
) -> Message:
    """构造当前群、当前成员专属的订阅或退订编号选择面板。"""
    group_id = group_openid(event)
    async with get_session() as db_session:
        subscriptions = await SubscribeManager.get_subscriptions_by_group(db_session, group_id)
        subscribed_ids = {str(sub.username) for sub in subscriptions}

        if operation == "subscribe":
            all_users = await UserManager.get_all_users(db_session)
            candidates = [
                (str(user.User_ID), str(user.User_Name))
                for user in all_users
                if str(user.User_ID) not in subscribed_ids
            ]
            title = "📬 订阅选择面板"
            selection_command = "订阅选择"
            direct_command = "订阅 <用户ID> [更多用户ID]"
        else:
            users = await UserManager.get_users_by_ids(db_session, list(subscribed_ids))
            candidates = [
                (user_id, str(users[user_id].User_Name) if user_id in users else "未知用户")
                for user_id in sorted(subscribed_ids)
            ]
            title = "📭 退订选择面板"
            selection_command = "取消订阅选择"
            direct_command = "取消订阅 <用户ID> [更多用户ID]"

    if not candidates:
        empty_text = "本群已订阅全部可用用户。" if operation == "subscribe" else "本群当前没有订阅。"
        return info(empty_text, title)

    total_pages = (len(candidates) + PICKER_PAGE_SIZE - 1) // PICKER_PAGE_SIZE
    page = min(max(page, 1), total_pages)
    start = (page - 1) * PICKER_PAGE_SIZE
    page_candidates = candidates[start:start + PICKER_PAGE_SIZE]
    _set_picker_candidates(event, operation, [user_id for user_id, _ in page_candidates])

    lines = [f"第 {page}/{total_pages} 页 · 共 {len(candidates)} 个用户", ""]
    for index, (user_id, user_name) in enumerate(page_candidates, 1):
        lines.append(f"{index}. {user_name}（`{user_id}`）")
    lines.extend([
        "",
        f"选择多个：`{selection_command} 1 3 5`",
        f"选择范围：`{selection_command} 1-10`",
        f"也可直接发送：`{direct_command}`",
    ])

    keyboard_rows = [[("按编号选择", f"{selection_command} ", False)]]
    navigation = []
    panel_command = "订阅面板" if operation == "subscribe" else "退订面板"
    if page > 1:
        navigation.append(("上一页", f"{panel_command} {page - 1}", True))
    if page < total_pages:
        navigation.append(("下一页", f"{panel_command} {page + 1}", True))
    if navigation:
        keyboard_rows.append(navigation)
    return quoted_card(title, "\n".join(lines)) + command_keyboard(keyboard_rows)


async def _apply_picker_selection(
    event: GroupMessageCreateEvent, operation: str, command: str
) -> tuple[list[str], list[str]] | None:
    """执行选择面板中当前页的编号操作，返回（成功、失败）用户 ID。"""
    candidates = _get_picker_candidates(event, operation)
    if candidates is None:
        return None

    indices = _parse_picker_indices(command, len(candidates))
    if not indices:
        return [], []

    group_id = group_openid(event)
    selected_users = [candidates[index - 1] for index in indices]
    succeeded: list[str] = []
    failed: list[str] = []
    async with get_session() as db_session:
        for user_id in selected_users:
            try:
                subscription_id = f"{user_id}-{group_id}"
                if operation == "subscribe":
                    existing = await SubscribeManager.get_Sign_by_student_id(db_session, subscription_id)
                    if not existing:
                        await SubscribeManager.create_signmsg(
                            db_session,
                            id=subscription_id,
                            username=user_id,
                            group=group_id,
                        )
                else:
                    await SubscribeManager.delete_id(db_session, id=subscription_id)
                succeeded.append(user_id)
            except Exception as exception:
                logger.error(f"选择面板{operation} {user_id} 失败: {exception}")
                failed.append(user_id)

    _set_picker_candidates(
        event, operation, [user_id for user_id in candidates if user_id not in succeeded]
    )
    return succeeded, failed


async def _get_joined_group_ids() -> set[str]:
    """读取独立群登记表，包含历史待确认群，与是否存在 RSS 订阅无关。"""
    async with get_session() as db_session:
        return await BotGroupManager.ids(db_session)

async def User_get() -> set:
    async with (get_session() as db_session):
        sheet1 = await UserManager.get_all_student_id(db_session)
        return sheet1

async def User_name_get(id) -> User | None:
    async with (get_session() as db_session):
        sheet1 = await UserManager.get_Sign_by_student_id(db_session,id)
        return sheet1


def is_current_time_in_period(start_time_str, end_time_str, now=None):
    """
    判断当前时间是否在指定的时间段内

    Args:
        start_time_str (str): 开始时间，格式为"HH:MM"或"HH:MM:SS"
        end_time_str (str): 结束时间，格式为"HH:MM"或"HH:MM:SS"

    Returns:
        bool: 当前时间是否在时间段内
    """
    # 容器可能运行于 UTC，休息时间固定按北京时间判断。
    shanghai = ZoneInfo("Asia/Shanghai")
    now = (now or datetime.now(shanghai)).astimezone(shanghai).time()

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
    """命令查询与定时推送共用字段兼容和翻译降级逻辑。"""
    return await Format().extract_content(entry, if_need_trans, translator=B)


async def _send_rss_reply(group_id: str, message):
    """保留命令的被动回复上下文，同时遵守共用的机器人/群发送间隔。"""
    bot = get_bot()
    async with qq_utils.active_message_limiter.turn(str(getattr(bot, "self_id", id(bot))), group_id):
        return await rss_cmd.send(message)


async def _send_rss_article(group_id: str, content: dict, translation: str | None):
    """手动查询与自动推送共用文章锁，正文分页和原图不会相互插入。"""
    async with _delivery_lock(f"rss-group:{group_id}"):
        for message in article_messages(content, translation, config.model_name if translation else None):
            await _send_rss_reply(group_id, message)
        for url in dict.fromkeys(content.get("images") or []):
            await send_qq_image(url, group_id)


async def send_qq_image(img_url: str, group_id: str):
    """在命令回复中发送 QQ 官方富媒体图片。"""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            data, file_name = await download_image(img_url, client)
        await _send_rss_reply(group_id, file_image(data, file_name))

    except httpx.HTTPError as e:
        logger.opt(exception=False).error(f"图片下载失败: {str(e)}")
        await _send_rss_reply(group_id, error(f"图片下载失败：{e}", "🖼️ 图片发送失败"))
    except httpx.TimeoutException as e:
        logger.opt(exception=False).error(f"连接超时|图片下载失败: {str(e)}")
        await _send_rss_reply(group_id, error(f"连接超时：{e}", "🖼️ 图片发送失败"))
    except Exception as e:
        logger.opt(exception=False).error(f"意外错误|图片发送失败: {str(e)}")
        await _send_rss_reply(group_id, error(f"意外错误：{e}", "🖼️ 图片发送失败"))



rss_cmd = on_command("rss", priority=10, block=True, rule=group_rule)

@rss_cmd.handle()
async def handle_rss_cmd(event: GroupMessageCreateEvent,args: Message = CommandArg()):
    logger.info(f"从官方群 {group_openid(event)} 发起 RSS_Hub 请求")

    command = args.extract_plain_text().strip()
    parts = _split_args(command)
    if not parts:
        await rss_cmd.finish(info("`rss aibaaiai`\n\n可在用户名后加文章序号，例如：`rss aibaaiai 2`。", "📖 RSS 查询用法"))

    userid = parts[0]
    if len(parts) > 1:
        num = _parse_int(parts[1])
        if num is None:
            await rss_cmd.finish(error("文章序号必须是数字。", "📖 RSS 查询用法"))
    else:
        num = 0
    sheet1 = await User_get()
    if not userid:
        await rss_cmd.finish(info("`rss aibaaiai`", "📖 RSS 查询用法"))
    elif userid not in sheet1:
        await rss_cmd.finish(warning("该用户不在可访问列表中。", "🐦 RSS 查询"))
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
                await rss_cmd.finish(error(data["error"], "🐦 RSS 查询"))

            if not data.get("entries"):
                await rss_cmd.finish(info("该用户暂无动态，或用户不存在。", "🐦 RSS 查询"))

            if num < 0 or num >= len(data.entries):
                await rss_cmd.finish(error(
                    f"可用序号为 `0-{len(data.entries) - 1}`。", "🐦 RSS 查询"
                ))

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
                        content["username"] = username
                        translation = None
                        if if_need_trans == 1:
                            translation = content.get("trans_text") or "（暂无翻译）"
                        await _send_rss_article(group_openid(event), content, translation)
                    else:   #从RSSHUB获取信息
                        logger.info(f"该 {trueid} 推文不存在")
                        content = await extract_content(latest,if_need_trans)
                        content["username"] = username
                        content["id"] = trueid
                        await update_text(content)
                        logger.info(f"成功获取对于 {username} 的 {trueid} 推文")
                        translation = None
                        if if_need_trans == 1:
                            translation = content.get("trans_text") or "（暂无翻译）"
                        await _send_rss_article(group_openid(event), content, translation)
            except Exception as e:
                logger.opt(exception=False).error(f"数据库操作错误: {e}")


rss_sub = on_command("rss_sub", aliases={"订阅"}, priority=10, rule=group_rule)
rss_unsub = on_command("rss_unsub", aliases={"取消订阅"}, priority=10, rule=group_rule)
rss_list = on_command("rss_list", aliases={"订阅列表"}, priority=10, rule=superuser_group_rule)
subscription_panel = on_command("订阅面板", aliases={"订阅选择面板"}, priority=10, rule=group_rule)
unsubscribe_panel = on_command("退订面板", aliases={"取消订阅面板"}, priority=10, rule=group_rule)


async def _show_picker(
    event: GroupMessageCreateEvent, args: Message, operation: str
) -> Message:
    page = _parse_int(args.extract_plain_text().strip(), 1)
    return await _build_subscription_picker(event, operation, page or 1)


@subscription_panel.handle()
async def handle_subscription_panel(event: GroupMessageCreateEvent, args: Message = CommandArg()):
    await subscription_panel.finish(await _show_picker(event, args, "subscribe"))


@unsubscribe_panel.handle()
async def handle_unsubscribe_panel(event: GroupMessageCreateEvent, args: Message = CommandArg()):
    await unsubscribe_panel.finish(await _show_picker(event, args, "unsubscribe"))

@rss_sub.handle()
async def handle_rss_sub(event: GroupMessageCreateEvent,args: Message = CommandArg()):
    command = args.extract_plain_text().strip()
    parts = _split_args(command)
    if not parts:
        await rss_sub.finish(await _build_subscription_picker(event, "subscribe"))
    group_id = group_openid(event)

    sheet1 = await User_get()
    success_list = []
    exist_list = []
    invalid_list = []

    async with (get_session() as db_session):
        for username in parts:
            if username not in sheet1:
                invalid_list.append(username)
                continue
            true_id = username + "-" + group_id
            try:
                existing_lanmsg = await SubscribeManager.get_Sign_by_student_id(
                    db_session, true_id)
                if existing_lanmsg:
                    exist_list.append(username)
                else:
                    await SubscribeManager.create_signmsg(
                        db_session,
                        id=true_id,
                        username=username,
                        group=group_id,
                    )
                    success_list.append(username)
            except Exception as e:
                logger.opt(exception=False).error(f"创建群{group_id}对于{username}的订阅时发生错误: {e}")
                invalid_list.append(username)

    msg_parts = []
    if success_list:
        msg_parts.append(f"✅ 订阅成功 ({len(success_list)}): {', '.join(success_list)}")
    if exist_list:
        msg_parts.append(f"📌 已存在 ({len(exist_list)}): {', '.join(exist_list)}")
    if invalid_list:
        msg_parts.append(f"❌ 无效用户 ({len(invalid_list)}): {', '.join(invalid_list)}")
    await rss_sub.finish(quoted_card("📬 订阅结果", "\n\n".join(msg_parts)))

@rss_unsub.handle()
async def handle_rss_unsub(event: GroupMessageCreateEvent, args: Message = CommandArg()):
    command = args.extract_plain_text().strip()
    parts = _split_args(command)
    if not parts:
        await rss_unsub.finish(await _build_subscription_picker(event, "unsubscribe"))
    group_id = group_openid(event)

    success_list = []
    not_exist_list = []

    async with (get_session() as db_session):
        for username in parts:
            true_id = username + "-" + group_id
            try:
                existing_lanmsg = await SubscribeManager.get_Sign_by_student_id(
                    db_session, true_id)
                if not existing_lanmsg:
                    not_exist_list.append(username)
                else:
                    await SubscribeManager.delete_id(db_session, id=true_id)
                    success_list.append(username)
            except Exception as e:
                logger.opt(exception=False).error(f"取消群{group_id}对于{username}的订阅时发生错误: {e}")
                not_exist_list.append(username)

    msg_parts = []
    if success_list:
        msg_parts.append(f"✅ 取消成功 ({len(success_list)}): {', '.join(success_list)}")
    if not_exist_list:
        msg_parts.append(f"📌 未订阅 ({len(not_exist_list)}): {', '.join(not_exist_list)}")
    await rss_unsub.finish(quoted_card("📭 取消订阅结果", "\n\n".join(msg_parts)))


@rss_list.handle()
async def handle_rss_list(event: GroupMessageCreateEvent):
    async with (get_session() as db_session):
        sub_list = {}
        try:
            flag = await SubscribeManager.is_database_empty(db_session)
            if flag:
                await rss_list.send(info("本群暂未创建任何订阅。", "📭 订阅列表"))
                return

            # 一次查询获取所有订阅记录
            all_subscriptions = await SubscribeManager.get_all_subscriptions(db_session)

            # 在内存中构建 sub_list
            for sub in all_subscriptions:
                username = sub.username
                group = str(sub.group)
                if username not in sub_list:
                    sub_list[username] = []
                sub_list[username].append(group)

            logger.success("已获取所有订阅信息")

            # 批量获取所有用户信息
            user_ids = list(sub_list.keys())
            users_dict = await UserManager.get_users_by_ids(db_session, user_ids)

            entries = []
            for user in sub_list:
                user_detail = users_dict.get(user)
                user_name = user_detail.User_Name if user_detail else "未知"
                groups = "、".join(str(group) for group in sub_list[user])
                entries.append(
                    f"- 用户名：{user_name}\n"
                    f"  用户 ID：`{user}`\n"
                    f"  推送群组：{groups}"
                )

            await rss_list.send(quoted_card("📋 当前订阅列表", "\n\n".join(entries)))

        except SQLAlchemyError as e:
            logger.opt(exception=True).error(f"数据库操作错误: {e}")
            await rss_list.send(error("查询订阅列表时出现数据库错误，请稍后重试。", "📭 订阅列表"))



def _register_platform_command(command: str):
    matcher = on_command(command, priority=10, rule=superuser_group_rule)

    @matcher.handle()
    async def handle_platform(args: Message = CommandArg()):
        try:
            async with get_session() as session:
                result = await execute_platform_command(session, command, args.extract_plain_text())
        except ValueError as exc:
            await matcher.finish(error(str(exc), f"🗂️ {command}"))
        except SQLAlchemyError:
            logger.exception("平台管理数据库操作失败")
            await matcher.finish(error("平台数据操作失败，请查看日志后重试。", f"🗂️ {command}"))
        await matcher.finish(info(result, f"🗂️ {command}"))

    return matcher


platform_add = _register_platform_command("增加平台")
platform_update = _register_platform_command("修改平台")
platform_delete = _register_platform_command("删除平台")
platform_list = _register_platform_command("平台列表")


user_sub = on_command("user_sub", aliases={"增加用户"}, priority=10, rule=superuser_group_rule)
user_unsub = on_command("user_unsub", aliases={"删除用户"}, priority=10, rule=superuser_group_rule)
user_list = on_command("user_list", aliases={"用户列表"}, priority=10, rule=group_rule)
@user_sub.handle()
async def handle_user_sub(args: Message = CommandArg()):
    """
    增加可访问用户列表中用户
    """
    command = args.extract_plain_text().strip()
    parts = _split_args(command)
    if len(parts) < 3:
        await user_sub.finish(info("`增加用户 <用户ID> <用户名> <平台名>`", "📖 增加用户用法"))
    user_id = parts[0]
    user_name = parts[1]
    Plantform = parts[2]
    async with (get_session() as db_session):
        try:
            Plantform_in_list = await PlantformManager.get_Sign_by_student_id(
                db_session, Plantform)
            if not Plantform_in_list:
                await user_sub.send(error(
                    f"平台 `{Plantform}` 不存在。请先用 `平台列表` 查看，或用 `增加平台` 创建平台。",
                    "👤 增加用户",
                ))
                return
            # 检查数据库中是否已存在该 Student_id 的记录
            existing_lanmsg = await UserManager.get_Sign_by_student_id(
                db_session, user_id)
            if existing_lanmsg:  # 更新记录
                logger.info(f"用户{user_name}已在可访问列表")
                await user_sub.send(info(f"用户 **{user_name}** 已在可访问列表中。", "👤 增加用户"))
            else:
                try:
                    # 写入数据库
                    await UserManager.create_signmsg(
                        db_session,
                        User_ID=user_id,
                        User_Name=user_name,
                        Plantform=Plantform
                    )
                    await user_sub.send(success(
                        f"- 用户名：**{user_name}**\n"
                        f"- 用户 ID：`{user_id}`\n"
                        f"- 平台：{Plantform}",
                        "👤 用户已加入",
                    ))
                except Exception as e:
                    logger.opt(exception=False).error(f"创建用户{user_name}至在可访问列表时发生错误: {e}")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")

@user_unsub.handle()
async def handle_user_unsub(args: Message = CommandArg()):
    """
    删除可访问用户列表中用户
    """
    command = args.extract_plain_text().strip()
    parts = _split_args(command)
    if not parts:
        await user_unsub.finish(info("`删除用户 <用户ID>`", "📖 删除用户用法"))
    user_id = parts[0]
    async with (get_session() as db_session):
        try:
            # 检查数据库中是否已存在该 Student_id 的记录
            existing_lanmsg = await UserManager.get_Sign_by_student_id(
                db_session, user_id)
            if not existing_lanmsg:
                logger.info(f"用户{user_id}不在可访问列表")
                await user_unsub.send(info(f"用户 `{user_id}` 不在可访问列表中。", "👤 删除用户"))
            else:
                try:
                    user_name = existing_lanmsg.User_Name
                    await UserManager.delete_id(db_session,id=user_id)
                    await user_unsub.send(success(
                        f"- 用户名：**{user_name}**\n- 用户 ID：`{user_id}`",
                        "👤 用户已删除",
                    ))
                except Exception as e:
                    logger.opt(exception=False).error(f"将用户{user_id}移出可访问列表时发生错误: {e}")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")

@user_list.handle()
async def handle_user_list(event: GroupMessageCreateEvent):
    """
    查询当前可访问用户列表
    """
    async with (get_session() as db_session):
        try:
            flag = await UserManager.is_database_empty(db_session)
            if flag:
                await user_list.send(info("当前没有可访问用户。", "👥 用户列表"))
            else:
                all_users = await UserManager.get_all_users(db_session)
                msg_parts = []
                for user in all_users:
                    msg_parts.append(f"- {user.User_Name}（`{user.User_ID}`）")
                await user_list.send(quoted_card(
                    "📋 当前可访问用户列表",
                    "\n".join(msg_parts),
                    "如需增加新用户，请联系管理员，或发邮件至：public@tano.asia",
                ))

        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")


find = on_command("查询", priority=10, rule=group_rule)
@find.handle()
async def handle_find(event: GroupMessageCreateEvent, args: Message = CommandArg()):
    """
    订阅情况查询
    """
    async with (get_session() as db_session):
        command = args.extract_plain_text().strip()
        parts = _split_args(command)
        if command.startswith("群组"):
            if len(parts) >= 2 and await is_superuser(event):
                group_id = parts[1]
            else:
                group_id = group_openid(event)
            try:
                # 直接按群组ID查询订阅
                subscriptions = await SubscribeManager.get_subscriptions_by_group(db_session, group_id)
                if not subscriptions:
                    await find.send(info(f"群 `{group_id}` 当前没有订阅。", "🔎 查询结果"))
                else:
                    msg_parts = [f"群 OpenID：`{group_id}`", "订阅用户："]
                    for sub in subscriptions:
                        msg_parts.append(f"- `{sub.username}`")
                    await find.send(quoted_card("📋 群订阅列表", "\n".join(msg_parts)))
            except SQLAlchemyError as e:
                logger.opt(exception=False).error(f"数据库操作错误: {e}")
        elif command.startswith("用户"):
            if not await is_superuser(event):
                await find.finish(warning(
                    "仅超级管理员可查询用户在全部群的订阅情况。",
                    "🔎 查询用户",
                ))
            if len(parts) < 2:
                await find.finish(info("`查询 用户 <用户ID>`", "📖 查询用法"))
            user_id = parts[1]
            try:
                # 直接按用户名查询订阅
                subscriptions = await SubscribeManager.get_subscriptions_by_username(db_session, user_id)
                if not subscriptions:
                    await find.send(info(f"用户 `{user_id}` 当前没有订阅。", "🔎 查询结果"))
                else:
                    msg_parts = [f"用户 ID：`{user_id}`", "推送群组："]
                    for sub in subscriptions:
                        msg_parts.append(f"- `{sub.group}`")
                    await find.send(quoted_card("📋 用户推送群组", "\n".join(msg_parts)))
            except SQLAlchemyError as e:
                logger.opt(exception=False).error(f"数据库操作错误: {e}")
        else:
            await find.finish(warning("请输入 `查询 群组 [群OpenID]` 或 `查询 用户 <用户ID>`。", "📖 查询用法"))


# ==================== 导入关注功能 ====================
import_following = on_command(
    "import_following",
    aliases={"导入关注"},
    priority=10,
    rule=group_rule
)

import_following_private = on_command(
    "import_following",
    aliases={"导入关注"},
    priority=10,
    rule=private_rule,
)

# 存储待确认的批量订阅 {group_id: [matched_users]}
pending_batch_subscribe: dict[str, list[str]] = {}


@import_following.handle()
async def handle_import_following_group(event: GroupMessageCreateEvent):
    """群聊中拒绝使用导入关注命令"""
    await import_following.finish(warning(
        "此命令包含 X 凭据，请在与机器人的私聊中执行。\n\n"
        "`导入关注 <群 OpenID> <auth_token> <ct0> <X 用户名>`",
        "🔐 请在私聊中操作",
    ))


@import_following_private.handle()
async def handle_import_following_private(event: C2CMessageCreateEvent, args: Message = CommandArg()):
    """
    导入X关注列表并匹配可订阅用户（仅限私聊）

    用法: 导入关注 <群 OpenID> <auth_token> <ct0> <x用户名>

    获取凭据方法:
    1. 登录 X (twitter.com)
    2. 打开浏览器开发者工具 (F12)
    3. 在 Application > Cookies 中找到 auth_token 和 ct0
    """
    command = args.extract_plain_text().strip()
    parts = command.split()

    if len(parts) < 4:
        await import_following_private.finish(info(
            "`导入关注 <群 OpenID> <auth_token> <ct0> <X用户名>`\n\n"
            "获取凭据：\n"
            "1. 登录 X (twitter.com)\n"
            "2. 打开浏览器开发者工具（F12）\n"
            "3. 切换到 Application > Cookies > twitter.com\n"
            "4. 找到 `auth_token` 和 `ct0`",
            "📖 导入关注用法",
        ))

    group_id = parts[0]

    auth_token = parts[1]
    ct0 = parts[2]
    screen_name = parts[3]

    await import_following_private.send(info(
        f"正在获取 @{screen_name} 的关注列表，请稍候。", "🔄 导入关注"
    ))

    try:
        # 获取数据库中可订阅的用户列表
        available_users = await User_get()

        if not available_users:
            await import_following_private.finish(warning(
                "当前没有可订阅用户。", "🔄 导入关注"
            ))

        # 获取关注列表并匹配
        matched_users, fetched_count, total_count = await fetch_and_match(
            auth_token=auth_token,
            ct0=ct0,
            screen_name=screen_name,
            available_users=available_users,
            max_fetch=1000  # 限制最多获取1000个关注
        )

        if not matched_users:
            await import_following_private.finish(info(
                f"已扫描 {fetched_count}/{total_count} 个关注，未找到匹配的可订阅用户。",
                "🔄 导入关注",
            ))

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

            msg_parts.append(f"\n💡 请在群 {group_id} 中回复 \"确认订阅\" 一键订阅以上 {len(not_subscribed)} 个用户")
            msg_parts.append("\n💡 或回复 \"订阅编号 1 3 5\" 选择性订阅")
        else:
            msg_parts.append("✨ 所有匹配用户均已订阅")

        await import_following_private.finish(quoted_card("📊 导入关注结果", "".join(msg_parts)))

    except Exception as e:
        logger.opt(exception=True).error(f"导入关注失败: {e}")
        await import_following_private.finish(error(str(e), "🔄 导入关注失败"))


# 确认批量订阅
confirm_batch_sub = on_command(
    "确认订阅",
    priority=10,
    rule=group_rule
)


@confirm_batch_sub.handle()
async def handle_confirm_batch_sub(event: GroupMessageCreateEvent):
    """确认批量订阅待确认列表中的所有用户"""
    group_id = group_openid(event)

    if group_id not in pending_batch_subscribe or not pending_batch_subscribe[group_id]:
        await confirm_batch_sub.finish(warning(
            "没有待确认的订阅，请先在私聊中使用 `导入关注`。", "📬 批量订阅"
        ))

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

    await confirm_batch_sub.finish(success(
        f"- 成功：{success_count} 个\n- 失败：{fail_count} 个",
        "📬 批量订阅完成",
    ))


# 按编号订阅
sub_by_index = on_command(
    "订阅编号",
    aliases={"订阅选择"},
    priority=10,
    rule=group_rule
)


@sub_by_index.handle()
async def handle_sub_by_index(event: GroupMessageCreateEvent, args: Message = CommandArg()):
    """按编号订阅选择面板或导入关注待确认列表中的用户。"""
    group_id = group_openid(event)
    command = args.extract_plain_text().strip()

    if _get_picker_candidates(event, "subscribe") is not None:
        if not command:
            await sub_by_index.finish(info(
                "`订阅选择 1 3 5`\n\n或：`订阅选择 1-10`",
                "📖 订阅选择用法",
            ))
        result = await _apply_picker_selection(event, "subscribe", command)
        if result is None:
            await sub_by_index.finish(warning(
                "选择面板已过期，请重新发送 `订阅`。", "📬 订阅选择"
            ))
        succeeded, failed = result
        if not succeeded and not failed:
            await sub_by_index.finish(error(
                "请输入当前页内的有效编号，例如 `订阅选择 1 3 5`。", "📬 订阅选择"
            ))
        await sub_by_index.finish(quoted_card(
            "📬 订阅完成",
            f"成功：{len(succeeded)} 个\n"
            f"用户：{', '.join(succeeded) or '无'}\n"
            f"失败：{len(failed)} 个"
            + (f"（{', '.join(failed)}）" if failed else ""),
        ))

    if group_id not in pending_batch_subscribe or not pending_batch_subscribe[group_id]:
        await sub_by_index.finish(warning(
            "没有待确认的订阅，请先在私聊中使用 `导入关注`。", "📬 按编号订阅"
        ))

    if not command:
        await sub_by_index.finish(info(
            "`订阅编号 1 3 5`\n\n或：`订阅编号 1-10`",
            "📖 按编号订阅",
        ))

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
        await sub_by_index.finish(error(
            f"有效编号范围为 `1-{len(users_list)}`。", "📖 按编号订阅"
        ))

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

    await sub_by_index.finish(quoted_card(
        "📬 订阅完成",
        f"- 成功：{success_count} 个（{', '.join(subscribed_users)}）\n"
        f"- 失败：{fail_count} 个",
    ))


unsub_by_index = on_command(
    "取消订阅选择",
    aliases={"退订选择", "取消订阅编号"},
    priority=10,
    rule=group_rule,
)


@unsub_by_index.handle()
async def handle_unsub_by_index(event: GroupMessageCreateEvent, args: Message = CommandArg()):
    """按编号取消订阅选择面板中的用户。"""
    command = args.extract_plain_text().strip()
    if _get_picker_candidates(event, "unsubscribe") is None:
        await unsub_by_index.finish(warning(
            "没有可用的退订选择面板，请先发送 `取消订阅`。", "📭 退订选择"
        ))
    if not command:
        await unsub_by_index.finish(info(
            "`取消订阅选择 1 3 5`\n\n或：`取消订阅选择 1-10`",
            "📖 退订选择用法",
        ))

    result = await _apply_picker_selection(event, "unsubscribe", command)
    if result is None:
        await unsub_by_index.finish(warning(
            "选择面板已过期，请重新发送 `取消订阅`。", "📭 退订选择"
        ))
    succeeded, failed = result
    if not succeeded and not failed:
        await unsub_by_index.finish(error(
            "请输入当前页内的有效编号，例如 `取消订阅选择 1 3 5`。", "📭 退订选择"
        ))
    await unsub_by_index.finish(quoted_card(
        "📭 退订完成",
        f"成功：{len(succeeded)} 个\n"
        f"用户：{', '.join(succeeded) or '无'}\n"
        f"失败：{len(failed)} 个"
        + (f"（{', '.join(failed)}）" if failed else ""),
    ))


list_article = on_command("list", aliases={"文章列表"}, priority=10, rule=group_rule)
@list_article.handle()
async def handle_list_article(event: GroupMessageCreateEvent,args: Message = CommandArg()):
    """
    查询用户文章列表
    """
    logger.info(f"从官方群 {group_openid(event)} 发起 List 请求")
    userid = args.extract_plain_text().strip()
    sheet1 = await User_get()
    if not userid:
        await list_article.finish(info("`文章列表 aibaaiai`", "📖 文章列表用法"))
    elif userid not in sheet1:
        await list_article.finish(warning("该用户不在可访问列表中。", "🐦 文章列表"))
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
                await list_article.finish(error(data["error"], "🐦 文章列表"))

            if not data.get("entries"):
                await list_article.finish(info("该用户暂无动态，或用户不存在。", "🐦 文章列表"))

            entries = []
            num = len(data.get("entries"))
            for i in range(0,num):
                latest = data.get("entries")[i]
                entries.append(f"{i}. {latest.title}")

            await list_article.finish(quoted_card(f"🐦 @{username} 的动态列表", "\n".join(entries)))

def _group_settings_text(group_id: str, group_settings=None) -> str:
    settings = _parse_group_config(group_settings)
    status = lambda value: "开" if value else "关"
    limit = settings["push_limit"]
    amount = "全部未发送（0）" if limit == 0 else f"最近 {limit} 篇"
    return (
        f"群 OpenID：`{group_id}`\n"
        f"转发：{status(settings['if_need_trans'])} · "
        f"自转发：{status(settings['if_need_self_trans'])} · "
        f"翻译：{status(settings['if_need_translate'])}\n"
        f"推送数量：**{amount}**（每个账号、每轮）\n\n"
        "`群组配置 推送数量 1`\n"
        "`群组配置 转发 开` · `群组配置 自转发 关` · `群组配置 翻译 开`\n"
        "数量可设 1–5，0 为全部；窗口外的旧文章静默登记。"
    )


group_config = on_command("群组配置", priority=10, rule=group_rule)
@group_config.handle()
async def group_config_(event: GroupMessageCreateEvent, args: Message = CommandArg()):
    command = args.extract_plain_text().strip()
    group_id = group_openid(event)
    parts = _split_args(command)
    fields = {
        "推送数量": "push_limit", "转发": "if_need_trans",
        "自转发": "if_need_self_trans", "自我转发": "if_need_self_trans",
        "翻译": "if_need_translate",
    }
    changes = {}
    if len(parts) == 2 and parts[0] in fields:
        field = fields[parts[0]]
        if field == "push_limit":
            value = _parse_int(parts[1])
            if value is None or not 0 <= value <= 5:
                await group_config.finish(error("推送数量必须是 0–5 的整数；0 表示全部未发送。", "⚙️ 群组配置"))
        else:
            value = {"开": True, "关": False, "1": True, "0": False}.get(parts[1])
            if value is None:
                await group_config.finish(error("开关请填写「开」「关」或 1、0。", "⚙️ 群组配置"))
        changes[field] = value
    elif parts:
        values = [_parse_int(item) for item in parts]
        if len(values) not in (3, 4) or any(value not in (0, 1) for value in values):
            await group_config.finish(info(
                "发送 `群组配置` 查看设置；按名称修改，例如：\n"
                "`群组配置 推送数量 1`\n"
                "`群组配置 转发 开`\n"
                "`群组配置 自转发 关`\n"
                "`群组配置 翻译 开`",
                "⚙️ 群组配置用法",
            ))
        changes.update(
            if_need_trans=bool(values[0]), if_need_self_trans=bool(values[1]),
            if_need_translate=bool(values[2]), if_need_photo_num_mention=False,
        )

    try:
        async with get_session() as session:
            current = await GroupconfigManager.get_Sign_by_group_id(session, group_id)
            if changes:
                if current is None:
                    defaults = dict(
                        group_id=group_id, if_need_trans=True, if_need_self_trans=False,
                        if_need_translate=True, if_need_photo_num_mention=False,
                        if_need_merged_message=True, push_limit=1,
                    )
                    defaults.update(changes)
                    current = await GroupconfigManager.create_signmsg(session, **defaults)
                else:
                    await GroupconfigManager.update_config(session, group_id, **changes)
                await session.refresh(current)
            text = _group_settings_text(group_id, current)
            if changes:
                text += "\n\n修改将在下一轮刷新时生效。"
        await group_config.finish(info(text, "⚙️ 群组配置已更新" if changes else "⚙️ 当前群组配置"))
    except SQLAlchemyError as exc:
        logger.opt(exception=False).error(f"群组配置读写失败：{exc}")
        await group_config.finish(error("配置读写失败，请稍后重试。", "⚙️ 群组配置"))


view_config = on_command("查看配置", priority=10, rule=group_rule)
@view_config.handle()
async def handle_view_config(event: GroupMessageCreateEvent):
    """查看当前群组的配置状态"""
    group_id = group_openid(event)
    async with (get_session() as db_session):
        config_msg = await GroupconfigManager.get_Sign_by_group_id(db_session, group_id)
        await view_config.finish(info(_group_settings_text(group_id, config_msg), "⚙️ 当前群组配置"))


help = on_command("/help", aliases={"/帮助","help","帮助"}, priority=10, rule=group_rule)
@help.handle()
async def handle_help(event: GroupMessageCreateEvent):
    """发送带 QQ 官方指令按钮的帮助面板。"""
    group_keyboard = command_keyboard(
        [
            [
                ("RSS·填ID", "rss <用户ID> [序号]", False),
                ("文章·填ID", "文章列表 <用户ID>", False),
            ],
            [("👥 用户列表", "用户列表", True), ("ℹ️ 群信息", "群信息", True)],
            [
                ("订阅面板", "订阅", True),
                ("退订面板", "取消订阅", True),
            ],
            [("📋 本群订阅", "查询 群组", True), ("⚙️ 查看配置", "查看配置", True)],
            [("⚙️ 群组配置", "群组配置", True), ("推送数量·填参", "群组配置 推送数量 <0-5>", False)],
            [("转发·填参", "群组配置 转发 <开/关>", False), ("翻译·填参", "群组配置 翻译 <开/关>", False)],
        ]
    )
    await help.send(markdown(
        config.help_msg_1
        + "\n\n> 标有“填……”的按钮需要补充参数；点击后会在输入框中显示参数格式。"
    ) + group_keyboard)

    if not await is_superuser(event):
        await help.finish(markdown(
            "> 以上为当前群所有成员可用的功能，群 OpenID 会自动从当前会话读取。\n\n"
            "[项目主页](https://github.com/AhsokaTano26/nsybot)"
        ))

    advanced_keyboard = command_keyboard(
        [
            [
                ("📚 全部订阅", "订阅列表", True),
                ("查群·填ID", "查询 群组 <群OpenID>", False),
                ("查人·填ID", "查询 用户 <用户ID>", False),
            ],
            [
                ("加人·填参", "增加用户 <用户ID> <用户名> <平台名>", False),
                ("删人·填ID", "删除用户 <用户ID>", False),
                ("🧹 清理订阅", "清理失效订阅", True),
            ],
            [
                ("📊 订阅统计", "订阅统计", True),
                ("👥 群列表", "群列表", True),
                ("📈 发送统计", "发送统计", True),
                ("🔄 刷新推送", "refresh", True),
            ],
            [
                ("群发·填参", "/发送 <内容>", False),
                ("📡 首轮状态", "/信号", True),
                ("跳过首轮检查", "/信号否", True),
            ],
            [
                ("平台列表", "平台列表", True),
                ("加平台·填参", PLATFORM_USAGES["增加平台"], False),
                ("改平台·填参", PLATFORM_USAGES["修改平台"], False),
                ("删平台·填参", PLATFORM_USAGES["删除平台"], False),
            ],
        ]
    )
    await help.finish(markdown(
        "# 🧰 超级管理员命令\n\n"
        "平台管理：`平台列表`、`增加平台`、`修改平台`、`删除平台`。\n\n"
        "> 标有“填……”的按钮需要补充参数；其余按钮可直接执行。"
    ) + advanced_keyboard)

send_msg = on_command("/send", aliases={"/发送"}, priority=10, rule=superuser_group_rule)
@send_msg.handle()
async def handle_send_msg(args: Message = CommandArg()):
    """
    向所有订阅群组发送通知
    """
    command = args.extract_plain_text().strip()
    msg = str(command.split("*")[0])
    async with (get_session() as db_session):
        try:
            all_subscriptions = await SubscribeManager.get_all_subscriptions(db_session)
            bot = get_bot()

            # 去重并过滤ban_list
            group_set = {
                str(sub.group) for sub in all_subscriptions
                if str(sub.group) not in set(config.broadcast_ban_openids)
            }

            for group_id in group_set:
                try:
                    await send_group_message(bot, group_id, info(msg, "📢 系统通知"))
                    logger.info(f"成功发送消息到群 {group_id}")
                except Exception as e:
                    logger.opt(exception=False).error(f"发送消息到群 {group_id} 失败: {e}")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")
        except Exception as e:
            logger.opt(exception=False).error(f"发送时发生错误: {e}")

signal = on_command("/信号", priority=10, rule=superuser_group_rule)
@signal.handle()
async def signal_():
    if_first_time_start = await rss_get().get_signal()
    await signal.finish(info(
        f"首次运行标识：`{if_first_time_start}`\n\n"
        "启动首轮按群检查：上次成功推送超过 20 分钟或无成功记录时，只登记历史文章。"
        "首轮完成后自动关闭检查。",
        "📡 RSS 首轮检查",
    ))

signal_on = on_command("/信号否", priority=10, rule=superuser_group_rule)
@signal_on.handle()
async def signal_on_():
    await rss_get().change_config()
    if_first_time_start = await rss_get().get_signal()
    await signal_on.finish(success(
        f"首次运行标识：`{if_first_time_start}`\n\n"
        "已关闭本次启动的首轮时间检查；已经登记的历史文章不会补发。",
        "📡 RSS 首轮检查",
    ))

_refresh_lock = asyncio.Lock()


async def refresh_article():
    # 手动刷新与定时刷新共用锁，避免同一批文章被同时发送。
    async with _refresh_lock:
        await _refresh_article()


async def _refresh_article():
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
                    group = str(sub.group)
                    if username not in sub_list:
                        sub_list[username] = []
                    sub_list[username].append(group)
                logger.success(f"{datetime.now()} 已获取所有订阅信息")

                silent_groups = set()
                if config.if_first_time_start:
                    cutoff = datetime.now() - timedelta(minutes=20)
                    for group_id in {group for groups in sub_list.values() for group in groups}:
                        last_sent = await DetailManager.last_successful_delivery_at(db_session, group_id)
                        if last_sent is None or last_sent < cutoff:
                            silent_groups.add(group_id)
                        action = "静默登记历史文章" if group_id in silent_groups else "正常推送"
                        logger.info(f"启动首轮：群 {group_id} 上次成功推送 {last_sent or '无记录'}，{action}")

                await DetailManager.bootstrap_legacy_subscriptions(db_session, [
                    (user_id, group_id)
                    for user_id, groups in sub_list.items() for group_id in groups
                ], silent_groups=silent_groups)

                # 预加载所有群组配置
                group_configs = await GroupconfigManager.get_all_configs(db_session)
                logger.info(f"已预加载 {len(group_configs)} 个群组配置")

                accounts = list(sub_list.items())
                for index, (user, groups) in enumerate(accounts):
                    try:
                        logger.info(f"{datetime.now()} 开始处理对 {user} 的订阅")
                        # 同一账号的目标群在 handle_rss 内并行，账号之间顺序处理。
                        await R.handle_rss(userid=user, group_id_list=groups, group_configs=group_configs)
                    except Exception as exc:
                        logger.opt(exception=False).error(f"对于{user}的订阅时发生错误: {exc}")
                    if index < len(accounts) - 1:
                        await asyncio.sleep(random.uniform(5, 15))

            await rss_get().change_config()
            logger.info(f"config.if_first_time_start：{await rss_get().get_signal()}")

            logger.info(f"{datetime.now()} 订阅处理完毕")
        except SQLAlchemyError as e:
            logger.opt(exception=False).error(f"数据库操作错误: {e}")


refresh = on_command("refresh", priority=10, rule=superuser_group_rule)
@refresh.handle()
async def refresh_():
    """
    手动刷新推文
    """
    start_time = datetime.now()
    logger.info(f"{start_time} 开始刷新推文")
    await refresh_article()
    end_time = datetime.now()
    await refresh.finish(success(
        f"RSS 刷新完成，用时 `{end_time - start_time}`。", "🔄 手动刷新完成"
    ))


sub_stats = on_command("订阅统计", priority=10, rule=superuser_group_rule)
@sub_stats.handle()
async def handle_sub_stats():
    """查询总订阅群组数和总订阅数"""
    async with get_session() as db_session:
        all_subscriptions = await SubscribeManager.get_all_subscriptions(db_session)
        total_subs = len(all_subscriptions)
        group_set = {sub.group for sub in all_subscriptions}
        user_set = {sub.username for sub in all_subscriptions}

        await sub_stats.finish(info(
            f"- 总订阅数：**{total_subs}**\n"
            f"- 订阅群组数：**{len(group_set)}**\n"
            f"- 订阅用户数：**{len(user_set)}**",
            "📊 订阅统计",
        ))


tweet_stats = on_command("发送统计", priority=10, rule=superuser_group_rule)
@tweet_stats.handle()
async def handle_tweet_stats():
    """查询过去24h发送的推文数"""
    async with get_session() as db_session:
        count = await DetailManager.count_recent(db_session, hours=24)
        await tweet_stats.finish(info(
            f"过去 24 小时共发送 **{count}** 条动态。", "📊 发送统计"
        ))


joined_groups_cmd = on_command("群列表", aliases={"已加入群"}, priority=10, block=True, rule=Rule(is_superuser))


@joined_groups_cmd.handle()
async def handle_joined_groups(args: Message = CommandArg()):
    parts = _split_args(args.extract_plain_text())
    page = _parse_int(parts[0]) if parts else 1
    if len(parts) > 1 or page is None or page < 1:
        await joined_groups_cmd.finish(error("用法：`群列表 [页码]`，页码从 1 开始。", "👥 群登记表"))
    async with get_session() as session:
        total, rows = await BotGroupManager.page(session, page=page, page_size=10)
        pages = max(1, (total + 9) // 10)
        if page > pages:
            await joined_groups_cmd.finish(error(f"当前共 {pages} 页。", "👥 群登记表"))
        sources = {"join": "入群事件确认", "message": "群消息确认", "history": "历史补录，待确认"}
        lines = [
            f"`{row.group_openid}`\n"
            f"入群：{_registry_display_time(row.joined_at)} · {sources.get(row.source, row.source)}"
            for row in rows
        ]
    await joined_groups_cmd.finish(quoted_card(
        f"👥 群登记表 · {total} 群 · 第 {page}/{pages} 页",
        "\n\n".join(lines) or "暂无群登记记录。",
        "时间为北京时间。历史待确认记录不代表已重新核实在群；真实入群时间未知时留空。\n"
        "翻页：`群列表 <页码>`",
    ))


async def _cleanup_orphan_subscriptions() -> str:
    """报告订阅与群登记差异；仅退群事件可作为自动删除依据。"""
    async with get_session() as db_session:
        joined_group_ids = await _get_joined_group_ids()
        all_subscriptions = await SubscribeManager.get_all_subscriptions(db_session)
        subscribed_group_ids = {str(sub.group) for sub in all_subscriptions}

        untracked_group_ids = sorted(subscribed_group_ids - joined_group_ids)
        if not untracked_group_ids:
            return (
                "✅ 订阅群均已有登记\n"
                f"登记群聊数: {len(joined_group_ids)}\n"
                f"订阅群组数: {len(subscribed_group_ids)}\n"
                "已收到退群事件的群会实时清理订阅和配置。"
            )
        return (
            f"登记群聊数: {len(joined_group_ids)}\n"
            f"订阅群组数: {len(subscribed_group_ids)}\n"
            f"未登记的订阅群: {len(untracked_group_ids)}\n\n"
            + "\n".join(untracked_group_ids)
            + "\n\n缺少退群证据，已保留这些订阅；收到群消息时会自动补登记。"
        )


cleanup_orphan_subscriptions = on_command(
    "清理失效订阅",
    aliases={"清理群订阅", "清理失效群订阅"},
    priority=10,
    rule=superuser_group_rule,
)


@cleanup_orphan_subscriptions.handle()
async def handle_cleanup_orphan():
    """手动清理失效群订阅"""
    try:
        report = await _cleanup_orphan_subscriptions()
        logger.info(f"手动清理失效订阅结果:\n{report}")

        # 发送到 target_groups
        try:
            bot = get_bot()
            if config.target_group_openid:
                await send_group_message(
                    bot,
                    config.target_group_openid,
                    quoted_card("🧹 手动清理失效订阅报告", report),
                )
        except Exception as e:
            logger.error(f"发送清理报告失败: {e}")

        await cleanup_orphan_subscriptions.finish(quoted_card("🧹 清理失效订阅报告", report))
    except Exception as e:
        logger.opt(exception=True).error(f"清理失效订阅失败: {e}")
        await cleanup_orphan_subscriptions.finish(error(str(e), "🧹 清理失效订阅失败"))


# 已构造好的 CronTrigger 不会继承调度器上的 apscheduler.timezone，缺省会回落到
# 进程本地时区，所以显式指定时区，避免清理时刻随运行环境的 TZ 漂移。
@scheduler.scheduled_job(
    CronTrigger(day_of_week="mon", hour=10, minute=0, timezone="Asia/Shanghai"),
    misfire_grace_time=60,
)
async def weekly_cleanup_orphan():
    """每周一10:00定时清理失效群订阅"""
    try:
        bot = get_bot()
        if not bot:
            logger.error("未能获取到有效的 bot 实例")
            return

        report = await _cleanup_orphan_subscriptions()
        logger.info(f"定时清理失效订阅结果:\n{report}")

        if config.target_group_openid:
            await send_group_message(
                bot,
                config.target_group_openid,
                quoted_card("🧹 每周清理失效订阅报告", report),
            )
    except Exception as e:
        logger.opt(exception=True).error(f"定时清理失效订阅失败: {e}")


@scheduler.scheduled_job('interval',minutes=config.refresh_time,misfire_grace_time=60)
async def auto_update_func():
    """
    定时任务，检查更新并向订阅群组发送推文
    """
    start_time = datetime.now()
    logger.info(f"任务开始: {start_time}")

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


group_removed = on_type(GroupDelRobotEvent, priority=10, block=False)


@group_removed.handle()
async def handle_group_removed(event: GroupDelRobotEvent):
    """退群时原子删除登记、RSS 订阅和群配置。"""
    group_id = str(event.group_openid)
    left_at = _registry_event_time(event.timestamp)
    async with _delivery_lock(f"membership:{group_id}"):
        async with get_session() as session, session.begin():
            current = await session.get(BotGroup, group_id)
            evidence = [stamp for stamp in (
                current.joined_at if current else None, current.last_seen_at if current else None,
            ) if stamp is not None]
            # QQ 入群/退群时间可能仅精确到秒；同一秒内按收到的事件顺序处理。
            if any(stamp.replace(microsecond=0) > left_at.replace(microsecond=0) for stamp in evidence):
                logger.info(f"忽略群 {group_id} 早于最新在群证据的退群事件")
                return
            await BotGroupManager.remove(session, group_id)
            result = await session.execute(delete(Subscribe).where(Subscribe.group == group_id))
            deleted = result.rowcount
            await session.execute(delete(Groupconfig).where(Groupconfig.group_id == group_id))
        previous = _departed_groups.get(group_id)
        _departed_groups[group_id] = max(left_at, previous) if previous else left_at
    logger.info(f"机器人已被移出群 {group_id}，删除 {deleted} 条订阅")
    if config.target_group_openid:
        await send_group_message(
            get_bot(),
            config.target_group_openid,
            warning(
                f"群 OpenID：`{group_id}`\n\n已删除 {deleted} 条订阅及该群配置。",
                "🤖 机器人已被移出群",
            ),
        )


group_added = on_type(GroupAddRobotEvent, priority=10, block=False)


@group_added.handle()
async def handle_group_added(event: GroupAddRobotEvent):
    group_id = str(event.group_openid)
    joined_at = _registry_event_time(event.timestamp)
    async with _delivery_lock(f"membership:{group_id}"):
        departed_at = _departed_groups.get(group_id)
        if departed_at and joined_at.replace(microsecond=0) < departed_at.replace(microsecond=0):
            return
        async with get_session() as session, session.begin():
            await BotGroupManager.record_join(session, group_id, joined_at)
        _departed_groups.pop(group_id, None)
    logger.info(f"机器人已加入群 {event.group_openid}")
    if config.target_group_openid:
        await send_group_message(
            get_bot(),
            config.target_group_openid,
            success(
                f"群 OpenID：`{event.group_openid}`\n入群时间：{_registry_display_time(joined_at)}（北京时间）",
                "🤖 机器人已加入新群",
            ),
        )
