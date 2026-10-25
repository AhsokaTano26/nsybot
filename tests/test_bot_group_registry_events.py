"""真实 QQ 群事件到独立群登记表的集成测试，不连接外部服务。"""

import tempfile
import unittest
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from nonebot.adapters.qq import Message
from nonebot.adapters.qq.event import (
    C2CMessageCreateEvent, GroupAddRobotEvent, GroupAtMessageCreateEvent,
    GroupDelRobotEvent, GroupMessageCreateEvent,
)
from nonebot.exception import FinishedException
from nonebot.rule import TrieRule
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rss_test_support import load_rss_plugin


def group_event(group="group-a", *, at=False, member="member", content="普通聊天"):
    event_type = GroupAtMessageCreateEvent if at else GroupMessageCreateEvent
    return event_type.model_validate({
        "id": "message", "timestamp": "2026-10-25T20:00:00+08:00", "content": content,
        "group_id": group, "group_openid": group,
        "author": {"id": member, "member_openid": member, "bot": False, "member_role": "member"},
    })


def robot_event(event_type, group="group-a", timestamp="2026-10-25T20:00:00+08:00"):
    return event_type.model_validate({
        "timestamp": timestamp, "group_openid": group, "op_member_openid": "operator",
    })


class BotGroupRegistryEventTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.TemporaryDirectory(prefix="nsybot-registry-events-")
        cls.rss = load_rss_plugin(cls.root.name)
        from nsy.plugins.rssget import models

        cls.models = models

    @classmethod
    def tearDownClass(cls):
        cls.root.cleanup()

    async def asyncSetUp(self):
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.root.name}/{uuid4().hex}.sqlite3")
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as connection:
            await connection.run_sync(self.models.Model.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        for patcher in (
            patch.object(self.rss, "get_session", self.sessions),
            patch.object(self.rss.config, "target_group_openid", None),
            patch.object(self.rss, "send_group_message", AsyncMock()),
            patch.object(self.rss, "_departed_groups", {}, create=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def stored_group(self, group="group-a"):
        async with self.sessions() as session:
            return await session.get(self.models.BotGroup, group)

    async def seed_membership_and_rss(self, group="group-a"):
        async with self.sessions.begin() as session:
            session.add(self.models.BotGroup(
                group_openid=group, joined_at=datetime(2026, 10, 25, 10),
                recorded_at=datetime(2026, 10, 25, 10), last_seen_at=datetime(2026, 10, 25, 11), source="join",
            ))
            session.add(self.models.Subscribe(id=f"account-{group}", username="account", group=group))
            session.add(self.models.Groupconfig(
                group_id=group, if_need_trans=True, if_need_self_trans=False, if_need_translate=True,
                if_need_photo_num_mention=False, if_need_merged_message=True,
            ))

    async def test_received_group_message_records_unsubscribed_and_ignored_group(self):
        observer = getattr(self.rss, "track_group_message", None)
        self.assertTrue(callable(observer), "所有群消息都应经过独立登记，不能仅依赖 RSS 订阅")
        with patch.object(self.rss.config, "ignored_group_openids", ["group-a"]):
            await observer(group_event())
        group = await self.stored_group()
        self.assertIsNotNone(group)
        self.assertIsNone(group.joined_at)
        self.assertEqual(group.source, "message")
        self.assertEqual(group.last_seen_at, datetime(2026, 10, 25, 12))
        self.assertEqual(await self.rss._get_joined_group_ids(), {"group-a"})
        async with self.sessions() as session:
            self.assertEqual(list(await session.scalars(select(self.models.Subscribe))), [])

    async def test_at_group_messages_are_also_registered(self):
        await self.rss.track_group_message(group_event("at-group", at=True))
        self.assertIsNotNone(await self.stored_group("at-group"))

    async def test_private_messages_do_not_create_group_rows(self):
        event = C2CMessageCreateEvent.model_validate({
            "id": "message", "timestamp": "2026-10-25T12:00:00+00:00", "content": "私聊",
            "author": {"id": "member", "user_openid": "member", "bot": False},
        })
        await self.rss.track_group_message(event)
        self.assertEqual(await self.rss._get_joined_group_ids(), set())

    async def test_join_records_real_event_time_and_messages_do_not_overwrite_it(self):
        event = robot_event(GroupAddRobotEvent)
        await self.rss.handle_group_added(event)
        first = await self.stored_group()
        await self.rss.handle_group_added(event)
        await self.rss.track_group_message(group_event())
        group = await self.stored_group()
        self.assertEqual(group.joined_at, datetime(2026, 10, 25, 12))
        self.assertEqual(group.recorded_at, first.recorded_at)
        self.assertEqual(group.source, "join")

    async def test_history_is_confirmed_without_inventing_join_time(self):
        recorded = datetime(2026, 1, 1)
        async with self.sessions.begin() as session:
            session.add(self.models.BotGroup(
                group_openid="group-a", recorded_at=recorded, joined_at=None,
                last_seen_at=None, source="history",
            ))
        await self.rss.track_group_message(group_event())
        group = await self.stored_group()
        self.assertEqual(group.recorded_at, recorded)
        self.assertIsNone(group.joined_at)
        self.assertEqual(group.source, "message")

    async def test_leave_deletes_registry_subscription_and_configuration_only_for_that_group(self):
        await self.seed_membership_and_rss()
        await self.seed_membership_and_rss("other-group")
        event = robot_event(GroupDelRobotEvent)
        await self.rss.handle_group_removed(event)
        await self.rss.handle_group_removed(event)
        self.assertEqual(await self.rss._get_joined_group_ids(), {"other-group"})
        async with self.sessions() as session:
            self.assertIsNone(await session.get(self.models.Groupconfig, "group-a"))
            groups = set(await session.scalars(select(self.models.Subscribe.group)))
            self.assertEqual(groups, {"other-group"})
        await self.rss.handle_group_added(robot_event(GroupAddRobotEvent, timestamp="2026-10-26T08:00:00+08:00"))
        self.assertEqual((await self.stored_group()).joined_at, datetime(2026, 10, 26))

    async def test_departure_cleanup_rolls_back_all_tables_if_one_delete_fails(self):
        await self.seed_membership_and_rss()
        async with self.engine.begin() as connection:
            await connection.execute(text("""
                CREATE TRIGGER reject_configuration_delete BEFORE DELETE ON Group_config
                WHEN OLD.group_id = 'group-a'
                BEGIN SELECT RAISE(FAIL, 'simulated delete failure'); END
            """))
        with self.assertRaises(SQLAlchemyError):
            await self.rss.handle_group_removed(robot_event(GroupDelRobotEvent))
        async with self.sessions() as session:
            self.assertIsNotNone(await session.get(self.models.BotGroup, "group-a"))
            self.assertIsNotNone(await session.get(self.models.Groupconfig, "group-a"))
            self.assertIsNotNone(await session.get(self.models.Subscribe, "account-group-a"))

    async def test_joined_group_lookup_does_not_use_subscription_rows(self):
        await self.rss.handle_group_added(robot_event(GroupAddRobotEvent, "registered-only"))
        async with self.sessions.begin() as session:
            session.add(self.models.Subscribe(id="untracked", username="account", group="subscription-only"))
        self.assertEqual(await self.rss._get_joined_group_ids(), {"registered-only"})

    async def test_delayed_message_or_join_does_not_recreate_a_departed_group(self):
        await self.seed_membership_and_rss()
        await self.rss.handle_group_removed(robot_event(GroupDelRobotEvent, timestamp="2026-10-25T20:01:00+08:00"))
        await self.rss.track_group_message(group_event())
        await self.rss.handle_group_added(robot_event(GroupAddRobotEvent))
        self.assertIsNone(await self.stored_group())

    async def test_delayed_departure_does_not_delete_newer_join_evidence(self):
        await self.rss.handle_group_added(robot_event(GroupAddRobotEvent, timestamp="2026-10-26T08:00:00+08:00"))
        await self.rss.handle_group_removed(robot_event(GroupDelRobotEvent))
        self.assertIsNotNone(await self.stored_group())

    async def test_message_confirmation_keeps_previous_membership_join_events_out(self):
        await self.seed_membership_and_rss()
        await self.rss.handle_group_removed(robot_event(GroupDelRobotEvent, timestamp="2026-10-25T20:01:00+08:00"))
        newer_message = group_event()
        newer_message.timestamp = "2026-10-25T20:02:00+08:00"
        await self.rss.track_group_message(newer_message)
        await self.rss.handle_group_added(robot_event(GroupAddRobotEvent))
        current = await self.stored_group()
        self.assertIsNone(current.joined_at, "上一次在群期间的入群事件不能作为本次入群时间")
        self.assertEqual(current.source, "message")
        self.assertEqual(current.last_seen_at, datetime(2026, 10, 25, 12, 2))

    async def test_unknown_registry_membership_is_reported_without_deleting_subscriptions(self):
        async with self.sessions.begin() as session:
            session.add(self.models.Subscribe(id="untracked", username="account", group="subscription-only"))
        report = await self.rss._cleanup_orphan_subscriptions()
        self.assertIn("subscription-only", report)
        async with self.sessions() as session:
            self.assertIsNotNone(await session.get(self.models.Subscribe, "untracked"))

    async def invoke_list(self, page=""):
        replies = []

        async def finish(message):
            replies.append(str(message))
            raise FinishedException

        with patch.object(self.rss.joined_groups_cmd, "finish", finish):
            with self.assertRaises(FinishedException):
                await self.rss.joined_groups_cmd.handlers[0].call(args=Message(page))
        return replies[-1]

    async def test_group_list_shows_real_join_times_and_unknown_historical_times(self):
        await self.rss.handle_group_added(robot_event(GroupAddRobotEvent, "joined"))
        async with self.sessions.begin() as session:
            session.add(self.models.BotGroup(
                group_openid="historical", recorded_at=datetime(2026, 1, 1), source="history",
            ))
        result = await self.invoke_list()
        self.assertIn("joined", result)
        self.assertIn("2026-10-25 20:00:00", result)
        self.assertIn("historical", result)
        self.assertIn("未知", result)
        self.assertIn("待确认", result)

    async def test_group_list_is_paginated_and_superuser_only(self):
        async with self.sessions.begin() as session:
            for index in range(12):
                session.add(self.models.BotGroup(
                    group_openid=f"group-{index:02d}", recorded_at=datetime(2026, 1, 1) + timedelta(days=index),
                    source="history",
                ))
        first, second = await self.invoke_list("1"), await self.invoke_list("2")
        first_ids = {f"group-{index:02d}" for index in range(12) if f"group-{index:02d}" in first}
        second_ids = {f"group-{index:02d}" for index in range(12) if f"group-{index:02d}" in second}
        self.assertEqual((len(first_ids), len(second_ids)), (10, 2))
        self.assertFalse(first_ids & second_ids)
        self.assertEqual(len(first_ids | second_ids), 12)
        matcher = self.rss.joined_groups_cmd
        for member, allowed in (("member", False), ("admin-member", True)):
            event = group_event(member=member, content="群列表")
            state = {}
            TrieRule.get_value(None, event, state)
            self.assertEqual(await matcher.rule(None, event, state), allowed)


if __name__ == "__main__":
    unittest.main()
