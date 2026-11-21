import ast
import asyncio
import json
from time import monotonic

import feedparser

from nonebot.log import logger
from nonebot import get_plugin_config
from nonebot_plugin_orm import get_session
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError

from .models import Content, ImageSync, RSSIngestQueue
from .models_method import ContentManager
from .ingest_queue import IngestQueueManager
from .config import Config
from .state_machines import WriteOutcome

_ingest_lock = asyncio.Lock()
_stage_lock = asyncio.Lock()
config = get_plugin_config(Config)


async def update_text(dic, *, pending_version=None):
    """旧入口保留 bool 契约；业务工作器使用明确的 WriteOutcome。"""
    return bool(await write_content(dic, pending_version=pending_version))


async def write_content(dic, *, pending_version=None):
    """缓存尽力写入；缓存失败不阻断当前原文推送。"""
    images = list(dict.fromkeys(dic.get("images") or []))
    values = {key: dic.get(key) for key in (
        "title", "time", "link", "text", "trans_text", "username",
    )}
    values.update(image_num=str(len(images)), images=str(images) if images else None)
    for attempt in range(2):
        try:
            async with get_session() as session:
                if pending_version is not None:
                    # 先按版本确认并取得写锁；后续任一写入失败会连同确认一起回滚。
                    claimed = await session.execute(delete(RSSIngestQueue).where(
                        RSSIngestQueue.id == dic["id"], RSSIngestQueue.version == pending_version,
                    ))
                    if not claimed.rowcount:
                        return WriteOutcome.SUPERSEDED
                existing = await ContentManager.get_Sign_by_student_id(session, dic["id"])
                if existing is None:
                    session.add(Content(id=dic["id"], **values))
                else:
                    for key, value in values.items():
                        if key == "trans_text" and value is None and existing.trans_text:
                            continue
                        setattr(existing, key, value)
                # 先写 Content，再登记索引；两者原子提交，翻译更新不会产生新序号。
                await session.flush()
                if images and await session.scalar(select(ImageSync.seq).where(ImageSync.content_id == dic["id"])) is None:
                    session.add(ImageSync(content_id=dic["id"]))
                await session.commit()
            return WriteOutcome.COMMITTED
        except IntegrityError:
            # 并发文章缓存插入冲突，关闭回滚会话后重读并更新。
            if attempt:
                logger.warning("文章缓存并发写入失败，当前仍将发送原文")
        except SQLAlchemyError as exc:
            logger.warning(f"文章缓存写入失败，当前仍将发送原文：{type(exc).__name__}")
            return WriteOutcome.RETRY_PENDING
    return WriteOutcome.RETRY_PENDING


async def get_text(id) -> dict[str, str]:
    async with (get_session() as db_session):
        dic = {}
        msg = await ContentManager.get_Sign_by_student_id(db_session, id)
        if msg is None:
            return None
        image_num = msg.image_num
        id = msg.id
        username = msg.username
        title = msg.title
        time = msg.time
        link = msg.link
        text = msg.text
        trans_text = msg.trans_text

        dic["id"] = id
        dic["title"] = title
        dic["time"] = time
        dic["link"] = link
        dic["text"] = text
        dic["trans_text"] = trans_text
        dic["username"] = username
        dic["image_num"] = image_num
        if int(image_num) == 0:
            dic["images"] = None
            logger.info(f"成功获取对于 {username} 的 {id} 推文")
            return dic
        else:
            images = ast.literal_eval(msg.images)
            if not isinstance(images, list) or not all(isinstance(url, str) for url in images):
                raise ValueError("文章缓存的图片列表格式无效")
            dic["images"] = images
            logger.info(f"成功获取对于 {username} 的 {id} 推文")
            return dic


async def cache_entries(entries_info, username: str) -> None:
    """批量检查已缓存条目；不重复读取正文，翻译留给实际推送。"""
    # 新响应先落队列，不能在旧补偿任务后面等待到原始数据仍只留在内存。
    async with _stage_lock:
        missing_ids = await _stage_entries(entries_info, username)
    if missing_ids:
        async with _ingest_lock:
            for offset in range(0, len(missing_ids), 400):
                ids = missing_ids[offset:offset + 400]
                await _retry_pending_entries(limit=len(ids), ids=ids)


async def _stage_entries(entries_info, username):
    cached_ids = set()
    ids = list(dict.fromkeys(article_id for _, article_id in entries_info))
    try:
        async with get_session() as session:
            for offset in range(0, len(ids), 400):
                rows = await session.execute(select(Content.id, Content.image_num, Content.images).where(
                    Content.id.in_(ids[offset:offset + 400]),
                ))
                for article_id, image_num, raw_images in rows:
                    try:
                        if int(image_num) != 0:
                            images = ast.literal_eval(raw_images)
                            if not isinstance(images, list) or not all(isinstance(url, str) for url in images):
                                continue
                        cached_ids.add(article_id)
                    except (ValueError, SyntaxError, TypeError):
                        pass
    except SQLAlchemyError as exc:
        logger.error(f"检查文章缓存失败，尚未接受本轮条目：{type(exc).__name__}")
        raise

    missing = [(entry, article_id) for entry, article_id in entries_info if article_id not in cached_ids]
    if not missing:
        return []
    # 必须先持久化再格式化/入库；队列无法提交时明确失败，不更新账号快照。
    for attempt in range(3):
        try:
            async with get_session() as session, session.begin():
                await IngestQueueManager.stage(session, missing, username)
            break
        except (IntegrityError, StaleDataError):
            if attempt == 2:
                raise
    return [article_id for _, article_id in missing]


async def retry_pending_entries(limit=100):
    """不依赖 RSS 窗口或 QQ，按到期时间补写已持久化的原始条目。"""
    async with _ingest_lock:
        await _retry_pending_entries(limit=limit)


async def _retry_pending_entries(*, limit, ids=None):
    from .format_json import Format

    async with get_session() as session:
        pending = await IngestQueueManager.due(session, limit, ids,
            max_bytes=config.rss_ingest_retry_max_bytes, max_entry_bytes=config.rss_entry_max_bytes)
    started = monotonic()
    for index, item in enumerate(pending):
        if index and monotonic() - started >= config.rss_ingest_retry_max_seconds:
            break
        try:
            if item["entry"] is None:
                raise ValueError("EntryTooLarge")
            entry = json.loads(item["entry"], object_hook=feedparser.FeedParserDict)
            content = await Format().extract_content(entry, 0)
            content.update(id=item["id"], username=item["username"])
            outcome = await write_content(content, pending_version=item["version"])
            if outcome.success:
                continue
            error = "DatabaseWriteError"
        except Exception as exc:
            error = "EntryTooLarge" if item["entry"] is None else type(exc).__name__
        async with get_session() as session, session.begin():
            await IngestQueueManager.failed(session, item, error)
        logger.warning(f"文章 {item['id']} 入库失败，保留补偿队列：{error}")


async def cache_feed(entries, username: str) -> None:
    """手动查询同样复用已取得的响应，不发起额外 RSS 请求。"""
    from .get_id import get_id

    entries_info, seen = [], set()
    for entry in entries:
        try:
            article_id = await get_id(entry)
        except (ValueError, TypeError, AttributeError):
            continue
        if article_id not in seen:
            entries_info.append((entry, article_id))
            seen.add(article_id)
    await cache_entries(entries_info, username)
