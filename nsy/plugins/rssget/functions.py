import asyncio
from datetime import datetime
import random
from urllib.parse import urlencode
from weakref import WeakValueDictionary
import feedparser
import httpx
from nonebot import get_bot, get_plugin_config
from nonebot.log import logger
from nonebot_plugin_orm import get_session
from sqlalchemy.exc import SQLAlchemyError

from .config import Config
from .format_json import Format
from .get_id import get_id
from .models_method import DetailManager, PlantformManager, UserManager
from .trans_msg import if_self_trans, if_trans
from .update_text import get_text, update_text
from nsy.qq_utils import article_card, download_image, error, file_image, info, send_group_message

config = get_plugin_config(Config)

class NetworkManager:
    _client: httpx.AsyncClient = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            # 配置连接池：保持 20 个长连接，最多允许 50 个并发
            limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
            # 配置超时：连接 10s，读写 30s
            timeout = httpx.Timeout(30.0, connect=10.0)
            cls._client = httpx.AsyncClient(
                limits=limits,
                timeout=timeout,
                follow_redirects=True,
            )
        return cls._client

    @classmethod
    async def close(cls):
        if cls._client:
            await cls._client.aclose()
            logger.info("网络连接池已关闭")


# 限制并行处理正文/附件的任务数；实际 QQ 发送频率由 qq_utils 控制。
_msg_semaphore = asyncio.Semaphore(3)
_delivery_locks = WeakValueDictionary()


def _delivery_lock(key: str):
    lock = _delivery_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _delivery_locks[key] = lock
    return lock

# 默认群组配置值
_DEFAULT_GROUP_CONFIG = {
    "if_need_trans": True,
    "if_need_self_trans": False,
    "if_need_translate": True,
    "if_need_photo_num_mention": True,
}


def _parse_group_config(group_config) -> dict:
    """从群组配置对象或None解析配置字典"""
    if group_config:
        return {
            "if_need_trans": group_config.if_need_trans,
            "if_need_self_trans": group_config.if_need_self_trans,
            "if_need_translate": group_config.if_need_translate,
            "if_need_photo_num_mention": group_config.if_need_photo_num_mention,
        }
    return _DEFAULT_GROUP_CONFIG


async def fetch_feed(url: str) -> dict:
    """异步获取并解析RSS内容"""
    client = NetworkManager.get_client()
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)

        if parsed.bozo:  # feedparser 内部解析错误
            logger.warning(f"RSS 格式异常: {url}")

        return parsed
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP错误 {e.response.status_code}: {url}")
    except httpx.RequestError as e:
        logger.error(f"网络请求异常: {type(e).__name__} on {url}")
    except Exception as e:
        logger.exception(f"解析非预期错误: {url}")
    return {"entries": [], "error": "Fetch failed"}


