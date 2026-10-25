"""持久化群推送上限及每轮 RSS 窗口的回归测试。"""

import importlib.util
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rss_test_support import load_rss_plugin


GROUP_OPTIONS = {
    "if_need_trans": True,
    "if_need_self_trans": False,
    "if_need_translate": True,
    "if_need_photo_num_mention": False,
    "if_need_merged_message": True,
}
MIGRATIONS = Path(__file__).resolve().parents[1] / "nsy/plugins/rssget/migrations"


def entries(*article_ids):
    return [({"title": article_id}, article_id) for article_id in article_ids]


class RSSPushPolicyTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_root = tempfile.TemporaryDirectory(prefix="nsybot-rss-policy-")
        load_rss_plugin(cls.test_root.name)
        from nsy.plugins.rssget import models, models_method

        cls.models = models
        cls.details = models_method.DetailManager
        cls.groups = models_method.GroupconfigManager

    @classmethod
    def tearDownClass(cls):
        cls.test_root.cleanup()

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.addAsyncCleanup(self.engine.dispose)
        async with self.engine.begin() as connection:
            await connection.run_sync(self.models.Model.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def skipped_titles(self, session, user="account", group="group-a"):
        prefix = self.details.skip_id(user, group, "")
        return set(await session.scalars(select(self.models.Detail.summary).where(
            self.models.Detail.id.startswith(prefix),
        )))

    async def test_omitted_push_limit_defaults_to_one_in_manager_and_database(self):
        async with self.sessions() as session:
            config = await self.groups.create_signmsg(
                session, group_id="orm-group", **GROUP_OPTIONS,
            )
            self.assertEqual(config.push_limit, 1)
            await session.execute(text("""
                INSERT INTO Group_config (
                    group_id, if_need_trans, if_need_self_trans, if_need_translate,
                    if_need_photo_num_mention, if_need_merged_message
                ) VALUES ('sql-group', 1, 0, 1, 0, 1)
            """))
            await session.commit()
            self.assertEqual((await session.get(self.models.Groupconfig, "sql-group")).push_limit, 1)

    async def test_updating_another_group_option_preserves_explicit_limit(self):
        async with self.sessions() as session:
            await self.groups.create_signmsg(
                session, group_id="group-a", push_limit=5, **GROUP_OPTIONS,
            )
            self.assertTrue(await self.groups.update_config(session, "group-a", if_need_translate=False))
            config = await session.get(self.models.Groupconfig, "group-a")
            self.assertEqual(config.push_limit, 5)
            self.assertFalse(config.if_need_translate)
            self.assertTrue(config.if_need_trans)
            self.assertTrue(await self.groups.update_config(session, "group-a", push_limit=0))
            self.assertEqual(config.push_limit, 0)
            self.assertFalse(config.if_need_translate)

    async def test_manager_rejects_invalid_create_limits_without_creating_rows(self):
        for invalid in (-1, 6, 1.5, 1.0, "1", None, True, False):
            with self.subTest(push_limit=invalid):
                async with self.sessions() as session:
                    with self.assertRaisesRegex(ValueError, "0.*5"):
                        await self.groups.create_signmsg(
                            session, group_id="invalid", push_limit=invalid, **GROUP_OPTIONS,
                        )
                    self.assertIsNone(await session.get(self.models.Groupconfig, "invalid"))

    async def test_manager_rejects_invalid_update_before_mutating_other_options(self):
        async with self.sessions() as session:
            await self.groups.create_signmsg(
                session, group_id="group-a", push_limit=4, **GROUP_OPTIONS,
            )
            for invalid in (-1, 6, 1.5, "1", None, True):
                with self.subTest(push_limit=invalid):
                    with self.assertRaisesRegex(ValueError, "0.*5"):
                        await self.groups.update_config(
                            session, "group-a", if_need_trans=False, push_limit=invalid,
                        )
                    config = await session.get(self.models.Groupconfig, "group-a")
                    self.assertEqual(config.push_limit, 4)
                    self.assertTrue(config.if_need_trans)

    async def test_database_rejects_out_of_range_or_nonintegral_limits(self):
        for invalid in (-1, 6, 1.5, None):
            with self.subTest(push_limit=invalid):
                async with self.sessions() as session:
                    with self.assertRaises(IntegrityError):
                        await session.execute(text("""
                            INSERT INTO Group_config VALUES ('invalid', 1, 0, 1, 0, 1, :limit)
                        """), {"limit": invalid})
                    await session.rollback()

    async def test_default_window_silently_registers_everything_after_latest_one(self):
        async with self.sessions() as session:
            await self.details.initialize_subscription(session, "account", "group-a", entries("a", "b", "c", "d"))
            self.assertEqual(await self.skipped_titles(session), {"b", "c", "d"})
            self.assertIsNone(await session.get(self.models.Detail, "a-group-a"))

    async def test_limits_one_five_and_zero_apply_to_each_round(self):
        cases = (
            (1, {"b", "c", "d", "e", "f", "g"}, {"i", "j", "k", "l", "m", "n"}),
            (5, {"f", "g"}, {"m", "n"}),
            (0, set(), set()),
        )
        for limit, first_skips, second_skips in cases:
            user = f"account-{limit}"
            with self.subTest(push_limit=limit):
                async with self.sessions() as session:
                    await self.details.initialize_subscription(
                        session, user, "group-a", entries("a", "b", "c", "d", "e", "f", "g"), push_limit=limit,
                    )
                    self.assertEqual(await self.skipped_titles(session, user), first_skips)
                    await self.details.initialize_subscription(
                        session, user, "group-a", entries("h", "i", "j", "k", "l", "m", "n"), push_limit=limit,
                    )
                    self.assertEqual(await self.skipped_titles(session, user), first_skips | second_skips)
                    # Increasing the limit must not resurrect articles silently handled before.
                    await self.details.initialize_subscription(
                        session, user, "group-a", entries("b", "f", "m"), push_limit=0,
                    )
                    self.assertEqual(await self.skipped_titles(session, user), first_skips | second_skips)

    async def test_existing_initialized_marker_does_not_bypass_current_window(self):
        async with self.sessions() as session:
            session.add(self.models.Detail(
                id=self.details.initialization_id("account", "group-a"), summary="initialized",
            ))
            await session.commit()
            await self.details.initialize_subscription(
                session, "account", "group-a", entries("a", "b", "c", "d", "e", "f", "g"), push_limit=5,
            )
            self.assertEqual(await self.skipped_titles(session), {"f", "g"})

    async def test_pending_startup_baseline_seeds_all_articles_even_with_zero_limit(self):
        for limit in (0, 1, 5):
            user = f"pending-{limit}"
            with self.subTest(push_limit=limit):
                async with self.sessions() as session:
                    key = self.details.initialization_id(user, "group-a")
                    session.add(self.models.Detail(id=key, summary="pending"))
                    await session.commit()
                    await self.details.initialize_subscription(
                        session, user, "group-a", entries("a", "b", "c", "d", "e", "f", "g"), push_limit=limit,
                    )
                    self.assertEqual(await self.skipped_titles(session, user), {"a", "b", "c", "d", "e", "f", "g"})
                    self.assertEqual((await session.get(self.models.Detail, key)).summary, "initialized")

    async def test_silent_records_remain_source_and_group_scoped(self):
        async with self.sessions() as session:
            await self.details.initialize_subscription(
                session, "account", "group-a", entries("new", "shared"), push_limit=1,
            )
            await self.details.initialize_subscription(
                session, "other", "group-a", entries("shared"), push_limit=1,
            )
            await self.details.initialize_subscription(
                session, "account", "group-b", entries("shared"), push_limit=1,
            )
            self.assertEqual(await self.skipped_titles(session), {"shared"})
            self.assertEqual(await self.skipped_titles(session, "other"), set())
            self.assertEqual(await self.skipped_titles(session, group="group-b"), set())
            self.assertIsNone(await session.get(self.models.Detail, "shared-group-a"))
            self.assertIsNone(await session.get(self.models.Detail, "shared-group-b"))

    async def test_window_preserves_actual_delivery_records_and_timestamps(self):
        delivered_at = datetime(2026, 10, 25, 12, 30)
        async with self.sessions() as session:
            session.add(self.models.Detail(id="shared-group-a", summary="delivered", updated=delivered_at))
            await session.commit()
            await self.details.initialize_subscription(
                session, "account", "group-a", entries("new", "shared", "older"), push_limit=1,
            )
            self.assertEqual(await self.skipped_titles(session), {"older"})
            delivered = await session.get(self.models.Detail, "shared-group-a")
            self.assertEqual((delivered.summary, delivered.updated), ("delivered", delivered_at))
            self.assertEqual(await self.details.last_successful_delivery_at(session, "group-a"), delivered_at)
            silent = await session.get(self.models.Detail, self.details.skip_id("account", "group-a", "older"))
            self.assertIsNone(silent.updated)


def load_migration(filename):
    path = MIGRATIONS / filename
    spec = importlib.util.spec_from_file_location(f"rss_migration_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RSSPushLimitMigrationTests(unittest.TestCase):
    def test_upgrade_and_downgrade_preserve_existing_rows_and_options(self):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        migration_path = MIGRATIONS / "2f7a9d8136c0_group_push_limit.py"
        self.assertTrue(migration_path.is_file(), "推送上限需要独立迁移")
        migration = load_migration(migration_path.name)
        self.assertEqual(migration.down_revision, "76942fe5b1a4")
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                load_migration("1b51e394adf2_init.py").upgrade()
                load_migration("76942fe5b1a4_group_openid.py").upgrade()
            connection.execute(text("INSERT INTO Group_config VALUES ('openid-existing', 1, 0, 1, 0, 1)"))
            connection.execute(text("INSERT INTO Plantform VALUES ('test', '/test/', '0')"))
            connection.execute(text("INSERT INTO User VALUES ('account', 'name', 'test')"))
            connection.execute(text("INSERT INTO Subscribe VALUES ('account-openid-existing', 'account', 'openid-existing')"))
            connection.execute(text("INSERT INTO Detail VALUES ('article-openid-existing', 'title', '2026-10-25 12:30:00')"))
            connection.execute(text("INSERT INTO Content (id, text) VALUES ('article', 'full original')"))
            original_tables = inspect(connection).get_table_names()
            original_rows = {table: connection.execute(text(f'SELECT * FROM "{table}"')).all() for table in original_tables}

            with Operations.context(context):
                migration.upgrade()
            self.assertEqual(inspect(connection).get_table_names(), original_tables)
            self.assertEqual(connection.execute(text("SELECT * FROM Group_config")).one(), (*original_rows["Group_config"][0], 1))
            for table in original_tables:
                if table != "Group_config":
                    self.assertEqual(connection.execute(text(f'SELECT * FROM "{table}"')).all(), original_rows[table])
            connection.execute(text("INSERT INTO Group_config (group_id, if_need_trans, if_need_self_trans, if_need_translate, if_need_photo_num_mention, if_need_merged_message) VALUES ('openid-new', 0, 1, 0, 1, 0)"))
            self.assertEqual(connection.scalar(text("SELECT push_limit FROM Group_config WHERE group_id='openid-new'")), 1)
            for invalid in (-1, 6, 1.5):
                with self.subTest(push_limit=invalid), self.assertRaises(IntegrityError):
                    connection.execute(text("UPDATE Group_config SET push_limit=:limit WHERE group_id='openid-existing'"), {"limit": invalid})
            connection.execute(text("UPDATE Group_config SET push_limit=5 WHERE group_id='openid-existing'"))
            with Operations.context(context):
                migration.downgrade()
            self.assertNotIn("push_limit", {column["name"] for column in inspect(connection).get_columns("Group_config")})
            self.assertEqual(connection.execute(text("SELECT * FROM Group_config WHERE group_id='openid-existing'")).one(), original_rows["Group_config"][0])
            self.assertEqual(connection.execute(text("SELECT * FROM Group_config WHERE group_id='openid-new'")).one(), ("openid-new", 0, 1, 0, 1, 0))
            for table in original_tables:
                if table != "Group_config":
                    self.assertEqual(connection.execute(text(f'SELECT * FROM "{table}"')).all(), original_rows[table])


if __name__ == "__main__":
    unittest.main()
