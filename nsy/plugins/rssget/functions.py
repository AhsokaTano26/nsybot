import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import math
import random
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from weakref import WeakValueDictionary
import feedparser
import httpx
from nonebot import get_bot, get_plugin_config
from nonebot.log import logger
from nonebot_plugin_orm import get_session
from sqlalchemy.exc import SQLAlchemyError

from .config import Config
from .availability import FeedUnavailable, utc_now
from .format_json import Format
from .get_id import get_id
from .models_method import DetailManager, PlantformManager, UserManager
from .models import RSSFeedCache
from .resource_limits import FeedResourceError, FeedSyntaxError, check_feed_structure, read_feed_body
from .state_machines import DeliveryDecision, delivery_decision
from .trans_msg import if_self_trans, if_trans
from .update_text import cache_entries, get_text, update_text
from nsy.qq_utils import article_messages, download_image, error, file_image, image_transfer_slot, send_group_message

config = get_plugin_config(Config)

class NetworkManager:
    _client: httpx.AsyncClient = None
    _rss_backoffs = {}
    # 至多两个有界响应；允许手动查询与采集并发观察限流，解析仍在单 worker 执行。
    _rss_capacity = asyncio.Semaphore(2)

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            # 采集和发送共用小型连接池。
            limits = httpx.Limits(max_connections=6, max_keepalive_connections=3)
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
    "push_limit": 1,
}


def _parse_group_config(group_config) -> dict:
    """从群组配置对象或None解析配置字典"""
    if group_config:
        return {
            "if_need_trans": group_config.if_need_trans,
            "if_need_self_trans": group_config.if_need_self_trans,
            "if_need_translate": group_config.if_need_translate,
            "push_limit": 1 if group_config.push_limit is None else group_config.push_limit,
        }
    return _DEFAULT_GROUP_CONFIG


async def fetch_feed(url: str) -> dict:
    """首次请求加三次指数退避；较长 Retry-After 延后该实例，交给调用方切备用。"""
    parts = urlsplit(url)
    host = parts.netloc
    # 共享同一路由的账号冷却，但不把 Twitter 的上游限制施加到 B 站等平台。
    scope = (parts.scheme, host, parts.path.rsplit("/", 1)[0])
    rate_limited, retry_after = False, 0
    for attempt in range(4):
        backoff = NetworkManager._rss_backoffs.get(scope)
        if backoff is not None:
            deadline, failure = backoff
            remaining = math.ceil((deadline - utc_now()).total_seconds())
            if remaining > 0:
                return dict(failure, retry_after=remaining)
            NetworkManager._rss_backoffs.pop(scope, None)
        result = await _fetch_feed_once(url)
        valid = result.get("entries") or (result.get("version") and not result.get("bozo"))
        if valid and not result.get("error"):
            return result
        rate_limited |= bool(result.get("rate_limited"))
        retry_after = max(retry_after, result.get("retry_after", 0))
        failure = dict(result, error=result.get("error") or "Invalid RSS", rate_limited=rate_limited,
                       retry_after=retry_after)
        if result.get("resource_limited"):
            return failure
        # 不在采集锁内等待很长的上游冷却；同一实例上的后续账号也遵守它。
        if retry_after > 30:
            return _remember_rss_backoff(scope, retry_after, failure)
        if attempt < 3:
            delay = max(config.rss_fetch_retry_base * 2 ** attempt, result.get("retry_after", 0))
            logger.warning(f"RSS 请求失败，{delay:g} 秒后第 {attempt + 1}/3 次重试：{host}")
            await asyncio.sleep(delay)
    if rate_limited:
        cooldown = max(config.rss_twitter_cooldown, retry_after)
        return _remember_rss_backoff(scope, cooldown, failure)
    return failure


def _remember_rss_backoff(scope, delay, failure):
    deadline = utc_now() + timedelta(seconds=delay)
    previous = NetworkManager._rss_backoffs.get(scope)
    if previous is None or previous[0] < deadline:
        NetworkManager._rss_backoffs[scope] = (deadline, failure)
    retained_deadline, retained_failure = NetworkManager._rss_backoffs[scope]
    return dict(retained_failure, retry_after=math.ceil((retained_deadline - utc_now()).total_seconds()))


