"""入库补偿队列的短事务操作；正文处理和网络请求均在事务外执行。"""

from hashlib import sha256
import json

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.orm.exc import StaleDataError

from .availability import utc_now
from .models import RSSIngestQueue
from .state_machines import ingest_retry


class IngestQueueManager:
    @staticmethod
    async def stage(session, entries_info, username):
        ids = [article_id for _, article_id in entries_info]
        existing = {}
        for offset in range(0, len(ids), 400):
            rows = await session.execute(select(RSSIngestQueue.id, RSSIngestQueue.version).where(
                RSSIngestQueue.id.in_(ids[offset:offset + 400])))
            existing.update((row.id, row.version) for row in rows)
        now = utc_now()
        for entry, article_id in entries_info:
            raw = json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str)
            version = sha256(json.dumps([username, raw], ensure_ascii=False).encode("utf-8")).hexdigest()
            if article_id in existing and existing[article_id] == version:
                continue  # 同一响应不能重置失败次数或延后/提前既定重试。
            values = dict(username=username, entry=raw, version=version,
                          attempts=0, next_retry_at=now, last_error=None)
            if article_id not in existing:
                session.add(RSSIngestQueue(id=article_id, created_at=now, **values))
            else:
                result = await session.execute(update(RSSIngestQueue).where(
                    RSSIngestQueue.id == article_id, RSSIngestQueue.version == existing[article_id],
                ).values(**values))
                if result.rowcount != 1:
                    raise StaleDataError("ingest queue changed during staging")
            existing[article_id] = version

    @staticmethod
    async def due(session, limit, ids=None, *, max_bytes=4 * 1024 * 1024, max_entry_bytes=256 * 1024):
        # 先取小型元数据和数据库内计算的字节数，避免先加载大 entry 才发现超额。
        query = select(RSSIngestQueue.id, RSSIngestQueue.username, RSSIngestQueue.version,
                       RSSIngestQueue.attempts, func.octet_length(RSSIngestQueue.entry).label("size"))\
            .where(RSSIngestQueue.next_retry_at <= utc_now())
        if ids is not None:
            query = query.where(RSSIngestQueue.id.in_(ids))
        heads = (await session.execute(query.order_by(RSSIngestQueue.next_retry_at, RSSIngestQueue.id).limit(limit))).all()
        selected, oversized, used = [], [], 0
        for row in heads:
            item = dict(id=row.id, username=row.username, version=row.version, attempts=row.attempts)
            if row.size > min(max_bytes, max_entry_bytes):
                oversized.append(dict(item, entry=None))
            elif used + row.size <= max_bytes:
                selected.append((row.id, row.version))
                used += row.size
        loaded = []
        if selected:
            rows = await session.scalars(select(RSSIngestQueue).where(
                tuple_(RSSIngestQueue.id, RSSIngestQueue.version).in_(selected),
            ).order_by(RSSIngestQueue.next_retry_at, RSSIngestQueue.id))
            loaded = [dict(id=row.id, username=row.username, entry=row.entry, version=row.version,
                           attempts=row.attempts) for row in rows]
        return oversized + loaded

    @staticmethod
    async def failed(session, pending, error):
        retry = ingest_retry(pending["attempts"], utc_now())
        await session.execute(update(RSSIngestQueue).where(
            RSSIngestQueue.id == pending["id"], RSSIngestQueue.version == pending["version"],
        ).values(attempts=retry.attempts, next_retry_at=retry.next_retry_at, last_error=error[:64]))
