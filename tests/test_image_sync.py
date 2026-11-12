"""内部图片 API、Content 同步索引与历史迁移的集成测试。"""

import asyncio
import importlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
import nonebot
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rss_test_support import load_rss_plugin


class ImageSyncTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.TemporaryDirectory(prefix="nsybot-image-sync-")
        load_rss_plugin(cls.root.name)

    @classmethod
    def tearDownClass(cls):
        cls.root.cleanup()

    async def asyncSetUp(self):
        from nsy.plugins.rssget import models

        self.models = models
        self.cache = importlib.import_module("nsy.plugins.rssget.update_text")
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.root.name}/{uuid4().hex}.db")
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as connection:
            await connection.run_sync(models.Model.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        patcher = patch.object(self.cache, "get_session", self.sessions)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def store(self, article_id, **values):
        content = dict(id=article_id, username="测试作者", title="图片推文", time="2026-11-12 12:34",
                       link="https://x.com/example/status/1234567890", text="正文", trans_text=None,
                       images=["https://pbs.twimg.com/media/a.jpg?name=orig"])
        content.update(values)
        self.assertTrue(await self.cache.update_text(content))

    async def client(self, enabled=True):
        api = importlib.import_module("nsy.plugins.rssget.image_sync")
        from nsy.plugins.rssget.config import Config

        for patcher in (
            patch.object(api, "get_session", self.sessions),
            patch.object(api, "config", Config(rss_image_sync_enabled=enabled, rss_image_sync_token="test-token")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=nonebot.get_app()), base_url="http://internal",
                                   headers={"Authorization": "Bearer test-token"})
        self.addAsyncCleanup(client.aclose)
        return client

    async def test_image_index_is_atomic_unique_and_translation_is_preserved(self):
        await self.store("one", trans_text="已有译文")
        await self.store("one")
        async with self.sessions() as session:
            tables = await session.run_sync(lambda s: inspect(s.bind).get_table_names())
            self.assertIn("rss_image_sync", tables, "图片文章需要稳定增量序号")
            self.assertEqual(await session.scalar(text("SELECT count(*) FROM rss_image_sync")), 1)
            self.assertEqual((await session.get(self.models.Content, "one")).trans_text, "已有译文")

    async def test_pagination_retries_tail_polling_and_late_old_post(self):
        client = await self.client()
        await self.store("one", images=["https://example.com/a.jpg", "https://example.com/a.jpg"])
        await self.store("text-only", images=[])
        await self.store("two")
        response = await client.get("/internal/v1/images", params={"cursor": "0", "limit": 1})
        self.assertEqual(response.status_code, 200, response.text)
        first = response.json()
        self.assertTrue(first["has_more"])
        self.assertEqual([row["id"] for row in first["items"]], ["one"])
        self.assertEqual(first["items"][0]["images"], ["https://example.com/a.jpg"])
        self.assertEqual(first["items"][0]["tweet_id"], "1234567890")
        self.assertEqual(first["items"][0]["author"], "测试作者")
        self.assertEqual(first["items"][0]["author_handle"], "example")
        self.assertEqual(first["items"][0]["published_at"], "2026-11-12T12:34:00+08:00")
        self.assertEqual((await client.get("/internal/v1/images", params={"cursor": "0", "limit": 1})).json(), first)
        second = (await client.get("/internal/v1/images", params={"cursor": first["next_cursor"], "limit": 1})).json()
        self.assertEqual([row["id"] for row in second["items"]], ["two"])
        self.assertFalse(second["has_more"])
        tail = second["next_cursor"]
        empty = (await client.get("/internal/v1/images", params={"cursor": tail})).json()
        self.assertEqual(empty, {"items": [], "next_cursor": tail, "has_more": False})
        await self.store("late", time="2020-01-01 00:00")
        new = (await client.get("/internal/v1/images", params={"cursor": tail})).json()
        self.assertEqual([row["id"] for row in new["items"]], ["late"])
        replay = (await client.get("/internal/v1/images")).json()
        self.assertEqual([row["id"] for row in replay["items"]], ["one", "two", "late"])

    async def test_authentication_and_disabled_api_fail_closed(self):
        client = await self.client()
        client.headers.pop("Authorization")
        for auth in (None, "", "Basic test-token", "Bearer wrong", "Bearer", "Bearer test-token extra", "Bearer 测试"):
            with self.subTest(auth=auth):
                headers = {} if auth is None else {"Authorization": auth.encode()}
                response = await client.get("/internal/v1/images", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")
        api = importlib.import_module("nsy.plugins.rssget.image_sync")
        with patch.object(api.config, "rss_image_sync_enabled", False):
            self.assertEqual((await client.get("/internal/v1/images")).status_code, 404)

    async def test_invalid_cursors_and_page_sizes_are_rejected(self):
        client = await self.client()
        for params in ({"cursor": "-1"}, {"cursor": "1.5"}, {"cursor": "abc"}, {"cursor": "01"},
                       {"cursor": "9223372036854775808"}, {"limit": 0}, {"limit": 201}):
            with self.subTest(params=params):
                self.assertEqual((await client.get("/internal/v1/images", params=params)).status_code, 422)

    async def test_reads_do_not_mutate_database_and_unknown_dates_remain_visible(self):
        client = await self.client()
        await self.store("unknown", time="未知时间", link="https://example.com/post")

        def read_only(connection, cursor, statement, parameters, context, executemany):
            self.assertTrue(statement.lstrip().upper().startswith("SELECT"), "拉取 API 只能读取数据库")

        event.listen(self.engine.sync_engine, "before_cursor_execute", read_only)
        self.addCleanup(event.remove, self.engine.sync_engine, "before_cursor_execute", read_only)
        payload = (await client.get("/internal/v1/images")).json()
        self.assertEqual(payload["items"][0]["published_at"], None)
        self.assertEqual(payload["items"][0]["published_at_raw"], "未知时间")
        self.assertIsNone(payload["items"][0]["tweet_id"])
        self.assertNotIn("/internal/v1/images", nonebot.get_app().openapi()["paths"])

    async def test_concurrent_duplicate_writes_allocate_one_sequence(self):
        await asyncio.gather(self.store("shared"), self.store("shared"))
        client = await self.client()
        payload = (await client.get("/internal/v1/images")).json()
        self.assertEqual([row["id"] for row in payload["items"]], ["shared"])

    async def test_index_failure_rolls_back_content_and_allows_later_retry(self):
        async with self.engine.begin() as connection:
            await connection.execute(text("CREATE TRIGGER fail_image_index BEFORE INSERT ON rss_image_sync "
                                          "BEGIN SELECT RAISE(ABORT, 'index unavailable'); END"))
        self.assertFalse(await self.cache.update_text({"id": "retry", "images": ["https://example.com/a.jpg"]}))
        async with self.sessions() as session:
            self.assertIsNone(await session.get(self.models.Content, "retry"))
        async with self.engine.begin() as connection:
            await connection.execute(text("DROP TRIGGER fail_image_index"))
        await self.store("retry")
        client = await self.client()
        self.assertEqual([row["id"] for row in (await client.get("/internal/v1/images")).json()["items"]], ["retry"])

    async def test_text_post_can_gain_images_before_first_sync(self):
        await self.store("text", images=[])
        client = await self.client()
        self.assertEqual((await client.get("/internal/v1/images")).json()["items"], [])
        await self.store("text")
        self.assertEqual([row["id"] for row in (await client.get("/internal/v1/images")).json()["items"]], ["text"])

    async def test_enabled_api_requires_nonempty_token(self):
        from nsy.plugins.rssget.config import Config

        for token in (None, "", "  "):
            with self.subTest(token=token), self.assertRaises(ValueError):
                Config(rss_image_sync_enabled=True, rss_image_sync_token=token)


class ImageSyncMigrationTests(unittest.TestCase):
    def test_backfill_preserves_content_and_delivery_records_and_never_reuses_sequence(self):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        directory = Path(__file__).resolve().parents[1] / "nsy/plugins/rssget/migrations"
        path = directory / "8d0e4a6b9c12_image_sync.py"
        self.assertTrue(path.is_file(), "需要历史图片索引回填迁移")
        spec = importlib.util.spec_from_file_location("image_sync_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE Content (id VARCHAR PRIMARY KEY, images TEXT)"))
            connection.execute(text("CREATE TABLE Detail (id VARCHAR PRIMARY KEY)"))
            connection.execute(text("INSERT INTO Detail VALUES ('delivered-group-a')"))
            connection.execute(text("INSERT INTO Content VALUES (:id, :images)"), [
                {"id": "a", "images": "['https://example.com/a.jpg']"},
                {"id": "b", "images": '["https://example.com/b.jpg"]'},
                {"id": "text", "images": None},
                {"id": "empty", "images": "[]"},
            ])
            before = connection.execute(text("SELECT * FROM Content ORDER BY id")).all()
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                self.assertEqual(connection.execute(text("SELECT content_id FROM rss_image_sync ORDER BY seq")).scalars().all(), ["a", "b"])
                connection.execute(text("DELETE FROM rss_image_sync WHERE seq=2"))
                connection.execute(text("INSERT INTO rss_image_sync (content_id) VALUES ('empty')"))
                self.assertEqual(connection.scalar(text("SELECT max(seq) FROM rss_image_sync")), 3)
                migration.downgrade()
            self.assertEqual(connection.execute(text("SELECT * FROM Content ORDER BY id")).all(), before)
            self.assertEqual(connection.execute(text("SELECT * FROM Detail")).scalars().all(), ["delivered-group-a"])


if __name__ == "__main__":
    unittest.main()
