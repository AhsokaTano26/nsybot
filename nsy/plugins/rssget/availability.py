"""采集链路状态与待发送通知；所有事务都在网络请求之外完成。"""

from datetime import datetime, timezone

from sqlalchemy import delete, select

from .models import RSSSourceNotice, RSSSourceStatus
from .state_machines import source_health_transition


class FeedUnavailable(Exception):
    def __init__(self, *, rate_limited=False, retry_after=0, global_failure=True):
        super().__init__("RSS 所有源均不可用")
        self.rate_limited = rate_limited
        self.retry_after = retry_after
        self.global_failure = global_failure


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_twitter_account(platform_name, route):
    return str(platform_name).casefold() in {"twitter", "x"} or "/twitter/" in str(route).casefold()


class SourceHealthManager:
    @staticmethod
    async def retry_at(session):
        state = await session.get(RSSSourceStatus, "twitter")
        return state.retry_at if state else None

    @staticmethod
    async def observe(session, available, *, notify, cooldown=0):
        now = utc_now()
        state = await session.get(RSSSourceStatus, "twitter")
        transition = source_health_transition(
            state.available if state is not None else None, available, now,
            notify=notify, cooldown=cooldown,
        )
        if state is None:
            state = RSSSourceStatus(source="twitter")
            session.add(state)
        state.available = transition.available
        state.observed_at = transition.observed_at
        state.retry_at = transition.retry_at
        if transition.enqueue_notice:
            # 每轮有效探测都给 Kuma 心跳；连续同状态的未发送记录合并，避免故障时积压。
            pending = await session.scalar(select(RSSSourceNotice).where(
                RSSSourceNotice.source == "twitter",
            ).order_by(RSSSourceNotice.id.desc()).limit(1))
            if pending is not None and pending.available == available:
                pending.observed_at = now
            else:
                session.add(RSSSourceNotice(source="twitter", available=available, observed_at=now))
        return transition.changed

    @staticmethod
    async def pending(session):
        rows = await session.scalars(select(RSSSourceNotice).order_by(RSSSourceNotice.id).limit(10))
        return [(row.id, row.available, row.observed_at) for row in rows]

    @staticmethod
    async def acknowledge(session, notice_id, observed_at):
        # 网络等待期间同状态记录可能已合并新观测，只确认实际发送的版本。
        await session.execute(delete(RSSSourceNotice).where(
            RSSSourceNotice.id == notice_id,
            RSSSourceNotice.observed_at == observed_at,
        ))
