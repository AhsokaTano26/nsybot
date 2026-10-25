"""机器人当前群登记表的事务、事件时间和一次性历史补录测试。"""

import asyncio
import importlib
import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, delete, inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rss_test_support import load_rss_plugin


RSS_ROOT = Path(__file__).resolve().parents[1] / "nsy/plugins/rssget"
MIGRATIONS = RSS_ROOT / "migrations"
MIGRATION = "7c6b8d2e40a1_bot_group_registry.py"
UTC = timezone.utc
BEIJING = timezone(timedelta(hours=8))


def load_migration(filename):
    path = MIGRATIONS / filename
    spec = importlib.util.spec_from_file_location(f"rss_registry_migration_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BotGroupRegistryStoreTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin_root = tempfile.TemporaryDirectory(prefix="nsybot-registry-plugin-")
        load_rss_plugin(cls.plugin_root.name)
        from nsy.plugins.rssget import models
        cls.models = models

    @classmethod
    def tearDownClass(cls):
        cls.plugin_root.cleanup()

    async def asyncSetUp(self):
        self.database_root = tempfile.TemporaryDirectory(prefix="nsybot-registry-store-")
        self.addCleanup(self.database_root.cleanup)
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.database_root.name}/registry.sqlite3"
        )
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as connection:
            await connection.run_sync(self.models.Model.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    def manager(self):
        self.assertTrue((RSS_ROOT / "group_registry.py").is_file(), "需要独立的群登记存储管理器")
        return importlib.import_module("nsy.plugins.rssget.group_registry").BotGroupManager

    async def test_join_uses_actual_event_time_and_never_regresses_known_times(self):
        manager = self.manager()
        before = datetime.now(UTC).replace(tzinfo=None)
        async with self.sessions() as session:
            await manager.record_join(session, "group-a", datetime(2026, 10, 20, 18, tzinfo=BEIJING))
            row = await session.get(self.models.BotGroup, "group-a")
            recorded = row.recorded_at
            self.assertEqual(row.joined_at, datetime(2026, 10, 20, 10))
            self.assertEqual(row.last_seen_at, datetime(2026, 10, 20, 10))
            self.assertEqual(row.source, "join")
            self.assertLessEqual(before, recorded)
            self.assertLessEqual(recorded, datetime.now(UTC).replace(tzinfo=None))

            for stamp in (datetime(2026, 10, 20, 10), datetime(2026, 10, 19), datetime(2026, 10, 21, 11)):
                await manager.record_join(session, "group-a", stamp)
            await manager.observe(session, "group-a", datetime(2026, 10, 22, 20, tzinfo=BEIJING))
            await manager.record_join(session, "group-a", datetime(2026, 10, 21))
            self.assertEqual(row.joined_at, datetime(2026, 10, 21, 11))
            self.assertEqual(row.last_seen_at, datetime(2026, 10, 22, 12))
            self.assertEqual(row.recorded_at, recorded)
            self.assertEqual(row.source, "join")
            self.assertEqual(await manager.ids(session), {"group-a"})

    async def test_observing_history_confirms_membership_without_inventing_join_time(self):
        manager = self.manager()
        historical_recorded = datetime(2026, 10, 1, 3, 4, 5)
        async with self.sessions() as session:
            row = self.models.BotGroup(
                group_openid="history", joined_at=None, recorded_at=historical_recorded,
                last_seen_at=None, source="history",
            )
            session.add(row)
            await session.flush()
            await manager.observe(session, "history", datetime(2026, 10, 23, 15, tzinfo=BEIJING))
            self.assertIsNone(row.joined_at)
            self.assertEqual(row.source, "message")
            self.assertEqual(row.last_seen_at, datetime(2026, 10, 23, 7))
            self.assertEqual(row.recorded_at, historical_recorded)
            await manager.observe(session, "history", datetime(2026, 10, 22))
            await manager.record_join(session, "history", datetime(2026, 10, 20, 9, tzinfo=UTC))
            self.assertEqual(row.joined_at, datetime(2026, 10, 20, 9))
            self.assertEqual(row.last_seen_at, datetime(2026, 10, 23, 7))
            self.assertEqual(row.recorded_at, historical_recorded)
            self.assertEqual(row.source, "join")

    async def test_first_message_defaults_to_current_utc_and_preserves_registration_time(self):
        manager = self.manager()
        before = datetime.now(UTC).replace(tzinfo=None)
        async with self.sessions() as session:
            await manager.observe(session, "message-only")
            row = await session.get(self.models.BotGroup, "message-only")
            after = datetime.now(UTC).replace(tzinfo=None)
            self.assertIsNone(row.joined_at)
            self.assertEqual(row.source, "message")
            self.assertLessEqual(before, row.recorded_at)
            self.assertLessEqual(row.recorded_at, after)
            self.assertLessEqual(before, row.last_seen_at)
            self.assertLessEqual(row.last_seen_at, after)
            recorded, last_seen = row.recorded_at, row.last_seen_at
            await manager.observe(session, "message-only", datetime(2020, 1, 1))
            self.assertEqual(row.recorded_at, recorded)
            self.assertEqual(row.last_seen_at, last_seen)

    async def test_registration_flushes_without_committing_callers_transaction(self):
        manager = self.manager()
        async with self.sessions() as session:
            await manager.record_join(session, "rolled-back-join", datetime(2026, 10, 20))
            await manager.observe(session, "rolled-back-message", datetime(2026, 10, 21))
            self.assertEqual(await manager.ids(session), {"rolled-back-join", "rolled-back-message"})
            async with self.sessions() as observer:
                self.assertEqual(await manager.ids(observer), set())
            await session.rollback()
        async with self.sessions() as observer:
            self.assertEqual(await manager.ids(observer), set())

    async def test_remove_can_rollback_with_related_cleanup_and_does_not_backfill_again(self):
        manager = self.manager()
        async with self.sessions.begin() as session:
            session.add(self.models.Subscribe(id="account-history", username="account", group="history"))
            await manager.observe(session, "history", datetime(2026, 10, 20))
        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            async with self.sessions.begin() as session:
                self.assertTrue(await manager.remove(session, "history"))
                await session.execute(delete(self.models.Subscribe).where(self.models.Subscribe.group == "history"))
                raise RuntimeError("cleanup failed")
        async with self.sessions() as session:
            self.assertEqual(await manager.ids(session), {"history"})
            self.assertIsNotNone(await session.get(self.models.Subscribe, "account-history"))
        async with self.sessions.begin() as session:
            self.assertTrue(await manager.remove(session, "history"))
            self.assertFalse(await manager.remove(session, "history"))
        async with self.sessions() as session:
            self.assertEqual(await manager.ids(session), set())
            self.assertEqual(await manager.page(session), (0, []))
            self.assertIsNotNone(await session.get(self.models.Subscribe, "account-history"))

    async def test_rejoin_after_removal_creates_a_new_membership(self):
        manager = self.manager()
        async with self.sessions.begin() as session:
            await manager.record_join(session, "returning", datetime(2026, 10, 1))
            original = await session.get(self.models.BotGroup, "returning")
            first_recorded = original.recorded_at
        async with self.sessions.begin() as session:
            self.assertTrue(await manager.remove(session, "returning"))
        async with self.sessions.begin() as session:
            await manager.record_join(session, "returning", datetime(2026, 10, 25, 18, tzinfo=BEIJING))
            row = await session.get(self.models.BotGroup, "returning")
            self.assertEqual(row.joined_at, datetime(2026, 10, 25, 10))
            self.assertEqual(row.last_seen_at, datetime(2026, 10, 25, 10))
            self.assertGreater(row.recorded_at, first_recorded)
            self.assertEqual(row.source, "join")

    async def test_ids_and_pages_use_independent_registry_with_stable_group_order(self):
        manager = self.manager()
        async with self.sessions() as session:
            session.add(self.models.Subscribe(id="untracked", username="account", group="legacy-only"))
            for group in ("z", "a", "m", "b", "n"):
                await manager.observe(session, group, datetime(2026, 10, 25))
            self.assertEqual(await manager.ids(session), {"a", "b", "m", "n", "z"})
            total, rows = await manager.page(session, page=2, page_size=2)
            self.assertEqual(total, 5)
            self.assertEqual([row.group_openid for row in rows], ["m", "n"])
            self.assertEqual((await manager.page(session, page=4, page_size=2)), (5, []))
            self.assertEqual([row.group_openid for row in (await manager.page(session))[1]], ["a", "b", "m", "n", "z"])

    async def test_simultaneous_first_observations_and_join_do_not_lose_evidence(self):
        manager = self.manager()
        start = asyncio.Event()

        async def register(index):
            await start.wait()
            async with self.sessions.begin() as session:
                if index in (2, 5):
                    await manager.record_join(session, "concurrent", datetime(2026, 10, 20 + index))
                else:
                    await manager.observe(session, "concurrent", datetime(2026, 10, 20 + index))

        pending = [asyncio.create_task(register(index)) for index in range(8)]
        start.set()
        await asyncio.wait_for(asyncio.gather(*pending), timeout=15)
        async with self.sessions() as session:
            self.assertEqual(await manager.ids(session), {"concurrent"})
            row = await session.get(self.models.BotGroup, "concurrent")
            self.assertEqual(row.joined_at, datetime(2026, 10, 25))
            self.assertEqual(row.last_seen_at, datetime(2026, 10, 27))
            self.assertEqual(row.source, "join")


class BotGroupRegistryMigrationTests(unittest.TestCase):
    def migration(self):
        self.assertTrue((MIGRATIONS / MIGRATION).is_file(), "群登记需要独立的一次性迁移")
        return load_migration(MIGRATION)

    def legacy(self, connection):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            load_migration("1b51e394adf2_init.py").upgrade()
            load_migration("76942fe5b1a4_group_openid.py").upgrade()
            load_migration("2f7a9d8136c0_group_push_limit.py").upgrade()
        return context

    def test_upgrade_unions_history_without_changing_legacy_data_and_downgrade_only_drops_registry(self):
        from alembic.operations import Operations
        migration = self.migration()
        self.assertEqual(migration.down_revision, "2f7a9d8136c0")
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            context = self.legacy(connection)
            connection.execute(text("CREATE TABLE birthday_group (group_id VARCHAR(255) PRIMARY KEY, group_name VARCHAR(40), birthday_type INTEGER)"))
            connection.execute(text("INSERT INTO Subscribe VALUES ('s1', 'one', 'shared'), ('s2', 'two', 'subscription-only'), ('s3', 'three', 'shared'), ('empty', 'empty', ''), ('null', 'null', NULL), ('spaces', 'spaces', '   ')"))
            connection.execute(text("INSERT INTO Group_config VALUES ('shared', 1, 0, 1, 0, 1, 5), ('config-only', 0, 1, 0, 1, 0, 0), ('', 1, 0, 1, 0, 1, 1)"))
            connection.execute(text("INSERT INTO birthday_group VALUES ('shared', '共享', 1), ('birthday-only', '生日群', 2), ('', '空', 1)"))
            connection.execute(text("INSERT INTO Detail VALUES ('article', 'title', '2026-10-25 12:30:00')"))
            connection.execute(text("INSERT INTO Content (id, text) VALUES ('article', 'full original')"))
            original_tables = inspect(connection).get_table_names()
            original_rows = {table: connection.execute(text(f'SELECT * FROM "{table}"')).all() for table in original_tables}
            before = datetime.now(UTC).replace(tzinfo=None)
            with Operations.context(context):
                migration.upgrade()
            after = datetime.now(UTC).replace(tzinfo=None)
            rows = connection.execute(text("SELECT group_openid, joined_at, recorded_at, last_seen_at, source FROM bot_group ORDER BY group_openid")).all()
            self.assertEqual([row.group_openid for row in rows], ["birthday-only", "config-only", "shared", "subscription-only"])
            for row in rows:
                self.assertIsNone(row.joined_at)
                self.assertIsNone(row.last_seen_at)
                self.assertEqual(row.source, "history")
                recorded = datetime.fromisoformat(row.recorded_at)
                self.assertIsNone(recorded.tzinfo)
                self.assertLessEqual(before, recorded)
                self.assertLessEqual(recorded, after)
            self.assertEqual(len({row.recorded_at for row in rows}), 1)
            for table in original_tables:
                self.assertEqual(connection.execute(text(f'SELECT * FROM "{table}"')).all(), original_rows[table])
            with Operations.context(context):
                migration.downgrade()
            self.assertEqual(inspect(connection).get_table_names(), original_tables)
            for table in original_tables:
                self.assertEqual(connection.execute(text(f'SELECT * FROM "{table}"')).all(), original_rows[table])

    def test_upgrade_works_when_birthday_plugin_table_is_absent(self):
        from alembic.operations import Operations
        migration = self.migration()
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            context = self.legacy(connection)
            connection.execute(text("INSERT INTO Subscribe VALUES ('account-group', 'account', 'rss-only')"))
            with Operations.context(context):
                migration.upgrade()
            self.assertEqual(connection.execute(text("SELECT group_openid FROM bot_group")).scalars().all(), ["rss-only"])
            self.assertNotIn("birthday_group", inspect(connection).get_table_names())

    def test_upgrade_on_empty_legacy_sources_creates_empty_registry_and_respects_bind_name(self):
        from alembic.operations import Operations
        migration = self.migration()
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            context = self.legacy(connection)
            with Operations.context(context):
                migration.upgrade("other-bind")
            self.assertNotIn("bot_group", inspect(connection).get_table_names())
            with Operations.context(context):
                migration.upgrade()
                migration.downgrade("other-bind")
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM bot_group")), 0)
            columns = {column["name"]: column for column in inspect(connection).get_columns("bot_group")}
            self.assertFalse(columns["recorded_at"]["nullable"])
            self.assertFalse(columns["source"]["nullable"])
            self.assertTrue(columns["joined_at"]["nullable"])
            self.assertTrue(columns["last_seen_at"]["nullable"])
            self.assertEqual(inspect(connection).get_pk_constraint("bot_group")["constrained_columns"], ["group_openid"])


if __name__ == "__main__":
    unittest.main()