async def _fetch_feed_once(url: str) -> dict:
    """单次请求保留上游错误类别，供实例重试与全局状态判断使用。"""
    client = NetworkManager.get_client()
    try:
        async with NetworkManager._rss_capacity:
            target = url
            for _ in range(6):
                # HTTPX 自动重定向会先无界读取中间响应；手动关闭正文再跳转。
                async with client.stream("GET", target, headers={"Accept-Encoding": "gzip, deflate"},
                                         follow_redirects=False) as resp:
                    if resp.is_redirect and resp.headers.get("location"):
                        target = urljoin(str(resp.url), resp.headers["location"])
                        if urlsplit(target).scheme not in {"http", "https"}:
                            raise FeedSyntaxError("InvalidFeedRedirect")
                        continue
                    if resp.is_error:
                        try:
                            reason = (await read_feed_body(resp, 16384, prefix=True)).decode("utf-8", errors="replace")
                        except FeedResourceError:
                            # 诊断正文不可信时仍必须尊重状态码及 Retry-After。
                            reason = ""
                        return _http_feed_failure(resp, reason, url)
                    content = await read_feed_body(resp, config.rss_feed_max_bytes)
                    check_feed_structure(content)
                    parsed = feedparser.parse(content)
                    if parsed.bozo:
                        logger.warning(f"RSS 格式异常: {url}")
                    return parsed
            raise FeedSyntaxError("FeedRedirectLimit")
    except FeedResourceError as exc:
        logger.warning(f"RSS 超出处理预算或编码无效：{exc}")
        return {"entries": [], "error": str(exc), "resource_limited": not isinstance(exc, FeedSyntaxError)}
    except httpx.HTTPStatusError as e:
        return _http_feed_failure(e.response, "", url)
    except httpx.RequestError as e:
        logger.error(f"网络请求异常: {type(e).__name__} on {url}")
    except Exception as e:
        logger.exception(f"解析非预期错误: {url}")
    return {"entries": [], "error": "Fetch failed"}


