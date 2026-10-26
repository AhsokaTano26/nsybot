"""生日插件的日期、订阅隔离、持久化提醒及命令权限回归测试。"""

import tempfile
import unittest
import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import nonebot
from nonebot.adapters.qq import GroupMessageCreateEvent, Message
from nonebot.adapters.qq.bot import _check_reply
from nonebot.exception import FinishedException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


TEST_ROOT = tempfile.TemporaryDirectory(prefix="nsybot-birthday-tests-")
nonebot.init(
    driver="~fastapi",
    sqlalchemy_database_url="sqlite+aiosqlite:///:memory:",
    localstore_data_dir=Path(TEST_ROOT.name) / "data",
    localstore_cache_dir=Path(TEST_ROOT.name) / "cache",
    localstore_config_dir=Path(TEST_ROOT.name) / "config",
    log_level="ERROR",
)
PLUGIN = nonebot.load_plugin("nsy.plugins.birthday")


def load_modules():
    if PLUGIN is None:
        raise AssertionError("生日插件应能独立加载")
    from nsy.plugins.birthday import commands, core, models, service, store

    return commands, core, models, service, store


class CalendarTests(unittest.TestCase):
    def setUp(self):
        _, self.core, _, _, _ = load_modules()

    def test_month_day_validation_includes_leap_day(self):
        for value in ("01-01", "02-29", "12-31"):
            self.core.validate_date(value)
        for value in ("02-30", "04-31", "1-1", "00-12", "13-01", "０１-０１", "٠١-٠١"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.core.validate_date(value)

    def test_tomorrow_uses_shanghai_date_instead_of_host_timezone(self):
        now = datetime(2026, 12, 31, 16, 30, tzinfo=timezone.utc)
        self.assertEqual(self.core.tomorrow_in_shanghai(now), date(2027, 1, 2))

    def test_year_and_leap_day_boundaries(self):
        for now, expected in (
            (datetime(2026, 12, 31, 15, tzinfo=timezone.utc), date(2027, 1, 1)),
            (datetime(2028, 2, 28, 15, tzinfo=timezone.utc), date(2028, 2, 29)),
            (datetime(2027, 2, 28, 15, tzinfo=timezone.utc), date(2027, 3, 1)),
        ):
            with self.subTest(now=now):
                self.assertEqual(self.core.tomorrow_in_shanghai(now), expected)

    def test_all_three_reference_name_formats(self):
        expected = (
            "测试群🎉@爱音&灯生日快乐🎉",
            "测试群(@爱音&灯生日快乐!)",
            "测试群(@爱音&灯生日快乐🎂)",
        )
        for style, name in enumerate(expected, 1):
            self.assertEqual(
                self.core.birthday_name("测试群", ["爱音", "灯"], style), name
            )

    def test_long_name_is_bounded_without_losing_the_group_name(self):
        result = self.core.birthday_name("测试群", ["很长的名字" * 10] * 8, 1)
        self.assertTrue(result.startswith("测试群"))
        self.assertLessEqual(len(result), 60)
        self.assertIn("等8人", result)
        with self.assertRaises(ValueError):
            self.core.validate_group_name("长" * 60)

    def test_scheduler_runs_at_23_shanghai_even_in_utc(self):
        from nsy.plugins.birthday import scheduler

        trigger = scheduler.get_job("birthday:remind").trigger
        next_fire = trigger.get_next_fire_time(
            None, datetime(2026, 12, 31, 14, 59, tzinfo=timezone.utc)
        )
        self.assertEqual(
            next_fire.astimezone(timezone.utc),
            datetime(2026, 12, 31, 15, tzinfo=timezone.utc),
        )

    def test_large_birthday_list_keeps_complete_nickname_after_qq_truncation(self):
        from nsy.qq_utils import truncate_markdown

        reminder = self.core.Reminder(
            group_id="group-a", target_date=date(2027, 1, 1),
            names=tuple("很长的名字" * 12 for _ in range(100)),
            suggested_name="测试群🎉@名字等100人生日快乐🎉", previous_name="测试群",
        )
        message = truncate_markdown(reminder.render())
        self.assertIn("```\n测试群🎉@名字等100人生日快乐🎉\n```", message)
        self.assertLessEqual(len(message), 3500)


class BirthdayIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.commands, self.core, self.models, self.service, self.store = load_modules()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(self.models.Model.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.sent = []

    async def asyncTearDown(self):
        if hasattr(self, "engine"):
            await self.engine.dispose()

    async def command(self, text, group_id="group-a", admin=True):
        async with self.sessions.begin() as session:
            return await self.commands.execute_command(
                self.store.BirthdayStore(session), text, group_id, admin
            )

    async def send(self, group_id, message):
        self.sent.append((group_id, message))

    async def seed(self):
        await self.command("增加标签 MyGO")
        await self.command("增加标签 Roselia")
        await self.command("增加成员 爱音 01-01")
        await self.command("增加成员 友希那 01-01")
        await self.command("关联标签 爱音 MyGO")
        await self.command("关联标签 友希那 Roselia")
        await self.command("群名 测试群")
        await self.command("订阅 MyGO 1")

    async def run_reminders(self, day=31, sender=None):
        return await self.service.run_reminders(
            sender or self.send,
            self.sessions,
            datetime(2026, 12, day, 15, tzinfo=timezone.utc),
        )

    async def quote_event(self, content="**生日快乐** 🎂\n[祝福](https://example.com)", *,
                          member="admin-member", attachments=None, quoted=True):
        event = GroupMessageCreateEvent.model_validate({
            "id": "command-message", "timestamp": "2026-10-26T23:00:00+08:00",
            "content": "发送生日语录", "group_id": "group-a", "group_openid": "group-a",
            "author": {"id": member, "member_openid": member, "bot": False, "member_role": "admin"},
            "message_type": 103 if quoted else 0,
            "message_scene": {"ext": ["ref_msg_idx=quoted-index"], "source": "group"},
            "msg_elements": [{
                "content": content, "message_type": 0, "msg_idx": "quoted-index",
                "attachments": attachments,
            }] if quoted else None,
        })
        await _check_reply(None, event)
        return event

    async def quote_command(self, event, bot=None, args=""):
        plugin = PLUGIN.module
        handler = getattr(plugin, "handle_birthday_quote", None)
        self.assertTrue(callable(handler), "缺少发送生日语录命令")
        responses = []

        async def finish(message):
            responses.append(message.data["markdown"].content)
            raise FinishedException

        from nsy import qq_utils

        with (
            patch.object(plugin, "get_session", self.sessions),
            patch.object(nonebot.get_driver().config, "superusers", {"admin-member"}),
            patch.object(qq_utils, "active_message_limiter", qq_utils.ActiveMessageLimiter(0, 0)),
            patch.object(plugin.birthday_quote_cmd, "finish", finish),
        ):
            with self.assertRaises(FinishedException):
                await handler(bot or QuoteBot(), event, Message(args))
        return "\n".join(responses)

    async def add_quote_target(self, group_id):
        await self.command("群名 目标群", group_id=group_id)
        await self.command("订阅 MyGO 1", group_id=group_id)

    async def test_quote_targets_only_active_subscriptions_once_and_excludes_source(self):
        await self.seed()
        await self.add_quote_target("group-b")
        await self.command("订阅 Roselia 2", group_id="group-b")
        await self.add_quote_target("group-c")
        await self.command("群名 尚未订阅", group_id="group-unused")
        await self.add_quote_target("group-unsubscribed")
        await self.command("退订 MyGO", group_id="group-unsubscribed")
        bot = QuoteBot()
        response = await self.quote_command(await self.quote_event(), bot)
        self.assertEqual([group for group, _ in bot.sent], ["group-b", "group-c"])
        self.assertEqual([msg.data["markdown"].content for _, msg in bot.sent], [
            "**生日快乐** 🎂\n[祝福](https://example.com)",
            "**生日快乐** 🎂\n[祝福](https://example.com)",
        ])
        self.assertIn("成功 2 群", response)
        async with self.sessions() as session:
            groups = await self.store.BirthdayStore(session).list_groups()
            self.assertTrue(all(group.last_suggested_name == group.group_name for group in groups))

    async def test_quote_rejects_member_even_when_qq_role_is_admin(self):
        await self.seed()
        await self.add_quote_target("group-b")
        bot = QuoteBot()
        response = await self.quote_command(await self.quote_event(member="member"), bot)
        self.assertIn("超级管理员", response)
        self.assertEqual(bot.sent, [])

    async def test_quote_requires_group_and_reference_and_no_extra_arguments(self):
        from nonebot.adapters.qq.event import C2CMessageCreateEvent

        private_event = C2CMessageCreateEvent.model_validate({
            "id": "private-message", "timestamp": "2026-10-26T23:00:00+08:00",
            "content": "发送生日语录", "author": {"id": "admin-member", "user_openid": "admin-member"},
        })
        for event, args, expected in (
            (private_event, "", "群"),
            (await self.quote_event(quoted=False), "", "引用"),
            (await self.quote_event(), "额外正文", "用法"),
            (await self.quote_event(content=" \n "), "", "为空"),
            (await self.quote_event(attachments=[{"content_type": "image/png"}]), "", "附件地址缺失"),
        ):
            with self.subTest(expected=expected):
                bot = QuoteBot()
                self.assertIn(expected, await self.quote_command(event, bot, args))
                self.assertEqual(bot.sent, [])

    async def test_quote_sends_each_image_after_markdown_without_losing_attachments(self):
        await self.seed()
        await self.add_quote_target("group-b")
        await self.add_quote_target("group-c")
        event = await self.quote_event(attachments=[
            {"content_type": "image/png", "url": "https://example.com/1.png"},
            {"content_type": "image/jpeg", "url": "https://example.com/2.jpg"},
        ])
        bot = QuoteBot()
        # Only network I/O is replaced; native QQ reply parsing and all sends remain real.
        with patch("nsy.plugins.birthday.quotes.download_image", AsyncMock(side_effect=[
            (b"first-image", "1.png"), (b"second-image", "2.jpg"),
        ])):
            response = await self.quote_command(event, bot)
        for group in ("group-b", "group-c"):
            messages = [message for target, message in bot.sent if target == group]
            self.assertEqual([message.type for message in messages], ["markdown", "file_image", "file_image"])
            self.assertEqual([message.data["content"] for message in messages[1:]], [b"first-image", b"second-image"])
        self.assertIn("成功 2 群", response)

    async def test_quote_supports_image_only_and_other_media(self):
        await self.seed()
        await self.add_quote_target("group-b")
        bot = QuoteBot()
        with patch("nsy.plugins.birthday.quotes.download_image", AsyncMock(return_value=(b"image", "quote.png"))):
            await self.quote_command(await self.quote_event(content="", attachments=[
                {"content_type": "image/png", "url": "https://example.com/quote.png"},
            ]), bot)
        self.assertEqual([message.type for _, message in bot.sent], ["file_image"])
        bot.sent.clear()
        await self.quote_command(await self.quote_event(content="", attachments=[
            {"content_type": "audio/mpeg", "url": "https://example.com/audio.mp3"},
            {"content_type": "video/mp4", "url": "https://example.com/video.mp4"},
            {"content_type": "application/pdf", "url": "https://example.com/quote.pdf"},
        ]), bot)
        self.assertEqual([message.type for _, message in bot.sent], ["audio", "video", "file"])

    async def test_quote_long_text_is_sent_completely(self):
        await self.seed()
        await self.add_quote_target("group-b")
        content = "生日祝福\n\n" * 1000
        bot = QuoteBot()
        await self.quote_command(await self.quote_event(content), bot)
        pages = [message.data["markdown"].content for _, message in bot.sent]
        self.assertEqual("".join(pages), content)
        self.assertTrue(all(len(page) <= 3500 for page in pages))

    async def test_quote_pagination_keeps_markdown_blocks_intact(self):
        await self.seed()
        await self.add_quote_target("group-b")
        emphasis = "**" + "祝" * 1700 + "**\n\n"
        link = "[祝福](https://example.com)\n\n"
        code = "```\n" + "福" * 1800 + "\n```\n\n"
        bot = QuoteBot()
        await self.quote_command(await self.quote_event(emphasis + link + code), bot)
        self.assertEqual([message.data["markdown"].content for _, message in bot.sent], [
            emphasis + link, code,
        ])

    async def test_quote_oversized_markdown_block_is_rejected_before_any_send(self):
        await self.seed()
        await self.add_quote_target("group-b")
        for content in (
            "```\n" + "祝福\n" * 1500 + "```",
            "**" + "祝福" * 2000 + "**",
            "[" + "祝福" * 2000 + "](https://example.com)",
            "[生日祝福][b]\n\n" + "段落\n\n" * 1000 + "[b]: https://example.com",
        ):
            with self.subTest(content=content[:10]):
                bot = QuoteBot()
                response = await self.quote_command(await self.quote_event(content), bot)
                self.assertIn("过长", response)
                self.assertEqual(bot.sent, [])

    async def test_quote_failure_does_not_stop_later_groups_or_count_partial_success(self):
        await self.seed()
        for group in ("group-b", "group-c", "group-d"):
            await self.add_quote_target(group)
        bot = QuoteBot(failures={("group-b", "markdown"), ("group-c", "file_image")})
        event = await self.quote_event(attachments=[
            {"content_type": "image/png", "url": "https://example.com/quote.png"},
        ])
        with patch("nsy.plugins.birthday.quotes.download_image", AsyncMock(return_value=(b"image", "quote.png"))):
            response = await self.quote_command(event, bot)
        self.assertEqual([(group, message.type) for group, message in bot.sent], [
            ("group-c", "markdown"), ("group-d", "markdown"), ("group-d", "file_image"),
        ])
        self.assertIn("成功 1 群", response)
        self.assertIn("失败 2 群", response)

    async def test_quote_download_failure_aborts_before_broadcast(self):
        await self.seed()
        await self.add_quote_target("group-b")
        bot = QuoteBot()
        event = await self.quote_event(attachments=[
            {"content_type": "image/png", "url": "https://example.com/quote.png"},
        ])
        with patch("nsy.plugins.birthday.quotes.download_image", AsyncMock(side_effect=RuntimeError("download failed"))):
            response = await self.quote_command(event, bot)
        self.assertIn("失败", response)
        self.assertEqual(bot.sent, [])

    async def test_quote_no_other_subscribed_groups_reports_no_targets(self):
        await self.seed()
        bot = QuoteBot()
        response = await self.quote_command(await self.quote_event(), bot)
        self.assertIn("没有", response)
        self.assertEqual(bot.sent, [])

    async def test_quote_source_group_does_not_need_a_birthday_subscription(self):
        await self.command("增加标签 MyGO")
        await self.add_quote_target("group-b")
        bot = QuoteBot()
        response = await self.quote_command(await self.quote_event(), bot)
        self.assertEqual([group for group, _ in bot.sent], ["group-b"])
        self.assertIn("成功 1 群", response)

    async def test_quote_command_is_registered_without_birthday_prefix(self):
        from nonebot.rule import TrieRule

        matcher = getattr(PLUGIN.module, "birthday_quote_cmd", None)
        self.assertIsNotNone(matcher, "应注册独立命令「发送生日语录」")
        event = await self.quote_event()
        state = {}
        with patch.object(nonebot.get_driver().config, "command_start", {""}):
            TrieRule.get_value(None, event, state)
            self.assertTrue(await matcher.rule(None, event, state))

    async def test_reminder_contains_only_subscribed_birthdays_and_copyable_name(self):
        await self.seed()
        self.assertEqual(await self.run_reminders(), (1, 0))
        group_id, message = self.sent[0]
        self.assertEqual(group_id, "group-a")
        self.assertIn("2027-01-01", message)
        self.assertIn("```\n测试群🎉@爱音生日快乐🎉\n```", message)
        self.assertNotIn("友希那", message)

    async def test_successful_delivery_is_persisted_and_not_sent_again(self):
        await self.seed()
        await self.run_reminders()
        self.assertEqual(await self.run_reminders(), (0, 0))
        self.assertEqual(len(self.sent), 1)

    async def test_restore_is_sent_once_after_birthday(self):
        await self.seed()
        await self.run_reminders()
        self.sent.clear()
        now = datetime(2027, 1, 1, 15, tzinfo=timezone.utc)
        result = await self.service.run_reminders(self.send, self.sessions, now)
        self.assertEqual(result, (1, 0))
        self.assertIn("恢复", self.sent[0][1])
        self.assertIn("```\n测试群\n```", self.sent[0][1])
        self.assertEqual(
            await self.service.run_reminders(self.send, self.sessions, now), (0, 0)
        )

    async def test_other_groups_birthdays_do_not_prevent_restore(self):
        await self.seed()
        await self.run_reminders()
        await self.command("增加成员 莉莎 01-02")
        await self.command("关联标签 莉莎 Roselia")
        await self.command("群名 另一群", group_id="group-b")
        await self.command("订阅 Roselia 2", group_id="group-b")
        self.sent.clear()
        await self.service.run_reminders(
            self.send, self.sessions, datetime(2027, 1, 1, 15, tzinfo=timezone.utc)
        )
        messages = dict(self.sent)
        self.assertIn("```\n测试群\n```", messages["group-a"])
        self.assertIn("另一群(@莉莎生日快乐!)", messages["group-b"])
        self.assertNotIn("莉莎", messages["group-a"])

    async def test_send_failure_does_not_mark_delivered_or_stop_other_groups(self):
        await self.seed()
        await self.command("群名 另一群", group_id="group-b")
        await self.command("订阅 MyGO 3", group_id="group-b")

        async def sender(group_id, message):
            if group_id == "group-a":
                raise RuntimeError("QQ temporarily unavailable")
            await self.send(group_id, message)

        self.assertEqual(await self.run_reminders(sender=sender), (1, 1))
        self.assertEqual(await self.run_reminders(), (1, 0))
        self.assertEqual([group for group, _ in self.sent], ["group-b", "group-a"])

    async def test_ordinary_days_do_not_emit_restore_spam(self):
        await self.seed()
        self.assertEqual(await self.run_reminders(day=30), (0, 0))
        self.assertEqual(self.sent, [])

    async def test_multiple_tags_do_not_duplicate_the_same_member(self):
        await self.seed()
        await self.command("关联标签 爱音 Roselia")
        await self.command("订阅 Roselia 1")
        await self.run_reminders()
        self.assertIn("测试群🎉@友希那&爱音生日快乐🎉", self.sent[0][1])

    async def test_unsubscribe_last_tag_still_allows_restore(self):
        await self.seed()
        await self.run_reminders()
        await self.command("退订 MyGO")
        self.sent.clear()
        await self.service.run_reminders(
            self.send, self.sessions, datetime(2027, 1, 1, 15, tzinfo=timezone.utc)
        )
        self.assertIn("```\n测试群\n```", self.sent[0][1])

    async def test_preview_does_not_change_delivery_state(self):
        await self.seed()
        async with self.sessions() as session:
            preview = await self.service.preview(
                self.store.BirthdayStore(session), "group-a", date(2027, 1, 1)
            )
        self.assertIn("测试群🎉@爱音生日快乐🎉", preview)
        self.assertEqual(await self.run_reminders(), (1, 0))

    async def test_global_mutations_require_superuser(self):
        for text in ("增加成员 测试 01-01", "增加标签 MyGO", "导入预设"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                await self.command(text, admin=False)

    async def test_current_group_configuration_is_open_to_members(self):
        await self.command("增加标签 MyGO")
        await self.command("群名 测试群", admin=False)
        await self.command("订阅 MyGO 1", admin=False)
        status = await self.command("状态", admin=False)
        self.assertIn("测试群", status)
        self.assertIn("MyGO", status)

    async def test_group_commands_reject_private_messages(self):
        for text in ("群名 测试群", "订阅 MyGO 1", "退订 MyGO", "状态", "预览"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                await self.command(text, group_id=None)

    async def test_subscription_requires_manual_base_name_and_existing_tag(self):
        await self.command("增加标签 MyGO")
        with self.assertRaises(ValueError):
            await self.command("订阅 MyGO 1")
        await self.command("群名 测试群")
        with self.assertRaises(ValueError):
            await self.command("订阅 不存在 1")
        with self.assertRaises(ValueError):
            await self.command("订阅 MyGO 4")

    async def test_repeated_subscription_keeps_original_base_name(self):
        await self.seed()
        await self.command("订阅 MyGO 2")
        status = await self.command("状态")
        self.assertIn("测试群", status)
        await self.run_reminders()
        self.assertIn("测试群(@爱音生日快乐!)", self.sent[0][1])

    async def test_batch_import_validates_all_entries_before_writing(self):
        with self.assertRaises(ValueError):
            await self.command("批量导入 爱音 01-01, 灯 02-30")
        self.assertNotIn("爱音", await self.command("成员"))
        await self.command("批量导入 爱音 01-01, 灯 02-29")
        self.assertIn("02-29 灯", await self.command("成员 2"))
        await self.command("批量导入 爱音 01-02")
        self.assertIn("01-02 爱音", await self.command("成员 1"))

    async def test_delete_tag_and_member_remove_associations(self):
        await self.seed()
        await self.command("删除标签 MyGO")
        self.assertEqual(await self.run_reminders(), (0, 0))
        await self.command("删除成员 友希那")
        self.assertNotIn("友希那", await self.command("成员"))

    async def test_group_departure_removes_config_and_reminders(self):
        await self.seed()
        async with self.sessions.begin() as session:
            await self.store.BirthdayStore(session).delete_group("group-a")
        self.assertEqual(await self.run_reminders(), (0, 0))

    async def test_preset_import_is_idempotent_and_includes_tags(self):
        await self.command("导入预设")
        first = await self.command("成员")
        self.assertIn("09-08 千早爱音", first)
        await self.command("修改成员 千早爱音 01-01")
        edited = await self.command("成员")
        await self.command("导入预设")
        self.assertEqual(edited, await self.command("成员"))
        self.assertIn("10-12 伊藤美来", first)
        self.assertIn("BanG Dream", await self.command("标签"))
        await self.command("群名 测试群")
        await self.command("订阅 声优 1")
        await self.service.run_reminders(
            self.send, self.sessions, datetime(2026, 10, 11, 15, tzinfo=timezone.utc)
        )
        self.assertIn("测试群🎉@伊藤美来生日快乐🎉", self.sent[0][1])


class QuoteBot:
    self_id = "birthday-test-bot"

    def __init__(self, failures=()):
        self.sent = []
        self.failures = set(failures)

    async def send_to_group(self, *, group_openid, message):
        if (group_openid, message.type) in self.failures:
            raise RuntimeError("simulated QQ failure")
        self.sent.append((group_openid, message))
        return {"id": "sent-message"}


class MigrationTests(unittest.TestCase):
    def test_upgrade_matches_models_and_downgrade_preserves_existing_data(self):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy import create_engine, inspect, text

        _, _, models, _, _ = load_modules()
        path = Path(__file__).resolve().parents[1] / "nsy/plugins/birthday/migrations/a71b8c902d44_init.py"
        self.assertTrue(path.is_file(), "生日插件需要独立的数据库迁移")
        spec = importlib.util.spec_from_file_location("birthday_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                context = MigrationContext.configure(connection)
                with Operations.context(context):
                    migration.upgrade()
                self.assertEqual(compare_metadata(context, models.Model.metadata), [])
                self.assertEqual(len(inspect(connection).get_table_names()), 5)
                connection.execute(text("CREATE TABLE existing_rss_data (value TEXT)"))
                connection.execute(text("INSERT INTO existing_rss_data VALUES ('preserved')"))
                with Operations.context(context):
                    migration.downgrade()
                self.assertEqual(inspect(connection).get_table_names(), ["existing_rss_data"])
                self.assertEqual(connection.scalar(text("SELECT value FROM existing_rss_data")), "preserved")
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