class rss_get():
    @staticmethod
    async def report_status(status_url):
        """
        发送bot状态报告
        Args: status_url (str): uptime-kuma状态检查url
        """
        client = NetworkManager.get_client()

        # 使用 create_task 以后台执行，不等待响应直接继续处理下一个 RSS
        async def _do_report():
            try:
                await client.get(status_url, timeout=5)
            except Exception:
                pass

        asyncio.create_task(_do_report())

    async def send_qq_image(self, img_url: str, group_id: str, retry_count: int = 0):
        """附件最多尝试四次；失败告知用户，不让已发送的正文重复推送。"""
        for attempt in range(retry_count, 4):
            try:
                data, file_name = await download_image(img_url, NetworkManager.get_client())
                await send_group_message(get_bot(), group_id, file_image(data, file_name))
                return True
            except Exception as exc:
                if attempt < 3:
                    logger.warning(f"图片发送失败，将重试：{type(exc).__name__}")
                    await asyncio.sleep((attempt + 1) * 2)
                else:
                    logger.error(f"图片发送达到最大重试次数：{img_url}")
                    try:
                        await send_group_message(
                            get_bot(), group_id,
                            error("正文已发送，但这张图片在重试后仍发送失败。", "🖼️ 图片发送失败"),
                        )
                    except Exception as warning_error:
                        logger.warning(f"图片失败提示也未发送：{type(warning_error).__name__}")
        return False

    async def send_text(self,
                        group_id: str,
                        content: dict,
                        if_need_trans: int,
                        if_is_self_trans: bool,
                        if_is_trans: bool,
                        group_config=None
                        ):
        """
        发送推文内容到群组
        group_config: 预加载的群组配置对象（可选），避免每次查库
        """
        logger.opt(exception=False).info(f"正在发送内容到群 {group_id}")
        if_need_trans = True if if_need_trans == 1 else False

        # 使用预加载配置
        gc = _parse_group_config(group_config)
        if_need_user_trans = gc["if_need_trans"]
        if_need_self_trans = gc["if_need_self_trans"]
        if_need_translate = gc["if_need_translate"]
        if_need_photo_num_mention = gc["if_need_photo_num_mention"]

        if if_is_self_trans:
            allowed = if_need_self_trans
        elif if_is_trans:
            allowed = if_need_user_trans
        else:
            allowed = True
        if allowed:
            translation = None
            if if_need_trans and if_need_translate:
                translation = content.get("trans_text") or "（暂无翻译）"

            async with _msg_semaphore:
                await self.handle_markdown_send(
                    group_id=group_id,
                    content=content,
                    translation=translation,
                    if_need_photo_num_mention=if_need_photo_num_mention,
                )
            return True
        return False

    @staticmethod
    async def handle_markdown_send(
        group_id: str, content: dict, translation: str | None = None,
        if_need_photo_num_mention: bool = True,
    ):
        """正文发送失败由调用方重试；附件失败降级为带警告的正文成功。"""
        bot = get_bot()
        try:
            await send_group_message(
                bot, group_id,
                article_card(content, translation, config.model_name if translation else None),
            )
        except Exception as exc:
            logger.error(f"发送群 {group_id} RSS 正文失败：{exc}")
            raise
        images = list(dict.fromkeys(content.get("images") or []))
        if images and if_need_photo_num_mention:
            try:
                await send_group_message(bot, group_id, info(
                    f"共 {len(images)} 张，正在逐张发送。", "🖼️ 图片附件",
                ))
            except Exception as exc:
                logger.warning(f"图片数量提示未发送，继续发送附件：{type(exc).__name__}")
        failures = 0
        for url in images:
            if not await rss_get().send_qq_image(url, group_id):
                failures += 1
        if failures:
            logger.warning(f"群 {group_id} RSS 正文已发送，{failures} 张附件失败")
        else:
            logger.info(f"群 {group_id} RSS 正文与附件发送完成")

    async def _fetch_user_feed(self, userid: str, route: str, platform_name: str):
        hosts = list(dict.fromkeys([config.rsshub_host, *(config.rsshub_host_back or [])]))
        for host in hosts:
            if not host:
                continue
            data = await fetch_feed(f"{host.rstrip('/')}/{route.lstrip('/')}{userid}")
            if data.get("entries") and not data.get("error"):
                if config.ut_url:
                    separator = "&" if "?" in config.ut_url else "?"
                    await self.report_status(config.ut_url + separator + urlencode({
                        "status": "up", "msg": f"{platform_name} 可用", "ping": "",
                    }))
                return data
            logger.warning(f"用户 {userid} 的 RSS 源无有效条目，尝试下一个源")
        if config.ut_url:
            separator = "&" if "?" in config.ut_url else "?"
            await self.report_status(config.ut_url + separator + urlencode({
                "status": "down", "msg": f"{platform_name} 所有源均无有效条目", "ping": "",
            }))
        return None

    async def handle_rss(self, userid: str, group_id_list: list, group_configs: dict = None):
        async with get_session() as session:
            user = await UserManager.get_Sign_by_student_id(session, userid)
            if not user:
                logger.warning(f"订阅用户 {userid} 不存在，跳过")
                return
            username = user.User_Name
            platform = await PlantformManager.get_Sign_by_student_id(session, user.Plantform)
            if platform is None:
                logger.warning(f"用户 {userid} 的平台不存在，跳过")
                return
            route, platform_name, need_trans = platform.url, platform.name, int(platform.need_trans)
        data = await self._fetch_user_feed(userid, route, platform_name)
        if data is None:
            return
        entries_info, seen = [], set()
        for latest in data.get("entries", []):
            try:
                trueid = await get_id(latest)
            except (ValueError, TypeError, AttributeError) as exc:
                logger.warning(f"跳过用户 {userid} 的无效 RSS 条目：{exc}")
                continue
            if trueid not in seen:
                entries_info.append((latest, trueid))
                seen.add(trueid)
        if not entries_info:
            return
        initialized_groups = []
        for group in group_id_list:
            try:
                async with _delivery_lock(f"rss-group:{group}"), get_session() as session:
                    await DetailManager.initialize_subscription(session, userid, group, entries_info)
                initialized_groups.append(group)
            except Exception as exc:
                logger.error(f"初始化 {group} 对 {userid} 的订阅失败，将下次重试：{exc}")
        group_id_list = initialized_groups
        if not group_id_list:
            return
        async with get_session() as session:
            existing_ids = await DetailManager.get_existing_ids(session, [
                record_id for _, trueid in entries_info for group in group_id_list
                for record_id in (f"{trueid}-{group}", DetailManager.skip_id(userid, group, trueid))
            ])
        for latest, trueid in entries_info:
            content = None
            is_self = await if_self_trans(username, latest)
            is_forward = await if_trans(latest)
            for group in group_id_list:
                record_id = f"{trueid}-{group}"
                skipped_id = DetailManager.skip_id(userid, group, trueid)
                if record_id in existing_ids or skipped_id in existing_ids:
                    continue
                try:
                    async with _delivery_lock(f"rss-group:{group}"):
                        # 和初始化共用群锁，保护不同订阅返回相同 GUID 的基线及发送记录。
                        async with get_session() as session:
                            existing = await DetailManager.get_existing_ids(session, [record_id, skipped_id])
                            if existing:
                                existing_ids.update(existing)
                                continue
                        if content is None:
                            try:
                                content = await get_text(trueid)
                            except (ValueError, SyntaxError, TypeError, AttributeError, SQLAlchemyError) as exc:
                                logger.warning(f"文章缓存不可用，将从 RSS 重建：{type(exc).__name__}")
                            if not content:
                                translate = need_trans if any(
                                    _parse_group_config((group_configs or {}).get(target))["if_need_translate"]
                                    for target in group_id_list
                                ) else 0
                                content = await Format().extract_content(latest, translate)
                                content.update(username=username, id=trueid)
                                await update_text(content)
                            content["username"] = username
                        sent = await self.send_text(
                            group, content, need_trans, is_self, is_forward,
                            (group_configs or {}).get(group),
                        )
                        processed_id = record_id if sent else skipped_id
                        async with get_session() as session:
                            await DetailManager.create_signmsg(
                                session, id=processed_id, summary=content.get("text"),
                                updated=datetime.now() if sent else None,
                            )
                        existing_ids.add(processed_id)
                        if sent:
                            await asyncio.sleep(random.uniform(1.5, 3.5))
                except Exception as exc:
                    # 每次记录使用独立会话；失败会回滚，不污染其他群的处理。
                    logger.error(f"处理 {group} 对 {userid} 的文章 {trueid} 失败：{exc}")
                await asyncio.sleep(0.1)

    async def change_config(self):
        config.if_first_time_start = False

    async def get_signal(self):
        return str(config.if_first_time_start)
