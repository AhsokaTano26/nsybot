"""当前群成员关系存储；只 flush，事务提交由事件处理方控制。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import case, delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from .models import BotGroup


def _utc_naive(value: datetime) -> datetime:
    """本模块约定无时区输入为 UTC，不沿用旧 RSS 记录的进程本地时间。"""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.replace(tzinfo=None)


class BotGroupManager:
    @classmethod
    async def _record(cls, session, group_openid: str, seen_at: datetime, *, joined: bool) -> BotGroup:
        stamp = _utc_naive(seen_at)
        values = {
            "group_openid": group_openid,
            "joined_at": stamp if joined else None,
            "recorded_at": datetime.now(timezone.utc).replace(tzinfo=None),
            "last_seen_at": stamp,
            "source": "join" if joined else "message",
        }
        changes = {
            "last_seen_at": case(
                (or_(BotGroup.last_seen_at.is_(None), BotGroup.last_seen_at < stamp), stamp),
                else_=BotGroup.last_seen_at,
            ),
            "source": "join" if joined else case(
                (BotGroup.source == "join", "join"), else_="message",
            ),
        }
        if joined:
            changes["joined_at"] = case(
                (or_(BotGroup.joined_at.is_(None), BotGroup.joined_at < stamp), stamp),
                else_=BotGroup.joined_at,
            )

        dialect = session.get_bind(mapper=BotGroup).dialect.name
        # SQLite（部署默认值）和 PostgreSQL 用单条原子 upsert，避免首次登记竞态。
        # 其他方言只回滚插入的 savepoint，再原子更新；不回滚调用方的事务。
        dialect_insert = {"sqlite": sqlite_insert, "postgresql": postgresql_insert}.get(dialect)
        if dialect_insert is not None:
            statement = dialect_insert(BotGroup).values(**values)
            await session.execute(statement.on_conflict_do_update(
                index_elements=[BotGroup.group_openid], set_=changes,
            ))
        else:
            try:
                async with session.begin_nested():
                    await session.execute(insert(BotGroup).values(**values))
            except IntegrityError:
                if await session.get(BotGroup, group_openid) is None:
                    raise
            await session.execute(update(BotGroup).where(
                BotGroup.group_openid == group_openid,
            ).values(**changes).execution_options(synchronize_session=False))
        await session.flush()
        return (await session.scalars(select(BotGroup).where(
            BotGroup.group_openid == group_openid,
        ).execution_options(populate_existing=True))).one()

    @classmethod
    async def record_join(cls, session, group_openid: str, joined_at: datetime) -> BotGroup:
        """保存实际入群事件；较早的重复事件不能覆盖较新的入群证据。"""
        return await cls._record(session, group_openid, joined_at, joined=True)

    @classmethod
    async def observe(cls, session, group_openid: str, seen_at: datetime | None = None) -> BotGroup:
        """群消息确认当前仍在群中，但不能推断原始入群时间。"""
        return await cls._record(
            session, group_openid,
            seen_at if seen_at is not None else datetime.now(timezone.utc),
            joined=False,
        )

    @classmethod
    async def remove(cls, session, group_openid: str) -> bool:
        result = await session.execute(delete(BotGroup).where(BotGroup.group_openid == group_openid))
        await session.flush()
        return bool(result.rowcount)

    @classmethod
    async def ids(cls, session) -> set[str]:
        return set(await session.scalars(select(BotGroup.group_openid)))

    @classmethod
    async def page(cls, session, page: int = 1, page_size: int = 10) -> tuple[int, list[BotGroup]]:
        total = await session.scalar(select(func.count()).select_from(BotGroup))
        rows = await session.scalars(select(BotGroup).order_by(BotGroup.group_openid).offset(
            (page - 1) * page_size,
        ).limit(page_size))
        return total, list(rows)
