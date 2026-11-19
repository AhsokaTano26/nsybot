"""采集状态和通知队列的迁移必须保留现有文章、推送和快照。"""

import importlib.util
from pathlib import Path
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


class RSSSourceMigrationTests(unittest.TestCase):
    def test_health_tables_upgrade_and_downgrade_without_touching_history(self):
        path = Path(__file__).resolve().parents[1] / "nsy/plugins/rssget/migrations/d4e7a1b2c903_rss_source_health.py"
        spec = importlib.util.spec_from_file_location("rss_source_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.assertEqual(migration.down_revision, "c2a6e8f102b3")
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            for table in ("Content", "Detail", "rss_feed_cache"):
                connection.execute(text(f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY)'))
                connection.execute(text(f'INSERT INTO "{table}" VALUES (\'existing\')'))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade("other-bind")
                self.assertNotIn("rss_source_status", inspect(connection).get_table_names())
                migration.upgrade()
                connection.execute(text("INSERT INTO rss_source_status VALUES ('twitter', 0, '2026-11-19', '2026-11-20')"))
                connection.execute(text("INSERT INTO rss_source_notice (source, available, observed_at) VALUES ('twitter', 0, '2026-11-19')"))
                self.assertEqual(connection.scalar(text("SELECT id FROM rss_source_notice")), 1)
                migration.downgrade()
            self.assertNotIn("rss_source_status", inspect(connection).get_table_names())
            self.assertNotIn("rss_source_notice", inspect(connection).get_table_names())
            for table in ("Content", "Detail", "rss_feed_cache"):
                self.assertEqual(connection.scalar(text(f'SELECT id FROM "{table}"')), "existing")
