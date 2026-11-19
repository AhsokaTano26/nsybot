"""补偿队列迁移必须支持持久化和到期索引，并保留历史业务表。"""

import importlib.util
from pathlib import Path
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


class RSSIngestMigrationTests(unittest.TestCase):
    def test_ingest_queue_migration_preserves_articles_cursors_and_delivery(self):
        path = Path(__file__).resolve().parents[1] / "nsy/plugins/rssget/migrations/e5f8b2c3d014_rss_ingest_queue.py"
        spec = importlib.util.spec_from_file_location("rss_ingest_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.assertEqual(migration.down_revision, "d4e7a1b2c903")
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            tables = ("Content", "Detail", "rss_image_sync", "rss_feed_cache", "rss_source_status")
            for table in tables:
                connection.execute(text(f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY)'))
                connection.execute(text(f'INSERT INTO "{table}" VALUES (\'existing\')'))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade("other-bind")
                self.assertNotIn("rss_ingest_queue", inspect(connection).get_table_names())
                migration.upgrade()
                indexes = inspect(connection).get_indexes("rss_ingest_queue")
                self.assertIn(["next_retry_at"], [index["column_names"] for index in indexes])
                connection.execute(text("INSERT INTO rss_ingest_queue VALUES "
                    "('article','author','{}','version',2,'2026-11-20','2026-11-19','DatabaseWriteError')"))
                self.assertEqual(connection.scalar(text("SELECT attempts FROM rss_ingest_queue")), 2)
                migration.downgrade()
            self.assertNotIn("rss_ingest_queue", inspect(connection).get_table_names())
            for table in tables:
                self.assertEqual(connection.scalar(text(f'SELECT id FROM "{table}"')), "existing")
