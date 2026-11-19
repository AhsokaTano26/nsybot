"""从定时任务到 QQ 发送与去重记录的集成回归测试。"""

import tempfile
import unittest
import importlib
import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import feedparser
import httpx
from nonebot.adapters.qq import GroupMessageCreateEvent, Message
from nonebot.exception import FinishedException
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rss_test_support import load_rss_plugin


RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>测试</title><link>https://example.com</link>
<description>测试动态</description><item><title>新文章</title>
<link>https://example.com/post-1</link><guid>post-1</guid>
<pubDate>Tue, 13 Oct 2026 12:00:00 GMT</pubDate><description>第一篇正文</description>
</item></channel></rss>"""

REAL_SLEEP = asyncio.sleep


class RecordingBot:
    def __init__(self):
        self.failed_groups = set()
        self.failed_types = set()
        self.before_send = None
        self.sent = []

    async def send_to_group(self, *, group_openid, message):
        if self.before_send:
            await self.before_send()
        if group_openid in self.failed_groups or message.type in self.failed_types:
            raise RuntimeError("simulated QQ failure")
        self.sent.append((group_openid, message))
        return {"id": "sent-message"}


class RSSDeliveryTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_root = tempfile.TemporaryDirectory(prefix="nsybot-rss-delivery-")
        cls.rss = load_rss_plugin(cls.test_root.name)

    @classmethod
    def tearDownClass(cls):
        cls.test_root.cleanup()

    async def asyncSetUp(self):
        from nsy.plugins.rssget import functions, models

        update_text = importlib.import_module("nsy.plugins.rssget.update_text")

        self.functions = functions
        self.real_fetch_feed = functions.fetch_feed
        self.real_report_status = functions.rss_get.report_status
        self.models = models
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.test_root.name}/{uuid4().hex}.sqlite3")
        self.addAsyncCleanup(self.engine.dispose)
        self.addAsyncCleanup(functions.NetworkManager.close)
        async with self.engine.begin() as connection:
            await connection.run_sync(models.Model.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.bot = RecordingBot()
        self.feed = feedparser.parse(RSS_FEED)
        from nsy import qq_utils

        self.patches = [
            patch.object(qq_utils, "active_message_limiter", qq_utils.ActiveMessageLimiter(0, 0)),
            patch.object(self.rss, "_refresh_lock", asyncio.Lock()),
            patch.object(self.rss, "_collection_lock", asyncio.Lock()),
            patch.object(self.rss, "_delivery_cache", {}, create=True),
            patch.object(self.rss, "_source_notice_lock", asyncio.Lock(), create=True),
            patch.object(functions, "_msg_semaphore", asyncio.Semaphore(3)),
            patch.object(self.rss, "get_session", self.sessions),
            patch.object(functions, "get_session", self.sessions),
            patch.object(update_text, "get_session", self.sessions),
            patch.object(update_text, "_ingest_lock", asyncio.Lock(), create=True),
            patch.object(update_text, "_stage_lock", asyncio.Lock(), create=True),
            patch.object(self.rss, "get_bot", return_value=self.bot),
            patch.object(functions, "get_bot", return_value=self.bot),
            patch.object(functions, "fetch_feed", AsyncMock(side_effect=lambda _: self.feed)),
            patch.object(functions.rss_get, "report_status", AsyncMock()),
            patch.object(functions, "download_image", AsyncMock(return_value=(b"image", "rss.jpg"))),
            patch.object(functions.asyncio, "sleep", AsyncMock()),
            patch.object(self.rss, "is_current_time_in_period", return_value=False),
            patch.object(functions.config, "if_first_time_start", False),
            patch.object(functions.config, "ut_url", "https://status.invalid"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def seed(self, groups=("group-a",), push_limit=0):
        async with self.sessions.begin() as session:
            session.add(self.models.Plantform(name="test", url="/test/", need_trans="0"))
            session.add(self.models.User(User_ID="account", User_Name="测试", Plantform="test"))
            for group in groups:
                session.add(self.models.Subscribe(
                    id=f"account-{group}", username="account", group=group,
                ))
                # Existing regressions explicitly exercise unlimited delivery.
                # Pass None to test a group with no stored configuration.
                if push_limit is not None:
                    session.add(self.models.Groupconfig(
                        group_id=group, if_need_trans=True, if_need_self_trans=False,
                        if_need_translate=True, if_need_photo_num_mention=False,
                        if_need_merged_message=True, push_limit=push_limit,
                    ))

    async def configure_group(self, text, group="group-a"):
        event = GroupMessageCreateEvent.model_validate({
            "id": "message", "timestamp": "2026-10-25T12:00:00+00:00",
            "content": "群组配置", "group_id": group, "group_openid": group,
            "author": {
                "id": "member", "member_openid": "member", "bot": False,
                "member_role": "member",
            },
        })
        replies = []

        async def finish(message):
            replies.append(str(message))
            raise FinishedException

        with patch.object(self.rss.group_config, "finish", finish):
            with self.assertRaises(FinishedException):
                await self.rss.group_config.handlers[0].call(event=event, args=Message(text))
        return replies[-1]

    async def run_scheduled(self):
        jobs = [job for job in self.rss.scheduler.get_jobs() if job.func == self.rss.auto_update_func]
        self.assertEqual(len(jobs), 1, "RSS 定时任务应注册一次")
        await jobs[0].func()
        jobs = [job for job in self.rss.scheduler.get_jobs() if job.func == self.rss.auto_push_func]
        self.assertEqual(len(jobs), 1, "缓存推送任务应注册一次")
        await jobs[0].func()

    async def details(self):
        async with self.sessions() as session:
            return list((await session.scalars(select(self.models.Detail).where(
                ~self.models.Detail.id.startswith("rss-init:"),
            ))).all())

    async def test_send_text_sends_images_without_a_separate_count_notice(self):
        content = {
            "username": "测试", "text": "正文", "time": "2026-10-13 20:00",
            "link": "https://example.com/post", "images": [
                "https://example.com/image-1.jpg", "https://example.com/image-2.jpg",
            ],
        }
        for enabled in (False, True):
            with self.subTest(image_count=enabled):
                self.bot.sent.clear()
                group_config = self.models.Groupconfig(
                    group_id="group-a", if_need_trans=True, if_need_self_trans=False,
                    if_need_translate=False, if_need_photo_num_mention=enabled,
                    if_need_merged_message=True,
                )
                await self.functions.rss_get().send_text(
                    "group-a", content, 0, False, False, group_config,
                )
                self.assertEqual(
                    [message.type for _, message in self.bot.sent],
                    ["markdown", "file_image", "file_image"],
                )
                self.assertIn("正文", str(self.bot.sent[0][1]))

    async def test_failed_qq_delivery_does_not_create_dedup_record_and_is_retried(self):
        await self.seed()
        self.bot.failed_groups.add("group-a")
        await self.run_scheduled()
        self.assertEqual(await self.details(), [])
        self.bot.failed_groups.clear()
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1)
        self.assertIn("第一篇正文", str(self.bot.sent[0][1]))
        self.assertEqual(len(await self.details()), 1)
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1, "成功发送后的动态不应重复推送")

    async def test_successful_scheduled_refresh_sends_to_subscribed_group(self):
        await self.seed()
        await self.run_scheduled()
        self.assertEqual([group for group, _ in self.bot.sent], ["group-a"])
        self.assertIn("第一篇正文", str(self.bot.sent[0][1]))
        self.assertEqual(len(await self.details()), 1)

    async def test_repeated_guid_in_same_feed_is_only_sent_once(self):
        await self.seed()
        self.feed.entries.append(self.feed.entries[0])
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1)
        self.assertEqual(len(await self.details()), 1)

    async def test_self_reposts_disabled_by_group_configuration_remain_filtered(self):
        await self.seed()
        self.feed.entries[0]["title"] = "RT 测试：转发自己的文章"
        await self.run_scheduled()
        self.assertEqual(self.bot.sent, [])
        self.assertEqual(len(await self.details()), 1)

    async def test_failed_group_does_not_block_other_group_or_mark_it_delivered(self):
        await self.seed(("group-a", "group-b"))
        self.bot.failed_groups.add("group-a")
        await self.run_scheduled()
        self.assertEqual([group for group, _ in self.bot.sent], ["group-b"])
        records = await self.details()
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].id.endswith("-group-b"))

    async def test_first_refresh_seeds_old_articles_then_pushes_new_article(self):
        await self.seed()
        self.functions.config.if_first_time_start = True
        await self.run_scheduled()
        self.assertEqual(self.bot.sent, [])
        self.assertEqual(len(await self.details()), 1)
        self.assertFalse(self.functions.config.if_first_time_start)
        new_feed = feedparser.parse(RSS_FEED.replace("post-1", "post-2").replace("第一篇正文", "第二篇正文"))
        self.feed.entries.insert(0, new_feed.entries[0])
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1)
        self.assertIn("第二篇正文", str(self.bot.sent[0][1]))
        self.assertEqual(len(await self.details()), 2)

    async def test_startup_silences_only_groups_without_a_success_in_twenty_minutes(self):
        groups = ("recent", "boundary", "stale", "never")
        await self.seed(groups)
        now = datetime(2026, 10, 25, 19, 0)
        async with self.sessions.begin() as session:
            for group, age in (("recent", 300), ("boundary", 1200), ("stale", 1201)):
                session.add(self.models.Detail(
                    id=f"previous-{group}", updated=now - timedelta(seconds=age),
                ))
            # 静默记录和初始化标记不能冒充最近一次成功推送。
            session.add(self.models.Detail(id="rss-skip:example-stale", updated=now))
            session.add(self.models.Detail(id="rss-init:example-stale", updated=now))
        for index in range(2, 5):
            self.feed.entries.append(feedparser.parse(RSS_FEED.replace("post-1", f"post-{index}")).entries[0])
        self.functions.config.if_first_time_start = True
        with patch.object(self.rss, "datetime", wraps=datetime) as clock:
            clock.now.return_value = now
            await self.run_scheduled()
            self.assertCountEqual(
                [group for group, _ in self.bot.sent], ["recent"] * 4 + ["boundary"] * 4,
            )
            self.assertFalse(self.functions.config.if_first_time_start)
            self.bot.sent.clear()
            self.feed.entries.insert(0, feedparser.parse(RSS_FEED.replace("post-1", "post-5")).entries[0])
            # 即使下一轮间隔一小时，也应正常推送，且不补发首轮的旧文章。
            clock.now.return_value = now + timedelta(hours=1)
            await self.run_scheduled()
        self.assertCountEqual([group for group, _ in self.bot.sent], list(groups))

    async def test_stale_restart_reseeds_previously_initialized_subscription(self):
        await self.seed()
        await self.run_scheduled()
        now = datetime(2026, 10, 25, 19, 0)
        async with self.sessions.begin() as session:
            records = await session.scalars(select(self.models.Detail).where(
                self.models.Detail.updated.is_not(None),
            ))
            for record in records:
                record.updated = now - timedelta(hours=1)
        for index in range(2, 6):
            self.feed.entries.insert(0, feedparser.parse(RSS_FEED.replace("post-1", f"post-{index}")).entries[0])
        self.functions.config.if_first_time_start = True
        with patch.object(self.rss, "datetime", wraps=datetime) as clock:
            clock.now.return_value = now
            await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1, "重启首轮不能补发停机期间积压的文章")
        self.assertEqual(len(await self.details()), 5)
        self.feed.entries.insert(0, feedparser.parse(RSS_FEED.replace("post-1", "post-6")).entries[0])
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 2)

    async def test_signal_no_bypasses_startup_silence(self):
        await self.seed()
        async with self.sessions.begin() as session:
            session.add(self.models.Detail(
                id="previous-group-a", updated=datetime.now() - timedelta(days=1),
            ))
        self.functions.config.if_first_time_start = True

        async def finish(message):
            raise FinishedException

        with patch.object(self.rss.signal_on, "finish", finish):
            with self.assertRaises(FinishedException):
                await self.rss.signal_on.handlers[0].call()
        await self.run_scheduled()
        self.assertEqual([group for group, _ in self.bot.sent], ["group-a"])

    async def test_group_config_accepts_three_options_and_legacy_fourth_option(self):
        event = GroupMessageCreateEvent.model_validate({
            "id": "message", "timestamp": "2026-10-25T12:00:00+00:00",
            "content": "群组配置", "group_id": "group-a", "group_openid": "group-a",
            "author": {
                "id": "member", "member_openid": "member", "bot": False,
                "member_role": "member",
            },
        })

        async def finish(message):
            raise FinishedException

        for args in ("1 0 1", "1 0 1 1"):
            with self.subTest(args=args), patch.object(self.rss.group_config, "finish", finish):
                with self.assertRaises(FinishedException):
                    await self.rss.group_config.handlers[0].call(event=event, args=Message(args))
                async with self.sessions() as session:
                    group = await session.get(self.models.Groupconfig, "group-a")
                    self.assertIsNotNone(group)
                    self.assertEqual(
                        (group.if_need_trans, group.if_need_self_trans,
                         group.if_need_translate, group.if_need_photo_num_mention),
                        (True, False, True, False),
                    )

    async def test_markdown_failure_reaches_caller_instead_of_looking_successful(self):
        self.bot.failed_groups.add("group-a")
        with self.assertRaisesRegex(RuntimeError, "simulated QQ failure"):
            await self.functions.rss_get.handle_markdown_send("group-a", {"text": "正文"})

    async def test_primary_request_failure_uses_backup(self):
        await self.seed()
        with patch.object(self.functions.config, "rsshub_host_back", ["https://backup.invalid"]), patch.object(
            self.functions, "fetch_feed", AsyncMock(side_effect=[{"entries": [], "error": "HTTP 503"}, self.feed]),
        ):
            await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1)
        self.assertIn("第一篇正文", str(self.bot.sent[0][1]))

    async def test_first_working_backup_is_not_overwritten_by_later_failure(self):
        await self.seed()
        with patch.object(self.functions.config, "rsshub_host_back", ["https://backup-a.invalid", "https://backup-b.invalid"]), patch.object(
            self.functions, "fetch_feed", AsyncMock(side_effect=[{"entries": []}, self.feed, {"entries": [], "error": "HTTP 503"}]),
        ):
            await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1)

    async def test_missing_rss_fields_do_not_block_valid_articles(self):
        await self.seed()
        for index, fields in enumerate((("id",), ("published", "published_parsed"), ("title",), ("summary",)), 2):
            with self.subTest(fields=fields):
                self.feed = feedparser.parse(RSS_FEED.replace("post-1", f"post-{index}"))
                for field in fields:
                    self.feed.entries[0].pop(field, None)
                before = len(self.bot.sent)
                await self.run_scheduled()
                self.assertEqual(len(self.bot.sent), before + 1)

    async def test_malformed_entry_does_not_abort_later_valid_entries(self):
        await self.seed()
        self.feed.entries.insert(0, feedparser.FeedParserDict())
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1)
        self.assertIn("第一篇正文", str(self.bot.sent[0][1]))

    async def test_translation_failure_still_delivers_original_article(self):
        await self.seed()
        async with self.sessions.begin() as session:
            (await session.get(self.models.Plantform, "test")).need_trans = "1"
        from nsy.plugins.rssget.format_json import PLATFORMS

        with patch.object(PLATFORMS[0], "main", AsyncMock(side_effect=RuntimeError("translation unavailable"))):
            await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1)
        self.assertIn("第一篇正文", str(self.bot.sent[0][1]))

    async def test_media_and_html_duplicate_image_is_only_sent_once(self):
        await self.seed()
        self.feed.entries[0]["media_content"] = [{"type": "image/jpeg", "url": "https://example.com/image.jpg"}]
        self.feed.entries[0]["summary"] += '<img src="https://example.com/image.jpg">'
        await self.run_scheduled()
        images = [message for _, message in self.bot.sent if message.type == "file_image"]
        self.assertEqual(len(images), 1)

    async def test_corrupt_cache_is_replaced_from_feed_instead_of_blocking_delivery(self):
        await self.seed()
        async with self.sessions.begin() as session:
            session.add(self.models.Content(
                id="f4ca36d5f89b9cee0d56a005f9966bee", username="测试", title="旧缓存",
                text="旧缓存", image_num="1", images="broken", link="https://example.com/post-1",
            ))
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1)
        self.assertIn("第一篇正文", str(self.bot.sent[0][1]))

    async def test_image_delivery_does_not_replay_body_or_images_on_next_refresh(self):
        await self.seed()
        self.feed.entries[0]["summary"] += '<img src="https://example.com/image.jpg">'
        await self.run_scheduled()
        self.assertEqual(len(await self.details()), 1)
        self.assertEqual(
            [message.type for _, message in self.bot.sent], ["markdown", "file_image"],
        )
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 2)

    async def test_terminal_image_failure_warns_without_replaying_delivered_body(self):
        await self.seed()
        self.feed.entries[0]["summary"] += '<img src="https://example.com/image.jpg">'
        self.bot.failed_types.add("file_image")
        await self.run_scheduled()
        self.assertTrue(any("图片发送失败" in str(message) for _, message in self.bot.sent))
        self.assertEqual(len(await self.details()), 1)
        await self.run_scheduled()
        self.assertEqual(len([message for _, message in self.bot.sent if "第一篇正文" in str(message)]), 1)

    async def test_manual_and_scheduled_refresh_overlap_does_not_duplicate_article(self):
        await self.seed()

        async def delay():
            await REAL_SLEEP(0.03)

        self.bot.before_send = delay
        await asyncio.gather(self.run_scheduled(), self.rss.refresh_article())
        self.assertEqual(len(self.bot.sent), 1)

    async def test_shared_guid_across_concurrent_users_is_only_sent_once(self):
        await self.seed()
        async with self.sessions.begin() as session:
            session.add(self.models.User(User_ID="other", User_Name="另一用户", Plantform="test"))
            session.add(self.models.Subscribe(id="other-group-a", username="other", group="group-a"))

        async def delay():
            await REAL_SLEEP(0.03)

        self.bot.before_send = delay
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1)

    async def test_existing_subscription_pushes_all_new_entries_after_restart(self):
        await self.seed()
        await self.run_scheduled()
        self.functions.config.if_first_time_start = True
        for index in range(2, 6):
            entry = feedparser.parse(RSS_FEED.replace("post-1", f"post-{index}")).entries[0]
            self.feed.entries.insert(0, entry)
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 5)
        self.assertEqual(len(await self.details()), 5)

    async def test_configured_three_article_window_silently_records_older_updates(self):
        await self.seed(push_limit=3)
        for index in range(2, 8):
            self.feed.entries.append(feedparser.parse(RSS_FEED.replace("post-1", f"post-{index}")).entries[0])
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 3)
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 3, "初次订阅的较旧文章不应以后突然补发")
        for index in range(8, 12):
            self.feed.entries.insert(0, feedparser.parse(RSS_FEED.replace("post-1", f"post-{index}")).entries[0])
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 6)
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 6, "窗口外文章以后也不补发")

    async def test_failed_article_retries_after_newer_posts_arrive_in_unlimited_mode(self):
        await self.seed()
        self.bot.failed_groups.add("group-a")
        await self.run_scheduled()
        self.bot.failed_groups.clear()
        for index in range(2, 6):
            self.feed.entries.insert(0, feedparser.parse(RSS_FEED.replace("post-1", f"post-{index}")).entries[0])
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 5)

    async def test_baseline_and_filtered_entries_are_not_counted_as_delivered(self):
        await self.seed()
        self.functions.config.if_first_time_start = True
        await self.run_scheduled()
        async with self.sessions() as session:
            self.assertEqual(await self.rss.DetailManager.count_recent(session), 0)

    async def test_legacy_subscriptions_are_grandfathered_without_reseeding(self):
        await self.seed()
        async with self.sessions.begin() as session:
            session.add(self.models.Detail(
                id="legacy-post-group-a", summary="旧文章", updated=datetime.now(),
            ))
        self.functions.config.if_first_time_start = True
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1)

    async def test_database_commit_failure_does_not_poison_other_groups(self):
        await self.seed(("group-a", "group-b"))
        inserted = False

        async def concurrent_commit():
            nonlocal inserted
            if not inserted:
                inserted = True
                async with self.sessions.begin() as session:
                    session.add(self.models.Detail(
                        id="f4ca36d5f89b9cee0d56a005f9966bee-group-a", summary="another sender",
                    ))

        self.bot.before_send = concurrent_commit
        await self.run_scheduled()
        self.assertIn("group-b", [group for group, _ in self.bot.sent])
        self.assertEqual(len(await self.details()), 2)

    async def test_hanging_translation_times_out_and_preserves_original(self):
        from nsy.plugins.rssget import format_json

        async def hanging_translate(text):
            await asyncio.Event().wait()

        with patch.object(format_json, "TRANSLATION_TIMEOUT", 0.02), patch.object(
            format_json.PLATFORMS[0], "main", hanging_translate,
        ):
            content = await asyncio.wait_for(format_json.Format().extract_content(self.feed.entries[0], 1), 0.2)
        self.assertEqual(content["text"], "第一篇正文")
        self.assertIsNone(content["trans_text"])

    async def test_syntax_error_in_cached_images_recovers_from_feed(self):
        await self.seed()
        async with self.sessions.begin() as session:
            session.add(self.models.Content(
                id="f4ca36d5f89b9cee0d56a005f9966bee", text="旧缓存", image_num="1", images="[",
            ))
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1)
        self.assertIn("第一篇正文", str(self.bot.sent[0][1]))

    async def test_startup_silences_new_group_without_successful_delivery(self):
        await self.seed()
        await self.run_scheduled()
        async with self.sessions.begin() as session:
            session.add(self.models.Subscribe(id="account-group-b", username="account", group="group-b"))
        self.functions.config.if_first_time_start = True
        await self.run_scheduled()
        self.assertNotIn("group-b", [group for group, _ in self.bot.sent])
        self.feed.entries.insert(0, feedparser.parse(RSS_FEED.replace("post-1", "post-2")).entries[0])
        await self.run_scheduled()
        self.assertEqual([group for group, _ in self.bot.sent].count("group-b"), 1)

    async def test_self_repost_filter_takes_precedence_over_forward_filter(self):
        await self.seed()
        self.feed.entries[0]["title"] = "RT 测试：自己的引用"
        self.feed.entries[0]["summary"] = '<div class="rsshub-quote">自己的引用</div>'
        await self.run_scheduled()
        self.assertEqual(self.bot.sent, [])
        async with self.sessions() as session:
            self.assertEqual(len((await session.scalars(select(self.models.Content))).all()), 1)

    async def test_failed_first_fetch_preserves_pending_baseline_until_valid_feed(self):
        await self.seed()
        self.functions.config.if_first_time_start = True
        valid_feed = self.feed
        self.feed = {"entries": [], "error": "Fetch failed"}
        await self.run_scheduled()
        self.assertEqual(await self.details(), [])
        self.feed = valid_feed
        await self.run_scheduled()
        self.assertEqual(self.bot.sent, [], "首次有效抓取建立基线，不应补发历史文章")
        self.feed.entries.insert(0, feedparser.parse(RSS_FEED.replace("post-1", "post-2")).entries[0])
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1)

    async def test_initialization_database_failure_is_isolated_to_its_group(self):
        from sqlalchemy import text

        await self.seed(("group-a", "group-b"), push_limit=3)
        for index in range(2, 5):
            self.feed.entries.append(feedparser.parse(RSS_FEED.replace("post-1", f"post-{index}")).entries[0])
        async with self.engine.begin() as connection:
            skipped_prefix = self.rss.DetailManager.skip_id("account", "group-a", "")
            await connection.execute(text(f"""
                CREATE TRIGGER reject_group_a_baseline BEFORE INSERT ON Detail
                WHEN NEW.id LIKE '{skipped_prefix}%'
                BEGIN SELECT RAISE(FAIL, 'simulated baseline database failure'); END
            """))
        await self.run_scheduled()
        self.assertEqual([group for group, _ in self.bot.sent], ["group-b"] * 3)

    async def test_overlapping_baselines_for_concurrent_users_do_not_drop_latest_posts(self):
        await self.seed(push_limit=3)
        async with self.sessions.begin() as session:
            session.add(self.models.User(User_ID="other", User_Name="另一用户", Plantform="test"))
            session.add(self.models.Subscribe(id="other-group-a", username="other", group="group-a"))
        feeds = {}
        for user in ("account", "other"):
            entries = [feedparser.parse(RSS_FEED.replace("post-1", f"{user}-{index}")).entries[0] for index in range(3)]
            entries.append(feedparser.parse(RSS_FEED.replace("post-1", "shared-old-post")).entries[0])
            feeds[user] = {"entries": entries}
        get_existing = self.rss.DetailManager.get_existing_ids

        async def slow_lookup(session, ids):
            result = await get_existing(session, ids)
            await REAL_SLEEP(0.02)
            return result

        with patch.object(self.functions, "fetch_feed", AsyncMock(side_effect=lambda url: feeds[url.rsplit("/", 1)[-1]])), patch.object(
            self.rss.DetailManager, "get_existing_ids", slow_lookup,
        ):
            await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 6)
        self.assertEqual(len(await self.details()), 8, "两来源各自保留历史基线，六篇新文章均送达")

    async def test_other_sources_baseline_does_not_suppress_failed_article_retry(self):
        await self.seed(push_limit=3)
        self.bot.failed_groups.add("group-a")
        await self.run_scheduled()
        async with self.sessions.begin() as session:
            session.add(self.models.User(User_ID="other", User_Name="另一用户", Plantform="test"))
            session.add(self.models.Subscribe(id="other-group-a", username="other", group="group-a"))
        other_feed = {"entries": [
            *[feedparser.parse(RSS_FEED.replace("post-1", f"other-{index}")).entries[0] for index in range(3)],
            self.feed.entries[0],
        ]}
        with patch.object(self.functions, "fetch_feed", AsyncMock(side_effect=lambda url: other_feed if url.endswith("/other") else self.feed)):
            await self.run_scheduled()
            self.bot.failed_groups.clear()
            await self.run_scheduled()
        self.assertTrue(any("post-1)" in str(message) for _, message in self.bot.sent), "其他来源的历史基线不能吞掉待重试正文")

    async def test_other_sources_filter_does_not_suppress_failed_article_retry(self):
        await self.seed()
        self.bot.failed_groups.add("group-a")
        await self.run_scheduled()
        async with self.sessions.begin() as session:
            session.add(self.models.User(User_ID="other", User_Name="另一用户", Plantform="test"))
            session.add(self.models.Subscribe(id="other-group-a", username="other", group="group-a"))
        other_feed = feedparser.parse(RSS_FEED)
        other_feed.entries[0]["title"] = "RT 另一用户：自己转发"
        with patch.object(self.functions, "fetch_feed", AsyncMock(side_effect=lambda url: other_feed if url.endswith("/other") else self.feed)):
            await self.run_scheduled()
            self.bot.failed_groups.clear()
            await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1, "其他来源过滤的同 GUID 不应让原来源永久漏发")

    async def test_per_group_article_limits_default_one_three_and_unlimited(self):
        await self.seed(("default", "three", "all"), push_limit=None)
        await self.configure_group("推送数量 3", "three")
        await self.configure_group("推送数量 0", "all")
        for index in range(2, 7):
            self.feed.entries.append(feedparser.parse(RSS_FEED.replace("post-1", f"post-{index}")).entries[0])
        await self.run_scheduled()
        self.assertCountEqual(
            [group for group, _ in self.bot.sent], ["default"] + ["three"] * 3 + ["all"] * 6,
        )
        self.bot.sent.clear()
        await self.configure_group("推送数量 0", "default")
        await self.run_scheduled()
        self.assertEqual(self.bot.sent, [], "扩大窗口不能补发之前已静默登记的旧文章")
        self.feed.entries.insert(0, feedparser.parse(RSS_FEED.replace("post-1", "post-7")).entries[0])
        await self.run_scheduled()
        self.assertCountEqual([group for group, _ in self.bot.sent], ["default", "three", "all"])

    async def test_named_group_settings_preserve_other_options_and_limit(self):
        await self.configure_group("推送数量 5")
        await self.configure_group("转发 关")
        await self.configure_group("自转发 开")
        await self.configure_group("翻译 0")
        async with self.sessions() as session:
            group = await session.get(self.models.Groupconfig, "group-a")
            self.assertEqual(
                (group.push_limit, group.if_need_trans, group.if_need_self_trans, group.if_need_translate),
                (5, False, True, False),
            )
        await self.configure_group("1 0 1")
        status = await self.configure_group("")
        self.assertIn("5", status)
        async with self.sessions() as session:
            group = await session.get(self.models.Groupconfig, "group-a")
            self.assertEqual(group.push_limit, 5)
        for invalid in ("推送数量 6", "推送数量 -1", "推送数量 1.5", "推送数量 全部", "转发 随便", "翻译 开 多余"):
            with self.subTest(invalid=invalid):
                await self.configure_group(invalid)
                async with self.sessions() as session:
                    self.assertEqual((await session.get(self.models.Groupconfig, "group-a")).push_limit, 5)

    async def test_group_configuration_without_arguments_is_read_only_and_shows_defaults(self):
        status = await self.configure_group("")
        self.assertIn("推送数量", status)
        self.assertIn("1", status)
        async with self.sessions() as session:
            self.assertIsNone(await session.get(self.models.Groupconfig, "group-a"))

    async def test_long_body_and_translation_finish_before_all_original_images(self):
        original = "原文开始\n\n" + ("长段落中文🙂 " * 900) + "\n\n原文结束"
        translated = "译文开始\n\n" + ("完整翻译内容 " * 900) + "\n\n译文结束"
        content = {
            "username": "测试", "time": "2026-10-25 19:00", "link": "https://example.com/post",
            "text": original, "trans_text": translated,
            "images": ["https://example.com/one.jpg", "https://example.com/two.jpg"],
        }
        await self.functions.rss_get().send_text("group-a", content, 1, False, False)
        kinds = [message.type for _, message in self.bot.sent]
        self.assertEqual(kinds[-2:], ["file_image", "file_image"])
        self.assertTrue(all(kind == "markdown" for kind in kinds[:-2]))
        pages = [message.data["markdown"].content for _, message in self.bot.sent[:-2]]
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(page) <= 3500 for page in pages))
        self.assertIn("原文结束", "".join(pages))
        self.assertIn("译文结束", "".join(pages))
        self.assertNotIn("已自动截断", "".join(pages))

    async def test_same_account_fans_out_to_groups_without_waiting_for_one_group_to_finish(self):
        await self.seed(("group-a", "group-b"))
        started = set()
        both_started = asyncio.Event()
        send = self.functions.rss_get.send_text

        async def concurrent_send(sender, group_id, *args, **kwargs):
            started.add(group_id)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 0.3)
            return await send(sender, group_id, *args, **kwargs)

        with patch.object(self.functions.rss_get, "send_text", concurrent_send):
            await self.run_scheduled()
        self.assertCountEqual([group for group, _ in self.bot.sent], ["group-a", "group-b"])

    async def test_accounts_complete_in_order_with_random_gap_between_them(self):
        await self.seed()
        async with self.sessions.begin() as session:
            session.add(self.models.User(User_ID="other", User_Name="另一个账号", Plantform="test"))
            session.add(self.models.Subscribe(id="other-group-a", username="other", group="group-a"))
        events = []

        async def process_account(*, userid, **kwargs):
            events.append(("start", userid))
            await REAL_SLEEP(0.01)
            events.append(("done", userid))

        async def wait_gap(seconds):
            events.append(("gap", seconds))

        await self.rss.auto_update_func()
        with patch.object(self.rss.R, "send_cached_rss", process_account), patch.object(
            self.functions.asyncio, "sleep", wait_gap,
        ), patch.object(self.functions.random, "uniform", return_value=9) as choose_gap:
            await self.rss.auto_push_func()
        self.assertEqual([call.args for call in choose_gap.call_args_list], [(5, 15)])
        self.assertEqual(events, [
            ("start", "account"), ("done", "account"), ("gap", 9),
            ("start", "other"), ("done", "other"),
        ])

    async def test_group_waits_only_between_articles(self):
        await self.seed()
        for index in range(2, 4):
            self.feed.entries.append(feedparser.parse(RSS_FEED.replace("post-1", f"post-{index}")).entries[0])
        self.functions.asyncio.sleep.reset_mock()
        with patch.object(self.functions.random, "uniform", return_value=9) as choose_gap:
            await self.rss.R.handle_rss("account", ["group-a"], await self._group_configs())
        self.assertEqual([call.args for call in choose_gap.call_args_list], [(5, 15), (5, 15)])
        self.assertEqual(
            [call.args[0] for call in self.functions.asyncio.sleep.await_args_list], [9, 9],
        )

    async def test_partial_page_failure_keeps_the_gap_before_the_next_article(self):
        await self.seed()
        self.feed.entries[0]["summary"] = "第一页正文 " * 1400
        self.feed.entries.append(feedparser.parse(RSS_FEED.replace("post-1", "post-2")).entries[0])
        send = self.bot.send_to_group
        attempts = 0

        async def fail_second_page(**kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise RuntimeError("second page failed")
            return await send(**kwargs)

        with patch.object(self.bot, "send_to_group", fail_second_page), patch.object(
            self.functions.random, "uniform", return_value=9,
        ) as choose_gap:
            await self.rss.R.handle_rss("account", ["group-a"], await self._group_configs())
        self.assertEqual([call.args for call in choose_gap.call_args_list], [(5, 15)])
        self.assertEqual([call.args[0] for call in self.functions.asyncio.sleep.await_args_list], [9])
        records = await self.details()
        self.assertEqual(len(records), 1, "未发完全部正文页的文章不能记为成功")
        self.assertIn("第一篇正文", str(self.bot.sent[-1][1]))

    async def test_manual_fresh_and_cached_articles_share_group_lock_and_send_limiter(self):
        from nsy import qq_utils

        await self.seed()
        self.feed.entries[0]["summary"] = ("完整正文 " * 1400) + '<img src="https://example.com/original.jpg">'
        event = GroupMessageCreateEvent.model_validate({
            "id": "message", "timestamp": "2026-10-25T12:00:00+00:00",
            "content": "rss account", "group_id": "group-a", "group_openid": "group-a",
            "author": {"id": "member", "member_openid": "member", "bot": False, "member_role": "member"},
        })
        cached_read, cache_write = self.rss.get_text, self.rss.update_text
        now = 0.0

        async def advance(seconds):
            nonlocal now
            now += seconds

        limiter = qq_utils.ActiveMessageLimiter(clock=lambda: now, sleeper=advance)
        for cached in (False, True):
            with self.subTest(cached=cached):
                prepared = asyncio.Event()
                replies, sent_at = [], []

                async def read_content(article_id):
                    content = await cached_read(article_id)
                    prepared.set()
                    return content

                async def write_content(content):
                    result = await cache_write(content)
                    prepared.set()
                    return result

                async def reply(message):
                    replies.append(message)
                    sent_at.append(now)

                with patch.object(self.rss, "fetch_feed", AsyncMock(return_value=self.feed)), patch.object(
                    self.rss, "get_text", read_content,
                ), patch.object(self.rss, "update_text", write_content), patch.object(
                    self.rss, "download_image", AsyncMock(return_value=(b"original-image", "original.jpg")),
                ), patch.object(self.rss.rss_cmd, "send", reply), patch.object(
                    qq_utils, "active_message_limiter", limiter,
                ):
                    async with self.functions._delivery_lock("rss-group:group-a"):
                        task = asyncio.create_task(self.rss.handle_rss_cmd(event, Message("account")))

                        async def finish_query(pending=task):
                            await asyncio.gather(pending, return_exceptions=True)

                        self.addAsyncCleanup(finish_query)
                        await asyncio.wait_for(prepared.wait(), 1)
                        self.assertEqual(replies, [], "手动全文不能插进同群另一篇文章中")
                    await asyncio.wait_for(task, 1)
                self.assertGreater(len(replies), 2)
                self.assertEqual(replies[-1].type, "file_image")
                self.assertTrue(all(message.type == "markdown" for message in replies[:-1]))
                self.assertTrue(all(later - earlier >= 3.1 - 1e-9 for earlier, later in zip(sent_at, sent_at[1:])))

    async def test_full_feed_is_cached_before_group_window_and_startup_silence(self):
        await self.seed(push_limit=1)
        older = dict(self.feed.entries[0], id="older", guid="older", link="https://example.com/older")
        older["summary"] = '旧正文<img src="https://example.com/older.jpg">'
        self.feed.entries.append(older)
        with patch.object(self.functions.config, "if_first_time_start", True):
            await self.rss.refresh_article()
        async with self.sessions() as session:
            cached = list((await session.scalars(select(self.models.Content))).all())
        self.assertEqual({row.link for row in cached}, {"https://example.com/post-1", "https://example.com/older"})
        self.assertIn("旧正文", next(row.text for row in cached if row.link.endswith("older")))
        self.assertEqual(self.bot.sent, [])

    async def test_account_without_group_subscription_is_collected(self):
        await self.seed(groups=())
        self.feed.entries[0]["summary"] += '<img src="https://example.com/unsubscribed.jpg">'
        await self.rss.auto_update_func()
        async with self.sessions() as session:
            cached = list((await session.scalars(select(self.models.Content))).all())
        self.assertEqual(len(cached), 1)
        self.assertIn("unsubscribed.jpg", cached[0].images)
        self.assertEqual(self.bot.sent, [])
        self.assertEqual(await self.details(), [])

    async def test_collection_includes_unsubscribed_accounts_and_fetches_each_once(self):
        await self.seed(("group-a", "group-b"))
        async with self.sessions.begin() as session:
            session.add(self.models.User(User_ID="no-group", User_Name="无订阅", Plantform="test"))
        feeds = {"account": self.feed, "no-group": feedparser.parse(RSS_FEED.replace("post-1", "other-post"))}
        with patch.object(self.functions, "fetch_feed", AsyncMock(side_effect=lambda url: feeds[url.rsplit("/", 1)[-1]])) as fetch:
            await self.rss.auto_update_func()
        async with self.sessions() as session:
            cached = list((await session.scalars(select(self.models.Content))).all())
        self.assertEqual({row.username for row in cached}, {"测试", "无订阅"})
        self.assertEqual(fetch.await_count, 2)
        self.assertEqual(self.bot.sent, [], "采集任务不能夹带 QQ 发送")

    async def test_collection_continues_offline_and_at_night_without_consuming_startup_flag(self):
        await self.seed()
        with patch.object(self.rss, "get_bot", side_effect=ValueError("offline")), patch.object(
            self.rss, "is_current_time_in_period", return_value=True,
        ), patch.object(self.functions.config, "if_first_time_start", True):
            await self.rss.auto_update_func()
            async with self.sessions() as session:
                cached = list((await session.scalars(select(self.models.Content))).all())
            self.assertEqual(len(cached), 1)
            self.assertTrue(self.functions.config.if_first_time_start)
        self.assertEqual(await self.details(), [])

    async def test_delivery_reads_collected_snapshot_without_refetching(self):
        await self.seed()
        await self.rss.R.handle_rss("account", [])
        push = getattr(self.rss, "auto_push_func", None)
        self.assertTrue(callable(push), "需要独立的缓存推送任务")
        with patch.object(self.functions, "fetch_feed", AsyncMock(side_effect=AssertionError("推送不得抓 RSS"))):
            await push()
            await push()
        self.assertEqual([group for group, _ in self.bot.sent], ["group-a"])

    async def test_manual_rss_uses_source_retries_and_backup_without_holding_connection(self):
        await self.seed()
        event_value = GroupMessageCreateEvent.model_validate({
            "id": "message", "timestamp": "2026-10-25T12:00:00+00:00",
            "content": "rss account", "group_id": "group-a", "group_openid": "group-a",
            "author": {"id": "member", "member_openid": "member", "bot": False, "member_role": "member"},
        })
        requests, leases, sent = [], [], []

        def respond(request):
            requests.append(request.url.host)
            leases.append(self.engine.pool.checkedout())
            return httpx.Response(503) if request.url.host == "primary.invalid" else httpx.Response(200, text=RSS_FEED)

        async def finish(message):
            raise FinishedException

        async def send_article(group, content, translation):
            sent.append(content["link"])

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.object(self.functions.NetworkManager, "get_client", return_value=client), patch.object(
                self.functions.config, "rsshub_host", "https://primary.invalid",
            ), patch.object(self.functions.config, "rsshub_host_back", ["https://backup.invalid"]), patch.object(
                self.functions, "fetch_feed", self.real_fetch_feed,
            ), patch.object(self.rss, "fetch_feed", self.real_fetch_feed), patch.object(
                self.rss, "_send_rss_article", send_article,
            ), patch.object(self.rss.rss_cmd, "finish", finish):
                try:
                    await self.rss.handle_rss_cmd(event_value, Message("account"))
                except FinishedException:
                    pass
        self.assertEqual(requests, ["primary.invalid"] * 4 + ["backup.invalid"])
        self.assertEqual(leases, [0] * 5, "手动查询在重试等待和HTTP期间也不能持有数据库连接")
        self.assertEqual(sent, ["https://example.com/post-1"])

    async def test_slow_delivery_does_not_block_collection_of_new_posts(self):
        await self.seed()
        await self.rss.R.handle_rss("account", [])
        push = getattr(self.rss, "auto_push_func", None)
        self.assertTrue(callable(push), "需要独立的缓存推送任务")
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_send():
            entered.set()
            await release.wait()

        self.bot.before_send = slow_send
        sending = asyncio.create_task(push())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            self.feed = feedparser.parse(RSS_FEED.replace("post-1", "post-2"))
            await asyncio.wait_for(self.rss.auto_update_func(), 1)
            async with self.sessions() as session:
                cached = list((await session.scalars(select(self.models.Content))).all())
            self.assertEqual({row.link for row in cached}, {"https://example.com/post-1", "https://example.com/post-2"})
        finally:
            release.set()
            await sending

    async def test_night_collection_does_not_consume_first_push_baseline(self):
        await self.seed()
        self.functions.config.if_first_time_start = True
        await self.rss.auto_update_func()
        with patch.object(self.rss, "is_current_time_in_period", return_value=True):
            await self.rss.auto_push_func()
        self.assertEqual(self.bot.sent, [])
        self.assertEqual(await self.details(), [])
        self.assertTrue(self.functions.config.if_first_time_start)
        await self.rss.auto_push_func()
        self.assertEqual(self.bot.sent, [])
        self.assertFalse(self.functions.config.if_first_time_start)
        self.feed = feedparser.parse(RSS_FEED.replace("post-1", "post-2"))
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 1)

    async def test_restart_waits_for_fresh_snapshot_before_initializing_groups(self):
        await self.seed()
        await self.rss.R.collect_rss("account")
        async with self.sessions.begin() as session:
            snapshot = await session.get(self.models.RSSFeedCache, "account")
            snapshot.collected_at = self.rss._rss_started_at - timedelta(seconds=1)
        self.functions.config.if_first_time_start = True
        await self.rss.auto_push_func()
        self.assertEqual(await self.details(), [])
        self.assertTrue(self.functions.config.if_first_time_start)
        await self.run_scheduled()
        self.assertEqual(self.bot.sent, [])
        self.assertFalse(self.functions.config.if_first_time_start)

    async def test_failed_collection_keeps_last_valid_snapshot_for_delivery(self):
        await self.seed()
        await self.rss.auto_update_func()
        async with self.sessions() as session:
            cached = await session.get(self.models.RSSFeedCache, "account")
            before = (cached.entries, cached.collected_at)
        self.feed = {"entries": [], "error": "fetch failed"}
        await self.rss.auto_update_func()
        async with self.sessions() as session:
            cached = await session.get(self.models.RSSFeedCache, "account")
            self.assertEqual((cached.entries, cached.collected_at), before)
        await self.rss.auto_push_func()
        self.assertEqual(len(self.bot.sent), 1)

    async def test_one_broken_feed_does_not_stop_other_accounts(self):
        await self.seed(groups=())
        async with self.sessions.begin() as session:
            session.add(self.models.User(User_ID="other", User_Name="正常账号", Plantform="test"))

        def respond(url):
            return self.feed if url.endswith("/other") else {"entries": [], "error": "failed"}

        with patch.object(self.functions, "fetch_feed", AsyncMock(side_effect=respond)):
            await self.rss.auto_update_func()
        async with self.sessions() as session:
            cached = list((await session.scalars(select(self.models.Content))).all())
        self.assertEqual([row.username for row in cached], ["正常账号"])

    async def test_cached_snapshot_preserves_quote_filtering(self):
        await self.seed()
        async with self.sessions.begin() as session:
            (await session.get(self.models.Groupconfig, "group-a")).if_need_trans = False
        self.feed.entries[0]["description"] = '<div class="rsshub-quote">引用正文</div>自己的正文'
        await self.run_scheduled()
        self.assertEqual(self.bot.sent, [], "快照存取不能让引用推文绕过群转发开关")
        self.assertEqual(len(await self.details()), 1)

    async def test_cached_articles_are_checked_in_batches_without_per_article_reads(self):
        cache = importlib.import_module("nsy.plugins.rssget.update_text")
        async with self.sessions.begin() as session:
            session.add_all(self.models.Content(id=f"cached-{i}", image_num="0", text="x" * 8192)
                            for i in range(200))
        selects = []

        def count(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(self.engine.sync_engine, "before_cursor_execute", count)
        try:
            await cache.cache_entries([({"title": "unchanged"}, f"cached-{i}") for i in range(200)], "作者")
        finally:
            event.remove(self.engine.sync_engine, "before_cursor_execute", count)
        self.assertLessEqual(len(selects), 2, "200 篇命中缓存不能逐篇读取正文")

    async def retry_ingest(self):
        worker = getattr(self.rss, "auto_ingest_retry_func", None)
        self.assertTrue(callable(worker), "需要独立的持久化入库补偿任务")
        await worker()

    async def make_ingest_due(self):
        async with self.sessions.begin() as session:
            for row in await session.scalars(select(self.models.RSSIngestQueue)):
                row.next_retry_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)

    async def test_failed_ingest_survives_new_feed_window_and_worker_restart(self):
        await self.seed(groups=())
        self.feed = feedparser.parse(RSS_FEED.replace('</item>',
            '<enclosure url="https://example.com/original.jpg" type="image/jpeg" /></item>'))
        async with self.sessions.begin() as session:
            await session.execute(text('CREATE TRIGGER reject_old BEFORE INSERT ON "Content" '
                "WHEN NEW.link='https://example.com/post-1' BEGIN SELECT RAISE(FAIL, 'simulated DB failure'); END"))
        await self.rss.auto_update_func()
        queue_model = getattr(self.models, "RSSIngestQueue", None)
        self.assertIsNotNone(queue_model, "失败文章必须持久保留原始 RSS 条目")
        async with self.sessions() as session:
            pending = list(await session.scalars(select(queue_model)))
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].attempts, 1)
            self.assertIn("original.jpg", pending[0].entry)
        self.feed = feedparser.parse(RSS_FEED.replace("post-1", "post-2"))
        await self.rss.auto_update_func()
        await self.engine.dispose()
        async with self.sessions.begin() as session:
            await session.execute(text("DROP TRIGGER reject_old"))
        await self.make_ingest_due()
        with patch.object(self.functions, "fetch_feed", AsyncMock(side_effect=AssertionError("补偿不能重新抓RSS"))):
            await self.retry_ingest()
            await self.retry_ingest()
        async with self.sessions() as session:
            articles = list(await session.scalars(select(self.models.Content)))
            self.assertEqual({row.link for row in articles}, {"https://example.com/post-1", "https://example.com/post-2"})
            self.assertIn("original.jpg", next(row.images for row in articles if row.link.endswith("post-1")))
            self.assertEqual(len(list(await session.scalars(select(self.models.ImageSync)))), 1)
            self.assertEqual(list(await session.scalars(select(queue_model))), [])
        self.assertEqual(self.bot.sent, [])
        self.assertEqual(await self.details(), [])

    async def test_ingest_format_failure_is_queued_and_same_feed_keeps_backoff(self):
        from nsy.plugins.rssget.format_json import Format

        await self.seed(groups=())
        with patch.object(Format, "extract_content", AsyncMock(side_effect=ValueError("bad article"))):
            await self.rss.auto_update_func()
        queue_model = getattr(self.models, "RSSIngestQueue", None)
        self.assertIsNotNone(queue_model, "正文解析失败也必须持久化")
        async with self.sessions() as session:
            row = await session.scalar(select(queue_model))
            before = row.attempts, row.next_retry_at, row.last_error
        await self.rss.auto_update_func()
        async with self.sessions() as session:
            row = await session.scalar(select(queue_model))
            self.assertEqual((row.attempts, row.next_retry_at, row.last_error), before)
            self.assertEqual(list(await session.scalars(select(self.models.Content))), [])
        await self.make_ingest_due()
        await self.retry_ingest()
        async with self.sessions() as session:
            self.assertEqual(list(await session.scalars(select(queue_model))), [])
            self.assertEqual(len(list(await session.scalars(select(self.models.Content)))), 1)

    async def test_ingest_cancel_after_staging_leaves_durable_work(self):
        from nsy.plugins.rssget.format_json import Format

        await self.seed(groups=())
        with patch.object(Format, "extract_content", AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await self.rss.R.collect_rss("account")
        queue_model = getattr(self.models, "RSSIngestQueue", None)
        self.assertIsNotNone(queue_model)
        async with self.sessions() as session:
            row = await session.scalar(select(queue_model))
            self.assertEqual(row.attempts, 0)
        await self.retry_ingest()
        async with self.sessions() as session:
            self.assertEqual(len(list(await session.scalars(select(self.models.Content)))), 1)

    async def test_new_feed_is_staged_while_old_ingest_worker_is_busy(self):
        from nsy.plugins.rssget.format_json import Format

        await self.seed(groups=())
        with patch.object(Format, "extract_content", AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await self.rss.R.collect_rss("account")
        entered, release = asyncio.Event(), asyncio.Event()
        original = Format.extract_content

        async def slow_old(formatter, entry, translate):
            entered.set()
            await release.wait()
            return await original(formatter, entry, translate)

        async def wait_for_durable_new_entry():
            while True:
                async with self.sessions() as session:
                    rows = list(await session.scalars(select(self.models.RSSIngestQueue)))
                    if any("post-2" in row.entry for row in rows):
                        return
                await REAL_SLEEP(0.01)

        with patch.object(Format, "extract_content", slow_old):
            worker = asyncio.create_task(self.retry_ingest())
            await asyncio.wait_for(entered.wait(), 2)
            self.feed = feedparser.parse(RSS_FEED.replace("post-1", "post-2"))
            collector = asyncio.create_task(self.rss.R.collect_rss("account"))
            try:
                try:
                    await asyncio.wait_for(wait_for_durable_new_entry(), 2)
                except TimeoutError:
                    self.fail("旧任务阻塞时，新取得的RSS也必须先持久化")
            finally:
                collector.cancel()
                await asyncio.gather(collector, return_exceptions=True)
                release.set()
                await worker
        await self.retry_ingest()
        async with self.sessions() as session:
            self.assertEqual({row.link for row in await session.scalars(select(self.models.Content))},
                {"https://example.com/post-1", "https://example.com/post-2"})

    async def test_image_index_failure_rolls_back_article_and_queue_ack(self):
        await self.seed(groups=())
        self.feed.entries[0]["summary"] = '<img src="https://example.com/original.jpg">'
        async with self.sessions.begin() as session:
            await session.execute(text("CREATE TRIGGER reject_index BEFORE INSERT ON rss_image_sync "
                                       "BEGIN SELECT RAISE(FAIL, 'simulated index failure'); END"))
        await self.rss.auto_update_func()
        queue_model = getattr(self.models, "RSSIngestQueue", None)
        self.assertIsNotNone(queue_model)
        async with self.sessions() as session:
            self.assertEqual(list(await session.scalars(select(self.models.Content))), [])
            self.assertEqual(list(await session.scalars(select(self.models.ImageSync))), [])
            self.assertEqual(len(list(await session.scalars(select(queue_model)))), 1)
        async with self.sessions.begin() as session:
            await session.execute(text("DROP TRIGGER reject_index"))
        await self.make_ingest_due()
        await self.retry_ingest()
        async with self.sessions() as session:
            self.assertEqual(len(list(await session.scalars(select(self.models.Content)))), 1)
            self.assertEqual(len(list(await session.scalars(select(self.models.ImageSync)))), 1)
            self.assertEqual(list(await session.scalars(select(queue_model))), [])

    async def test_ingest_queue_stage_failure_does_not_advance_snapshot(self):
        await self.seed(groups=())
        queue_model = getattr(self.models, "RSSIngestQueue", None)
        self.assertIsNotNone(queue_model)
        async with self.sessions.begin() as session:
            await session.execute(text("CREATE TRIGGER reject_queue BEFORE INSERT ON rss_ingest_queue "
                                       "BEGIN SELECT RAISE(FAIL, 'simulated storage unavailable'); END"))
        from sqlalchemy.exc import SQLAlchemyError
        with self.assertRaises(SQLAlchemyError):
            await self.rss.R.collect_rss("account")
        async with self.sessions() as session:
            self.assertEqual(list(await session.scalars(select(self.models.RSSFeedCache))), [])
            self.assertEqual(list(await session.scalars(select(self.models.Content))), [])

    async def test_stale_ingest_worker_preserves_newer_payload(self):
        from nsy.plugins.rssget.format_json import Format

        await self.seed(groups=())
        with patch.object(Format, "extract_content", AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await self.rss.R.collect_rss("account")
        original_extract = Format.extract_content

        async def replace_before_write(formatter, entry, translate):
            async with self.sessions.begin() as session:
                row = await session.scalar(select(self.models.RSSIngestQueue))
                changed = dict(entry, link="https://example.com/newer")
                row.entry = json.dumps(changed, default=str)
                row.version = "newer-version"
            return await original_extract(formatter, entry, translate)

        with patch.object(Format, "extract_content", replace_before_write):
            await self.retry_ingest()
        async with self.sessions() as session:
            self.assertEqual(list(await session.scalars(select(self.models.Content))), [], "过时任务不能写入旧内容")
            self.assertEqual(len(list(await session.scalars(select(self.models.RSSIngestQueue)))), 1)
        await self.retry_ingest()
        async with self.sessions() as session:
            self.assertEqual((await session.scalar(select(self.models.Content))).link, "https://example.com/newer")
            self.assertEqual(list(await session.scalars(select(self.models.RSSIngestQueue))), [])

    async def test_ingest_worker_is_bounded_and_poison_article_does_not_block_others(self):
        from nsy.plugins.rssget.format_json import Format

        await self.seed(groups=())
        self.feed.entries.extend(dict(self.feed.entries[0], id=f"extra-{i}", link=f"https://example.com/extra-{i}")
                                 for i in range(2))
        with patch.object(Format, "extract_content", AsyncMock(side_effect=ValueError("bad data"))):
            await self.rss.auto_update_func()
        queue_model = getattr(self.models, "RSSIngestQueue", None)
        self.assertIsNotNone(queue_model)
        await self.make_ingest_due()
        async with self.sessions.begin() as session:
            poison = await session.scalar(select(queue_model).order_by(queue_model.id))
            poison.entry = "{"
            poison.attempts = 99
            poison.next_retry_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=10)
        with patch.object(self.rss.config, "rss_ingest_retry_batch", 2, create=True):
            await self.retry_ingest()
        async with self.sessions() as session:
            queued = list(await session.scalars(select(queue_model)))
            self.assertEqual(len(queued), 2, "每次最多取2条，其中一条毒数据不能阻断另一条")
            self.assertEqual(len(list(await session.scalars(select(self.models.Content)))), 1)
            poison = next(row for row in queued if row.entry == "{")
            self.assertEqual(poison.attempts, 100)
            delay = (poison.next_retry_at - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()
            self.assertGreater(delay, 3590)
            self.assertLessEqual(delay, 3600)

    async def test_idle_delivery_skips_completed_snapshots_and_account_waits(self):
        await self.seed()
        async with self.sessions.begin() as session:
            session.add(self.models.User(User_ID="other", User_Name="其他", Plantform="test"))
            session.add(self.models.Subscribe(id="other-group-a", username="other", group="group-a"))
        await self.run_scheduled()
        self.functions.asyncio.sleep.reset_mock()
        before = len(self.bot.sent)
        await self.rss.auto_push_func()
        self.assertEqual(len(self.bot.sent), before)
        self.assertEqual(self.functions.asyncio.sleep.await_count, 0, "空闲推送检查不能逐账号等待")

    async def test_qq_send_does_not_hold_a_database_connection(self):
        await self.seed()
        connections = []

        async def observe():
            connections.append(self.engine.sync_engine.pool.checkedout())

        self.bot.before_send = observe
        await self.run_scheduled()
        self.assertEqual(connections, [0], "QQ I/O 期间必须释放外层数据库会话")

    async def test_identical_collection_does_not_invalidate_completed_delivery(self):
        await self.seed()
        async with self.sessions.begin() as session:
            session.add(self.models.User(User_ID="other", User_Name="其他", Plantform="test"))
            session.add(self.models.Subscribe(id="other-group-a", username="other", group="group-a"))
        await self.run_scheduled()
        await self.rss.auto_update_func()
        self.functions.asyncio.sleep.reset_mock()
        await self.rss.auto_push_func()
        self.assertEqual(self.functions.asyncio.sleep.await_count, 0, "同一RSS窗口重新采集不能使完成缓存失效")

    async def test_failed_delivery_retries_same_snapshot_without_another_collection(self):
        await self.seed()
        await self.rss.auto_update_func()
        self.bot.failed_groups.add("group-a")
        await self.rss.auto_push_func()
        self.bot.failed_groups.clear()
        await self.rss.auto_push_func()
        await self.rss.auto_push_func()
        self.assertEqual([group for group, _ in self.bot.sent], ["group-a"])

    async def enable_twitter(self):
        await self.seed(groups=())
        async with self.sessions.begin() as session:
            (await session.get(self.models.Plantform, "test")).url = "/twitter/user/"
        self.kuma_requests = []
        self.kuma_accepted = []
        self.kuma_connections = []
        self.kuma_error = False
        self.kuma_status = 200
        self.kuma_payload = {"ok": True}
        self.kuma_before_receive = None

        async def receive(request):
            self.kuma_requests.append(request)
            self.kuma_connections.append(self.engine.pool.checkedout())
            if self.kuma_before_receive:
                await self.kuma_before_receive()
            if self.kuma_error:
                raise httpx.ConnectError("simulated Kuma unavailable", request=request)
            if self.kuma_status == 200 and self.kuma_payload == {"ok": True}:
                self.kuma_accepted.append(dict(request.url.params))
            return httpx.Response(self.kuma_status, json=self.kuma_payload)

        client = httpx.AsyncClient(transport=httpx.MockTransport(receive))
        self.addAsyncCleanup(client.aclose)
        for patcher in (
            patch.object(self.rss.config, "target_group_openid", "ops-group"),
            patch.object(self.rss.config, "ut_url", "https://kuma.invalid/api/push/test-token?status=up&msg=OK&ping=&tenant=internal"),
            patch.object(self.functions.config, "rsshub_host_back", []),
            patch.object(self.functions.rss_get, "report_status", staticmethod(self.real_report_status)),
            patch.object(self.functions.NetworkManager, "get_client", return_value=client),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def flush_twitter(self):
        flush = getattr(self.rss, "auto_source_status_func", None)
        self.assertTrue(callable(flush), "需要独立的 Twitter 状态通知任务")
        await flush()

    async def expire_twitter_cooldown(self):
        async with self.sessions.begin() as session:
            state = await session.get(self.models.RSSSourceStatus, "twitter")
            state.retry_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)

    async def test_twitter_reports_aggregated_status_and_recovery_to_kuma(self):
        await self.enable_twitter()
        valid = self.feed
        await self.rss.auto_update_func()
        await self.flush_twitter()
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["up"], "首次有效采集需初始化 Kuma 心跳")
        self.feed = {"entries": [], "error": "limited", "status_code": 429,
                     "rate_limited": True, "retry_after": 3600}
        await self.rss.auto_update_func()
        await self.flush_twitter()
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["up", "down"])
        self.assertIn("Twitter 下线", self.kuma_accepted[-1]["msg"])
        self.functions.fetch_feed.reset_mock()
        await self.rss.auto_update_func()
        await self.flush_twitter()
        self.assertEqual(self.functions.fetch_feed.await_count, 0, "退避期内不能继续请求 Twitter")
        self.assertEqual(len(self.kuma_accepted), 2)
        await self.expire_twitter_cooldown()
        await self.rss.auto_update_func()
        await self.flush_twitter()
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["up", "down", "down"])
        await self.expire_twitter_cooldown()
        self.feed = valid
        await self.rss.auto_update_func()
        await self.flush_twitter()
        await self.rss.auto_update_func()
        await self.flush_twitter()
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["up", "down", "down", "up", "up"])
        self.assertIn("Twitter 上线", self.kuma_accepted[-1]["msg"])
        self.assertEqual(self.bot.sent, [], "Twitter 监控不应直接发 QQ 消息")
        for request in self.kuma_requests:
            self.assertEqual(request.url.params.get_list("status"), [request.url.params["status"]])
            self.assertEqual(len(request.url.params.get_list("msg")), 1)
            self.assertEqual(request.url.params["tenant"], "internal")

    async def test_one_twitter_account_failure_does_not_report_global_down(self):
        await self.enable_twitter()
        async with self.sessions.begin() as session:
            session.add(self.models.User(User_ID="other", User_Name="正常", Plantform="test"))
        with patch.object(self.functions, "fetch_feed", AsyncMock(side_effect=lambda url:
            self.feed if url.endswith("/other") else {"entries": [], "error": "private", "status_code": 404}
        )):
            await self.rss.auto_update_func()
        await self.flush_twitter()
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["up"])
        self.assertEqual(self.bot.sent, [])

    async def test_twitter_circuit_breaker_bounds_failures_without_blocking_other_platforms(self):
        await self.enable_twitter()
        async with self.sessions.begin() as session:
            session.add_all(self.models.User(User_ID=f"other-{i}", User_Name="Twitter", Plantform="test") for i in range(4))
            session.add(self.models.Plantform(name="bilibili", url="/bilibili/user/", need_trans="0"))
            session.add(self.models.User(User_ID="zzz-bili", User_Name="B站", Plantform="bilibili"))
        with patch.object(self.functions, "fetch_feed", AsyncMock(side_effect=lambda url:
            self.feed if "/bilibili/" in url else {"entries": [], "error": "unavailable", "status_code": 503}
        )) as fetch:
            await self.rss.auto_update_func()
        await self.flush_twitter()
        self.assertEqual(fetch.await_count, 4, "连续3个Twitter账号全源失败后，剩余Twitter账号应暂停；其他平台照常")
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["down"], "其他平台成功不能把 Twitter 故障覆盖为在线")
        self.assertEqual(self.bot.sent, [])
        async with self.sessions() as session:
            cached = list((await session.scalars(select(self.models.Content))).all())
        self.assertEqual([row.username for row in cached], ["B站"])

    async def test_kuma_outage_retries_without_requiring_qq_or_target_group(self):
        await self.enable_twitter()
        self.feed = {"entries": [], "error": "limited", "rate_limited": True}
        await self.rss.auto_update_func()
        self.kuma_error = True
        await self.flush_twitter()
        async with self.sessions() as session:
            self.assertEqual(len(list(await session.scalars(select(self.models.RSSSourceNotice)))), 1)
        self.kuma_error = False
        with patch.object(self.rss, "get_bot", side_effect=ValueError("offline")), patch.object(
            self.rss.config, "target_group_openid", None,
        ), patch.object(self.rss, "is_current_time_in_period", return_value=True):
            await self.flush_twitter()
            await self.flush_twitter()
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["down"])
        self.assertIn("Twitter 下线", self.kuma_accepted[0]["msg"])
        self.assertEqual(self.bot.sent, [])

    async def test_twitter_backup_success_does_not_trigger_down_or_cooldown(self):
        await self.enable_twitter()
        with patch.object(self.functions.config, "rsshub_host_back", ["https://backup.invalid"]), patch.object(
            self.functions, "fetch_feed", AsyncMock(side_effect=[
                {"entries": [], "error": "limited", "rate_limited": True}, self.feed,
            ]),
        ):
            await self.rss.auto_update_func()
        await self.flush_twitter()
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["up"])
        self.assertEqual(self.bot.sent, [])
        async with self.sessions() as session:
            state = await session.get(self.models.RSSSourceStatus, "twitter")
        self.assertIsNone(state.retry_at)

    async def test_account_404_and_broken_backup_do_not_trip_global_breaker(self):
        await self.enable_twitter()
        async with self.sessions.begin() as session:
            session.add_all(self.models.User(User_ID=f"other-{i}", User_Name="其他", Plantform="test") for i in range(3))

        def respond(url):
            if url.startswith("https://backup.invalid"):
                return {"entries": [], "error": "unavailable", "status_code": 503}
            if url.endswith("/other-2"):
                return self.feed
            return {"entries": [], "error": "private", "status_code": 404}

        with patch.object(self.functions.config, "rsshub_host_back", ["https://backup.invalid"]), patch.object(
            self.functions, "fetch_feed", AsyncMock(side_effect=respond),
        ) as fetch:
            await self.rss.auto_update_func()
        await self.flush_twitter()
        self.assertEqual(fetch.await_count, 7, "前三个失效账号不能让第四个正常账号被跳过")
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["up"])
        self.assertEqual(self.bot.sent, [])

    async def test_empty_valid_twitter_feed_is_not_an_outage(self):
        await self.enable_twitter()
        self.feed = feedparser.parse('<rss version="2.0"><channel><title>空账号</title>'
            '<link>https://example.com</link><description>暂无文章</description></channel></rss>')
        await self.rss.auto_update_func()
        await self.flush_twitter()
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["up"])
        self.assertEqual(self.bot.sent, [])

    async def test_twitter_cooldown_and_pending_transitions_survive_new_instances(self):
        await self.enable_twitter()
        valid = self.feed
        self.feed = {"entries": [], "error": "limited", "rate_limited": True}
        await self.rss.auto_update_func()
        self.functions.fetch_feed.reset_mock()
        # 模拟替换进程内采集器和锁，数据库保持原样。
        with patch.object(self.rss, "R", self.functions.rss_get()), patch.object(
            self.rss, "_collection_lock", asyncio.Lock(),
        ):
            await self.rss.auto_update_func()
            self.assertEqual(self.functions.fetch_feed.await_count, 0)
            await self.expire_twitter_cooldown()
            self.feed = valid
            await self.rss.auto_update_func()
        await self.flush_twitter()
        await self.flush_twitter()
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["down", "up"])
        self.assertEqual(self.kuma_connections, [0, 0], "Kuma HTTP 请求期间不能占着数据库连接")
        self.assertEqual(self.bot.sent, [])

    async def test_private_twitter_account_alone_does_not_prove_global_outage(self):
        await self.enable_twitter()
        self.feed = {"entries": [], "error": "not found", "status_code": 404}
        await self.rss.auto_update_func()
        await self.flush_twitter()
        self.assertEqual(self.kuma_requests, [], "单个私密账号不能触发 Kuma 全局故障")
        self.assertEqual(self.bot.sent, [])

    async def test_valid_empty_feed_recovers_twitter_without_discarding_cached_posts(self):
        await self.enable_twitter()
        await self.rss.auto_update_func()
        self.feed = {"entries": [], "error": "unavailable", "status_code": 503}
        await self.rss.auto_update_func()
        await self.flush_twitter()
        await self.expire_twitter_cooldown()
        self.feed = feedparser.parse('<rss version="2.0"><channel><title>空窗口</title>'
            '<link>https://example.com</link><description>暂无</description></channel></rss>')
        await self.rss.auto_update_func()
        await self.flush_twitter()
        async with self.sessions() as session:
            self.assertEqual(len(list(await session.scalars(select(self.models.Content)))), 1)
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["up", "down", "up"])
        self.assertIn("Twitter 上线", self.kuma_accepted[-1]["msg"])
        self.assertEqual(self.bot.sent, [])

    async def test_kuma_rejected_push_is_retained_until_acknowledged(self):
        await self.enable_twitter()
        self.feed = {"entries": [], "error": "limited", "rate_limited": True}
        await self.rss.auto_update_func()
        for status, payload in ((503, {"ok": False}), (200, {"ok": False}), (200, {})):
            with self.subTest(status=status, payload=payload):
                self.kuma_status, self.kuma_payload = status, payload
                await self.flush_twitter()
                async with self.sessions() as session:
                    self.assertEqual(len(list(await session.scalars(select(self.models.RSSSourceNotice)))), 1)
        self.kuma_status, self.kuma_payload = 200, {"ok": True}
        await self.flush_twitter()
        await self.flush_twitter()
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["down"])

    async def test_kuma_healthy_heartbeat_repeats_per_collection_without_queue_growth(self):
        await self.enable_twitter()
        for _ in range(3):
            await self.rss.auto_update_func()
        async with self.sessions() as session:
            self.assertEqual(len(list(await session.scalars(select(self.models.RSSSourceNotice)))), 1)
        await self.flush_twitter()
        await self.flush_twitter()
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["up"])
        await self.rss.auto_update_func()
        await self.flush_twitter()
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["up", "up"])

    async def test_unconfigured_kuma_only_records_source_state(self):
        await self.enable_twitter()
        self.feed = {"entries": [], "error": "limited", "rate_limited": True}
        with patch.object(self.rss.config, "ut_url", None):
            await self.rss.auto_update_func()
            await self.flush_twitter()
        async with self.sessions() as session:
            self.assertFalse((await session.get(self.models.RSSSourceStatus, "twitter")).available)
            self.assertEqual(list(await session.scalars(select(self.models.RSSSourceNotice))), [])
        self.assertEqual(self.kuma_requests, [])
        self.assertEqual(self.bot.sent, [])

    async def test_kuma_ack_does_not_delete_a_new_observation_merged_during_request(self):
        await self.enable_twitter()
        await self.rss.auto_update_func()

        async def collect_during_request():
            self.kuma_before_receive = None
            await self.rss._observe_twitter(True)

        self.kuma_before_receive = collect_during_request
        await self.flush_twitter()
        async with self.sessions() as session:
            pending = list(await session.scalars(select(self.models.RSSSourceNotice)))
        self.assertEqual(len(pending), 1, "旧HTTP响应不能删除发送期间产生的新观测")
        await self.flush_twitter()
        self.assertEqual([row["status"] for row in self.kuma_accepted], ["up", "up"])
        async with self.sessions() as session:
            self.assertEqual(list(await session.scalars(select(self.models.RSSSourceNotice))), [])

    async def test_twitter_service_failures_keep_longest_retry_after(self):
        for count in (1, 3):
            with self.subTest(accounts=count):
                # 单账号轮末失败和多账号熔断都必须保留之前响应的最长 Retry-After。
                if count == 1:
                    await self.enable_twitter()
                else:
                    async with self.sessions.begin() as session:
                        state = await session.get(self.models.RSSSourceStatus, "twitter")
                        state.retry_at = None
                        session.add_all(self.models.User(User_ID=f"other-{i}", User_Name="其他", Plantform="test") for i in range(2))
                with patch.object(self.functions, "fetch_feed", AsyncMock(side_effect=[
                    {"entries": [], "error": "unavailable", "status_code": 503,
                     "retry_after": 3600 if i == 0 else 0} for i in range(count)
                ])):
                    await self.rss.auto_update_func()
                async with self.sessions() as session:
                    state = await session.get(self.models.RSSSourceStatus, "twitter")
                    seconds = (state.retry_at - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()
                self.assertGreater(seconds, 3590)

    async def test_twitter_notice_database_failure_does_not_stop_other_platforms(self):
        await self.enable_twitter()
        async with self.sessions.begin() as session:
            session.add(self.models.Plantform(name="bilibili", url="/bilibili/user/", need_trans="0"))
            session.add(self.models.User(User_ID="zzz-bili", User_Name="B站", Plantform="bilibili"))
            await session.execute(text("CREATE TRIGGER fail_notice BEFORE INSERT ON rss_source_notice "
                                       "BEGIN SELECT RAISE(FAIL, 'simulated notice DB failure'); END"))
        with patch.object(self.functions, "fetch_feed", AsyncMock(side_effect=lambda url:
            self.feed if "/bilibili/" in url else {"entries": [], "error": "limited", "rate_limited": True}
        )):
            await self.rss.auto_update_func()
        async with self.sessions() as session:
            cached = list((await session.scalars(select(self.models.Content))).all())
        self.assertEqual([row.username for row in cached], ["B站"])

    async def test_cached_snapshot_preserves_enclosures_when_translation_is_added(self):
        from nsy.plugins.rssget import format_json

        await self.seed()
        async with self.sessions.begin() as session:
            (await session.get(self.models.Plantform, "test")).need_trans = "1"
        self.feed = feedparser.parse(RSS_FEED.replace(
            "</item>", '<enclosure url="https://example.com/attachment.jpg" type="image/jpeg" /></item>',
        ))
        with patch.object(format_json.PLATFORMS[0], "main", AsyncMock(return_value="译文")):
            await self.run_scheduled()
        self.assertEqual([message.type for _, message in self.bot.sent], ["markdown", "file_image"])
        async with self.sessions() as session:
            cached = list((await session.scalars(select(self.models.Content))).all())
        self.assertIn("https://example.com/attachment.jpg", cached[0].images)

    async def test_full_cache_preserves_translation_and_only_translates_delivered_articles(self):
        from nsy.plugins.rssget import format_json

        await self.seed(push_limit=1)
        async with self.sessions.begin() as session:
            platform = await session.get(self.models.Plantform, "test")
            platform.need_trans = "1"
        older = dict(self.feed.entries[0], id="older", guid="older", link="https://example.com/older")
        self.feed.entries.append(older)
        translator = AsyncMock()
        translator.main.return_value = "保留译文"
        with patch.dict(format_json.PLATFORMS, {format_json.TRANS_PLATFORM: translator}):
            await self.rss.R.handle_rss("account", ["group-a"], await self._group_configs())
            await self.rss.R.handle_rss("account", ["group-a"], await self._group_configs())
        async with self.sessions() as session:
            cached = list((await session.scalars(select(self.models.Content))).all())
        self.assertEqual(len(cached), 2)
        self.assertEqual([row.trans_text for row in cached if row.link.endswith("post-1")], ["保留译文"])
        self.assertEqual([row.trans_text for row in cached if row.link.endswith("older")], [None])
        self.assertEqual(translator.main.await_count, 1)
        self.assertEqual(len(self.bot.sent), 1)

    async def _group_configs(self):
        async with self.sessions() as session:
            return await self.rss.GroupconfigManager.get_all_configs(session)


if __name__ == "__main__":
    unittest.main()
