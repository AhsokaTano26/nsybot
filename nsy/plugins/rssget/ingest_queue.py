"""入库补偿队列的短事务操作；正文处理和网络请求均在事务外执行。"""

from datetime import timedelta
from hashlib import sha256
import json

from sqlalchemy import select, update

from .availability import utc_now
from .models import RSSIngestQueue


class IngestQueueManager:
    @staticmethod
    async def stage(session, entries_info, username):
        ids = [article_id for _, article_id in entries_info]
        existing = {}
        for offset in range(0, len(ids), 400):
            rows = await session.scalars(select(RSSIngestQueue).where(RSSIngestQueue.id.in_(ids[offset:offset + 400])))
            existing.update((row.id, row) for row in rows)
        now = utc_now()
        for entry, article_id in entries_info:
            raw = json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str)
            version = sha256(json.dumps([username, raw], ensure_ascii=False).encode("utf-8")).hexdigest()
            pending = existing.get(article_id)
            if pending is None:
                pending = RSSIngestQueue(id=article_id, created_at=now)
                existing[article_id] = pending
                session.add(pending)
            elif pending.version == version:
                continue  # 同一响应不能重置失败次数或延后/提前既定重试。
            pending.username, pending.entry, pending.version = username, raw, version
            pending.attempts, pending.next_retry_at, pending.last_error = 0, now, None

    @staticmethod
    async def due(session, limit, ids=None):
        query = select(RSSIngestQueue).where(RSSIngestQueue.next_retry_at <= utc_now())
        if ids is not None:
            query = query.where(RSSIngestQueue.id.in_(ids))
        rows = await session.scalars(query.order_by(RSSIngestQueue.next_retry_at, RSSIngestQueue.id).limit(limit))
        return [dict(id=row.id, username=row.username, entry=row.entry, version=row.version,
                     attempts=row.attempts) for row in rows]

    @staticmethod
    async def failed(session, pending, error):
        attempts = pending["attempts"] + 1
        delay = min(3600, 30 * 2 ** min(attempts - 1, 7))
        await session.execute(update(RSSIngestQueue).where(
            RSSIngestQueue.id == pending["id"], RSSIngestQueue.version == pending["version"],
        ).values(attempts=attempts, next_retry_at=utc_now() + timedelta(seconds=delay), last_error=error[:64]))
