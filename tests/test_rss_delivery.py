"""从定时任务到 QQ 发送与去重记录的集成回归测试。"""

import tempfile
import unittest
import importlib
import asyncio
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import feedparser
from sqlalchemy import select
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
        self.fail_image_notice = False
        self.before_send = None
        self.sent = []

    async def send_to_group(self, *, group_openid, message):
        if self.before_send:
            await self.before_send()
        if (group_openid in self.failed_groups or message.type in self.failed_types
                or (self.fail_image_notice and "图片附件" in str(message))):
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
            patch.object(functions, "_msg_semaphore", asyncio.Semaphore(3)),
            patch.object(self.rss, "get_session", self.sessions),
            patch.object(functions, "get_session", self.sessions),
            patch.object(update_text, "get_session", self.sessions),
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

    async def seed(self, groups=("group-a",)):
        async with self.sessions.begin() as session:
            session.add(self.models.Plantform(name="test", url="/test/", need_trans="0"))
            session.add(self.models.User(User_ID="account", User_Name="测试", Plantform="test"))
            for group in groups:
                session.add(self.models.Subscribe(
                    id=f"account-{group}", username="account", group=group,
                ))

    async def run_scheduled(self):
        jobs = [job for job in self.rss.scheduler.get_jobs() if job.func == self.rss.auto_update_func]
        self.assertEqual(len(jobs), 1, "RSS 定时任务应注册一次")
        await jobs[0].func()

    async def details(self):
        async with self.sessions() as session:
            return list((await session.scalars(select(self.models.Detail).where(
                ~self.models.Detail.id.startswith("rss-init:"),
            ))).all())

    async def test_send_text_honors_both_image_count_settings(self):
        content = {
            "username": "测试", "text": "正文", "time": "2026-10-13 20:00",
            "link": "https://example.com/post", "images": ["https://example.com/image.jpg"],
        }
        for enabled, expected_messages in ((False, 2), (True, 3)):
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
                self.assertEqual(len(self.bot.sent), expected_messages)
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

    async def test_image_count_notice_failure_does_not_replay_delivered_body(self):
        await self.seed()
        self.feed.entries[0]["summary"] += '<img src="https://example.com/image.jpg">'
        self.bot.fail_image_notice = True
        await self.run_scheduled()
        self.assertEqual(len(await self.details()), 1)
        self.assertEqual(len([message for _, message in self.bot.sent if message.type == "file_image"]), 1)
        await self.run_scheduled()
        self.assertEqual(len([message for _, message in self.bot.sent if "第一篇正文" in str(message)]), 1)

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

    async def test_new_subscription_keeps_first_three_then_checks_all_future_updates(self):
        await self.seed()
        for index in range(2, 8):
            self.feed.entries.append(feedparser.parse(RSS_FEED.replace("post-1", f"post-{index}")).entries[0])
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 3)
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 3, "初次订阅的较旧文章不应以后突然补发")
        for index in range(8, 12):
            self.feed.entries.insert(0, feedparser.parse(RSS_FEED.replace("post-1", f"post-{index}")).entries[0])
        await self.run_scheduled()
        self.assertEqual(len(self.bot.sent), 7)

    async def test_failed_initial_article_can_retry_after_sliding_out_of_first_three(self):
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
            session.add(self.models.Detail(id="legacy-post-group-a", summary="旧文章"))
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

    async def test_new_group_after_established_restart_still_gets_latest_articles(self):
        await self.seed()
        await self.run_scheduled()
        async with self.sessions.begin() as session:
            session.add(self.models.Subscribe(id="account-group-b", username="account", group="group-b"))
        self.functions.config.if_first_time_start = True
        await self.run_scheduled()
        self.assertIn("group-b", [group for group, _ in self.bot.sent])

    async def test_self_repost_filter_takes_precedence_over_forward_filter(self):
        await self.seed()
        self.feed.entries[0]["title"] = "RT 测试：自己的引用"
        self.feed.entries[0]["summary"] = '<div class="rsshub-quote">自己的引用</div>'
        await self.run_scheduled()
        self.assertEqual(self.bot.sent, [])

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

        await self.seed(("group-a", "group-b"))
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
        await self.seed()
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
        await self.seed()
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


if __name__ == "__main__":
    unittest.main()
