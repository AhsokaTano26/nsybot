"""Image sync reads metadata without retaining an ORM session for serialization."""

from contextlib import asynccontextmanager
import importlib
import tempfile
import unittest
from unittest.mock import patch

from fastapi import Response
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rss_test_support import load_rss_plugin


class ImageSyncProjectionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.TemporaryDirectory(prefix="nsybot-image-projection-")
        load_rss_plugin(cls.root.name)

    @classmethod
    def tearDownClass(cls):
        cls.root.cleanup()

    async def asyncSetUp(self):
        from nsy.plugins.rssget.models import Content, ImageSync, Model

        self.api = importlib.import_module("nsy.plugins.rssget.image_sync")
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as connection:
            await connection.run_sync(Model.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions.begin() as session:
            session.add_all([
                Content(id="one", username="Author", title="unused title", time="2026-11-21 12:34",
                        link="https://x.com/example/status/123", images="['https://img/one.jpg']",
                        text="unused body" * 100_000, trans_text="unused translation" * 100_000),
                ImageSync(content_id="one"),
            ])

    async def test_query_projects_only_image_response_metadata(self):
        columns = []

        def capture_projection(connection, cursor, statement, parameters, context, executemany):
            if context.compiled is not None and context.compiled.statement.is_select:
                columns.append(set(context.compiled.statement.selected_columns.keys()))

        event.listen(self.engine.sync_engine, "before_cursor_execute", capture_projection)
        self.addCleanup(event.remove, self.engine.sync_engine, "before_cursor_execute", capture_projection)
        response = Response()
        with patch.object(self.api, "get_session", self.sessions):
            page = await self.api.list_images(response, cursor="0", limit=1)

        self.assertEqual(columns, [{"seq", "id", "username", "time", "link", "images"}])
        self.assertEqual(page.model_dump(), {
            "items": [{"seq": "1", "id": "one", "tweet_id": "123", "author": "Author",
                       "author_handle": "example", "published_at": "2026-11-21T12:34:00+08:00",
                       "published_at_raw": "2026-11-21 12:34", "link": "https://x.com/example/status/123",
                       "images": ["https://img/one.jpg"]}],
            "next_cursor": "1", "has_more": False,
        })
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_session_is_released_before_image_response_serialization(self):
        session_active = False
        serializer_session_states = []
        serialize = self.api.image_item

        @asynccontextmanager
        async def sessions():
            nonlocal session_active
            async with self.sessions() as session:
                session_active = True
                try:
                    yield session
                finally:
                    session_active = False

        def serialize_item(seq, content):
            serializer_session_states.append(session_active)
            return serialize(seq, content)

        with patch.object(self.api, "get_session", sessions), patch.object(self.api, "image_item", serialize_item):
            page = await self.api.list_images(Response(), cursor="0", limit=1)

        self.assertEqual(serializer_session_states, [False], "the DB connection must be free while building response models")
        self.assertEqual([item.id for item in page.items], ["one"])


if __name__ == "__main__":
    unittest.main()