def _http_feed_failure(response, reason, url):
    logger.error(f"HTTP错误 {response.status_code}: {url}")
    reason = reason.casefold()
    rate_limited = response.status_code == 429 or any(
        term in reason for term in ("rate limit", "ratelimit", "too many requests", "too_many_requests")
    )
    retry_after = 0
    value = response.headers.get("Retry-After", "")
    try:
        retry_after = int(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            retry_after = int((when - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            pass
    return {"entries": [], "error": "HTTP error", "status_code": response.status_code,
            "rate_limited": rate_limited, "retry_after": max(0, min(retry_after, 86400))}


class rss_get():
    @staticmethod
    async def report_status(status_url, *, available, observed_at):
        """等待 Kuma 确认，失败由独立上报任务保留重试，不输出含 Token 的 URL。"""
        parts = urlsplit(status_url)
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                 if key not in {"status", "msg", "ping"}]
        query.extend([
            ("status", "up" if available else "down"),
            ("msg", f"Twitter {'上线' if available else '下线'}；采集检测时间 {observed_at.isoformat()} UTC"),
            ("ping", ""),
        ])
        url = urlunsplit(parts._replace(query=urlencode(query)))
        client = NetworkManager.get_client()
        response = await client.get(url, timeout=5)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ValueError("Uptime Kuma 未确认上报")

    async def send_qq_image(self, img_url: str, group_id: str, retry_count: int = 0):
        """附件最多尝试四次；失败告知用户，不让已发送的正文重复推送。"""
        for attempt in range(retry_count, 4):
            try:
                async with image_transfer_slot():
                    data, file_name = await download_image(img_url, NetworkManager.get_client())
                    try:
                        await send_group_message(get_bot(), group_id, file_image(data, file_name))
                    finally:
                        del data
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

        decision = delivery_decision(
            is_self_repost=if_is_self_trans, is_repost=if_is_trans,
            allow_self_reposts=if_need_self_trans, allow_reposts=if_need_user_trans,
        )
        if decision is DeliveryDecision.SEND:
            translation = None
            if if_need_trans and if_need_translate:
                translation = content.get("trans_text") or "（暂无翻译）"

            async with _msg_semaphore:
                await self.handle_markdown_send(
                    group_id=group_id,
                    content=content,
                    translation=translation,
                )
            return True
        return False

    @staticmethod
    async def handle_markdown_send(
        group_id: str, content: dict, translation: str | None = None,
    ):
        """正文发送失败由调用方重试；附件失败降级为带警告的正文成功。"""
        bot = get_bot()
        try:
            for message in article_messages(content, translation, config.model_name if translation else None):
                await send_group_message(bot, group_id, message)
        except Exception as exc:
            logger.error(f"发送群 {group_id} RSS 正文失败：{exc}")
            raise
        images = list(dict.fromkeys(content.get("images") or []))
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
        failures = []
        for host in hosts:
            if not host:
                continue
            data = await fetch_feed(f"{host.rstrip('/')}/{route.lstrip('/')}{userid}")
            valid = data.get("entries") or (data.get("version") and not data.get("bozo"))
            if valid and not data.get("error"):
                return data
            failures.append(data)
            logger.warning(f"用户 {userid} 的 RSS 源无有效条目，尝试下一个源")
        raise FeedUnavailable(
            rate_limited=any(item.get("rate_limited") or item.get("status_code") == 429 for item in failures),
            retry_after=max((item.get("retry_after", 0) for item in failures), default=0),
            # 明确的账号级错误优先，避免备用实例宕机导致连续失效账号误触发全局熔断。
            global_failure=bool(failures) and all(
                item.get("status_code") not in (400, 404, 410) and not item.get("resource_limited")
                for item in failures
            ),
        )

    async def handle_rss(self, userid: str, group_id_list: list, group_configs: dict = None):
        """兼容单账号入口：采集一次，再读取数据库快照投递。"""
        try:
            if await self.collect_rss(userid):
                await self.send_cached_rss(userid, group_id_list, group_configs)
        except FeedUnavailable:
            return

    async def collect_rss(self, userid: str, account: tuple | None = None) -> bool:
        """只采集和缓存，不依赖群订阅、不翻译或调用 QQ。"""
        if account is None:
            async with get_session() as session:
                user = await UserManager.get_Sign_by_student_id(session, userid)
                if not user:
                    logger.warning(f"用户 {userid} 不存在，跳过")
                    return False
                platform = await PlantformManager.get_Sign_by_student_id(session, user.Plantform)
                if platform is None:
                    logger.warning(f"用户 {userid} 的平台不存在，跳过")
                    return False
                account = (user.User_Name, platform.url, platform.name)
        username, route, platform_name = account
        data = await self._fetch_user_feed(userid, route, platform_name)
        if data is None:
            return False
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
            # 有效空窗口可以证明源已恢复，保留既有缓存等待后续有内容的响应。
            return not data.get("entries")
        await cache_entries(entries_info, username)
        serialized = json.dumps(entries_info, ensure_ascii=False, sort_keys=True, default=str)
        async with get_session() as session:
            snapshot = await session.get(RSSFeedCache, userid)
            values = dict(
                entries=serialized,
                digest=sha256(serialized.encode("utf-8")).hexdigest(),
                collected_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            if snapshot is None:
                session.add(RSSFeedCache(account_id=userid, **values))
            else:
                snapshot.entries = values["entries"]
                snapshot.digest = values["digest"]
                snapshot.collected_at = values["collected_at"]
            await session.commit()
        return True

    async def send_cached_rss(self, userid: str, group_id_list: list, group_configs: dict = None):
        """只投递最近一次有效 RSS 窗口，不重新抓取或扫描全部历史文章。"""
        if not group_id_list:
            return True
        async with get_session() as session:
            snapshot = await session.get(RSSFeedCache, userid)
            user = await UserManager.get_Sign_by_student_id(session, userid)
            if snapshot is None or user is None:
                return False
            platform = await PlantformManager.get_Sign_by_student_id(session, user.Plantform)
            if platform is None:
                return False
            username, need_trans = user.User_Name, int(platform.need_trans)
            # 恢复 feedparser 的字段别名（description/summary、enclosures/links 等）。
            entries_info = json.loads(snapshot.entries, object_hook=feedparser.FeedParserDict)
        groups = list(dict.fromkeys(map(str, group_id_list)))
        configs = group_configs or {}
        flags = {}
        content_tasks = {}

        async def load_content(entry, trueid):
            try:
                content = await get_text(trueid)
            except (ValueError, SyntaxError, TypeError, AttributeError, SQLAlchemyError) as exc:
                logger.warning(f"文章缓存不可用，将从 RSS 重建：{type(exc).__name__}")
                content = None
            translate = need_trans if any(
                _parse_group_config(configs.get(target))["if_need_translate"] for target in groups
            ) else 0
            if not content or (translate and not content.get("trans_text")):
                content = await Format().extract_content(entry, translate)
                content.update(username=username, id=trueid)
                await update_text(content)
            content["username"] = username
            return content

        async def content_for(entry, trueid):
            # 同一账号并行投递多群时，共用一份缓存读取/正文提取/翻译任务。
            if trueid not in content_tasks:
                content_tasks[trueid] = asyncio.create_task(load_content(entry, trueid))
            return await content_tasks[trueid]

        async def deliver_group(group):
            complete = True
            gc = _parse_group_config(configs.get(group))
            limit = gc["push_limit"]
            try:
                async with _delivery_lock(f"rss-group:{group}"), get_session() as session:
                    await DetailManager.initialize_subscription(
                        session, userid, group, entries_info, push_limit=limit,
                    )
            except Exception as exc:
                logger.error(f"初始化 {group} 对 {userid} 的订阅失败，将下次重试：{exc}")
                return False

            selected = entries_info[:limit] if limit else entries_info
            started_previous = False
            for entry, trueid in selected:
                record_id = f"{trueid}-{group}"
                skipped_id = DetailManager.skip_id(userid, group, trueid)
                try:
                    # 一篇的全部正文页和原图共用群锁，其他文章不能插入其中。
                    async with _delivery_lock(f"rss-group:{group}"):
                        async with get_session() as session:
                            existing = await DetailManager.get_existing_ids(session, [record_id, skipped_id])
                        if trueid not in flags and not existing:
                            flags[trueid] = (await if_self_trans(username, entry), await if_trans(entry))
                        is_self, is_forward = flags.get(trueid, (False, False))
                        decision = delivery_decision(
                            already_delivered=bool(existing),
                            is_self_repost=is_self, is_repost=is_forward,
                            allow_self_reposts=gc["if_need_self_trans"], allow_reposts=gc["if_need_trans"],
                        )
                        if decision is DeliveryDecision.ALREADY_DELIVERED:
                            continue
                        if decision is DeliveryDecision.FILTERED:
                            async with get_session() as session:
                                await DetailManager.create_signmsg(
                                    session, id=skipped_id, summary=entry.get("title"), updated=None,
                                )
                            continue
                        content = await content_for(entry, trueid)
                        if started_previous:
                            await asyncio.sleep(random.uniform(5, 15))
                        # 已开始发出的文章即使后续页或去重写入失败，也需要篇间等待。
                        started_previous = True
                        sent = await self.send_text(
                            group, content, need_trans, is_self, is_forward, configs.get(group),
                        )
                        async with get_session() as session:
                            await DetailManager.create_signmsg(
                                session, id=record_id if sent else skipped_id,
                                summary=content.get("text"), updated=datetime.now() if sent else None,
                            )
                except Exception as exc:
                    complete = False
                    logger.error(f"处理 {group} 对 {userid} 的文章 {trueid} 失败：{exc}")
            return complete

        return all(await asyncio.gather(*(deliver_group(group) for group in groups)))

    async def change_config(self):
        config.if_first_time_start = False

    async def get_signal(self):
        return str(config.if_first_time_start)
