"""独立采集快照迁移不能修改文章库存或群推送记录。"""

import importlib.util
from pathlib import Path
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


class RSSFeedMigrationTests(unittest.TestCase):
    def test_upgrade_and_downgrade_preserve_article_and_delivery_history(self):
        path = Path(__file__).resolve().parents[1] / "nsy/plugins/rssget/migrations/c2a6e8f102b3_rss_feed_cache.py"
        spec = importlib.util.spec_from_file_location("rss_feed_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE Content (id TEXT PRIMARY KEY, images TEXT)"))
            connection.execute(text("CREATE TABLE Detail (id TEXT PRIMARY KEY, summary TEXT)"))
            connection.execute(text("INSERT INTO Content VALUES ('article', 'original-url')"))
            connection.execute(text("INSERT INTO Detail VALUES ('article-group', 'delivered')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade("other-bind")
                self.assertNotIn("rss_feed_cache", inspect(connection).get_table_names())
                migration.upgrade()
                connection.execute(text("INSERT INTO rss_feed_cache VALUES ('account', '[]', 'digest', '2026-11-19 01:00:00')"))
                self.assertEqual(connection.scalar(text("SELECT account_id FROM rss_feed_cache")), "account")
                migration.downgrade()
            self.assertEqual(connection.execute(text("SELECT * FROM Content")).all(), [("article", "original-url")])
            self.assertEqual(connection.execute(text("SELECT * FROM Detail")).all(), [("article-group", "delivered")])


if __name__ == "__main__":
    unittest.main()
