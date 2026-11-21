"""Byte and time budgets preserve raw work while keeping each tick bounded."""

import asyncio
from datetime import datetime, timedelta
import importlib
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rss_test_support import load_rss_plugin


class RSSQueueBudgetTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.TemporaryDirectory(prefix="nsybot-queue-budget-")
        load_rss_plugin(cls.root.name)

    @classmethod
    def tearDownClass(cls):
        cls.root.cleanup()

    async def asyncSetUp(self):
        from nsy.plugins.rssget import models
        self.models = models
        self.cache = importlib.import_module("nsy.plugins.rssget.update_text")
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as connection:
            await connection.run_sync(models.Model.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.limits = SimpleNamespace(rss_entry_max_bytes=1000, rss_ingest_retry_max_bytes=600,
                                     rss_ingest_retry_max_seconds=1)
        for patcher in (patch.object(self.cache,"get_session",self.sessions),
                        patch.object(self.cache,"config",self.limits,create=True),
                        patch.object(self.cache,"_ingest_lock",asyncio.Lock())):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def seed(self, article_id, size=300):
        now = datetime(2026,1,1)
        raw = json.dumps({"id":article_id,"title":article_id,"summary":"x"*size})
        async with self.sessions.begin() as session:
            session.add(self.models.RSSIngestQueue(id=article_id,username="author",entry=raw,
                version=article_id,attempts=0,next_retry_at=now,created_at=now))

    async def counts(self):
        async with self.sessions() as session:
            return (len(list(await session.scalars(select(self.models.Content)))),
                    len(list(await session.scalars(select(self.models.RSSIngestQueue)))))

    async def test_due_rows_obey_combined_payload_byte_budget(self):
        for name in ("a","b","c"):
            await self.seed(name)
        await self.cache.retry_pending_entries(100)
        self.assertEqual(await self.counts(), (1,2), "不能因条数未满就加载并处理超出字节预算的整批")

    async def test_oversized_raw_remains_queued_without_blocking_small_articles(self):
        await self.seed("a-large",3000)
        await self.seed("b-small",100)
        await self.seed("c-small",100)
        await self.cache.retry_pending_entries(100)
        self.assertEqual(await self.counts(), (2,1))
        async with self.sessions() as session:
            row = await session.get(self.models.RSSIngestQueue,"a-large")
            self.assertIn("x"*3000,row.entry)
            self.assertEqual(row.last_error,"EntryTooLarge")

    async def test_time_budget_leaves_unstarted_articles_due(self):
        from nsy.plugins.rssget.format_json import Format
        for name in ("a","b","c"):
            await self.seed(name,100)
        current = 0
        original = Format.extract_content
        async def slow(formatter,entry,translate):
            nonlocal current
            result = await original(formatter,entry,translate)
            current = 2
            return result
        with patch.object(self.cache,"monotonic",lambda:current,create=True), patch.object(Format,"extract_content",slow):
            await self.cache.retry_pending_entries(100)
        self.assertEqual(await self.counts(), (1,2))
        async with self.sessions() as session:
            remaining = list(await session.scalars(select(self.models.RSSIngestQueue)))
            self.assertTrue(all(row.attempts==0 for row in remaining))

    async def test_typed_write_reports_superseded_without_touching_content(self):
        from nsy.plugins.rssget.state_machines import WriteOutcome
        await self.seed("new")
        writer=getattr(self.cache,"write_content",None)
        self.assertTrue(callable(writer),"入库结果需要明确区分成功与版本被替代")
        result=await writer({"id":"new","images":[]},pending_version="old")
        self.assertIs(result,WriteOutcome.SUPERSEDED)
        self.assertEqual(await self.counts(),(0,1))
