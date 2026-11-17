"""群信息保留可复制 ID，并尽力取得发送人的昵称。"""

import asyncio
import tempfile
import unittest
from unittest.mock import patch

import nonebot
from nonebot.adapters.qq import GroupMessageCreateEvent
from nonebot.adapters.qq.models import GroupMemberInfo

from rss_test_support import load_rss_plugin


class RecordingInfoBot:
    def __init__(self, username=None, failure=None):
        self.username = username
        self.failure = failure
        self.messages = []
        self.requests = []

    async def send(self, event, message):
        self.messages.append(message.data["markdown"].content)

    async def get_group_member(self, *, group_openid, member_openid):
        self.requests.append((group_openid, member_openid))
        if self.failure:
            raise self.failure
        if (group_openid, member_openid) != ("test-group", "test-member"):
            raise ValueError("必须使用当前群和发送人的 OpenID")
        return GroupMemberInfo(member_openid=member_openid, username=self.username, bot=False)


class GroupInfoTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.TemporaryDirectory(prefix="nsybot-group-info-")
        load_rss_plugin(cls.root.name)
        plugin = nonebot.get_plugin("get_info") or nonebot.load_plugin("nsy.plugins.get_info")
        cls.plugin = plugin.module

    @classmethod
    def tearDownClass(cls):
        cls.root.cleanup()

    def event(self, username=None):
        return GroupMessageCreateEvent.model_validate({
            "id": "message", "timestamp": "2026-11-17T02:00:00+00:00", "content": "群信息",
            "group_id": "test-group", "group_openid": "test-group",
            "author": {"id": "author-id", "member_openid": "test-member", "username": username,
                       "bot": False, "member_role": "member"},
        })

    async def test_event_nickname_returns_both_ids_without_extra_request(self):
        bot = RecordingInfoBot()
        await self.plugin.reply_group_message_info(bot, self.event("消息昵称"))
        self.assertEqual(len(bot.messages), 1)
        self.assertIn("```\ntest-group\n```", bot.messages[0])
        self.assertIn("```\ntest-member\n```", bot.messages[0])
        self.assertIn("发送人昵称：消息昵称", bot.messages[0])
        self.assertEqual(bot.requests, [])

    async def test_missing_event_nickname_queries_current_group_member(self):
        bot = RecordingInfoBot(username="接口昵称")
        await self.plugin.reply_group_message_info(bot, self.event("  "))
        self.assertIn("发送人昵称：接口昵称", bot.messages[0])
        self.assertEqual(bot.requests, [("test-group", "test-member")])

    async def test_missing_or_failed_member_lookup_still_returns_ids(self):
        for bot in (RecordingInfoBot(), RecordingInfoBot(failure=RuntimeError("permission denied"))):
            with self.subTest(failure=bot.failure):
                await self.plugin.reply_group_message_info(bot, self.event())
                self.assertIn("发送人昵称：未知", bot.messages[0])
                self.assertIn("```\ntest-member\n```", bot.messages[0])

    async def test_slow_lookup_does_not_block_id_reply(self):
        bot = RecordingInfoBot()

        async def hanging_lookup(**kwargs):
            await asyncio.Event().wait()

        with patch.object(bot, "get_group_member", hanging_lookup), patch.object(self.plugin, "NICKNAME_TIMEOUT", 0.02, create=True):
            await asyncio.wait_for(self.plugin.reply_group_message_info(bot, self.event()), timeout=0.5)
        self.assertIn("发送人昵称：未知", bot.messages[0])

    async def test_nickname_remains_single_line_literal_text(self):
        bot = RecordingInfoBot()
        await self.plugin.reply_group_message_info(bot, self.event("  A*[B]\nC  "))
        self.assertIn(r"发送人昵称：A\*\[B\] C", bot.messages[0])


if __name__ == "__main__":
    unittest.main()
