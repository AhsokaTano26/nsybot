"""平台命令的持久化、输入校验、权限与引用保护回归测试。"""

import tempfile
import unittest
from unittest.mock import patch

from nonebot.adapters.qq import GroupMessageCreateEvent, Message
from nonebot.exception import FinishedException
from nonebot.rule import TrieRule
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rss_test_support import load_rss_plugin


class PlatformCommandTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_root = tempfile.TemporaryDirectory(prefix="nsybot-platform-tests-")
        cls.rss = load_rss_plugin(cls.test_root.name)

    @classmethod
    def tearDownClass(cls):
        cls.test_root.cleanup()

    async def asyncSetUp(self):
        self.assertTrue(
            hasattr(self.rss, "execute_platform_command"),
            "RSS 插件尚未提供平台管理命令",
        )
        from nsy.plugins.rssget.models import Plantform, User

        self.Platform = Plantform
        self.User = User
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Plantform.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        if hasattr(self, "engine"):
            await self.engine.dispose()

    async def command(self, command, args=""):
        async with self.sessions() as session:
            return await self.rss.execute_platform_command(session, command, args)

    async def test_added_platform_persists_and_is_available_to_user_registration(self):
        await self.command("增加平台", "twitter /twitter/user/ 1")
        async with self.sessions() as session:
            from nsy.plugins.rssget.models_method import PlantformManager

            platform = await PlantformManager.get_Sign_by_student_id(session, "twitter")
            self.assertEqual((platform.url, platform.need_trans), ("/twitter/user/", "1"))
        result = await self.command("平台列表")
        self.assertIn("twitter", result)
        self.assertIn("/twitter/user/", result)

    async def test_duplicate_add_does_not_overwrite_existing_platform(self):
        await self.command("增加平台", "twitter /twitter/user/ 1")
        with self.assertRaises(ValueError):
            await self.command("增加平台", "twitter /changed/ 0")
        async with self.sessions() as session:
            platform = await session.get(self.Platform, "twitter")
            self.assertEqual((platform.url, platform.need_trans), ("/twitter/user/", "1"))

    async def test_update_persists_new_settings_and_preserves_user_association(self):
        await self.command("增加平台", "twitter /twitter/user/ 1")
        async with self.sessions.begin() as session:
            session.add(self.User(User_ID="account", User_Name="测试", Plantform="twitter"))
        await self.command("修改平台", "twitter /twitter/user/media/ 0")
        async with self.sessions() as session:
            platform = await session.get(self.Platform, "twitter")
            user = await session.get(self.User, "account")
            self.assertEqual((platform.url, platform.need_trans), ("/twitter/user/media/", "0"))
            self.assertEqual(user.Plantform, "twitter")

    async def test_update_of_missing_platform_does_not_create_it(self):
        with self.assertRaises(ValueError):
            await self.command("修改平台", "missing /example/ 0")
        async with self.sessions() as session:
            self.assertIsNone(await session.get(self.Platform, "missing"))

    async def test_invalid_inputs_do_not_write_platforms(self):
        invalid = (
            "twitter /twitter/user/", "twitter /twitter/user/ 2",
            "twitter /twitter/user/ true", "twitter /twitter/user/ １",
            "twitter https://rsshub.example/twitter/user/ 1",
            "twitter //rsshub.example/twitter/user/ 1",
            "twitter twitter/user/ 1", "twitter /twitter/user/#fragment 1",
            "twitter /twitter/user/ 1 extra", "x" * 256 + " /example/ 0",
        )
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(ValueError):
                await self.command("增加平台", args)
        async with self.sessions() as session:
            self.assertEqual(list((await session.scalars(select(self.Platform))).all()), [])

    async def test_invalid_update_preserves_previous_settings(self):
        await self.command("增加平台", "twitter /twitter/user/ 1")
        with self.assertRaises(ValueError):
            await self.command("修改平台", "twitter https://example.com/ 0")
        async with self.sessions() as session:
            platform = await session.get(self.Platform, "twitter")
            self.assertEqual((platform.url, platform.need_trans), ("/twitter/user/", "1"))

    async def test_route_prefix_is_preserved_when_user_id_is_a_query_parameter(self):
        await self.command("增加平台", "example /example?uid= 0")
        async with self.sessions() as session:
            platform = await session.get(self.Platform, "example")
            self.assertEqual(platform.url, "/example?uid=")

    async def test_referenced_platform_cannot_be_deleted(self):
        await self.command("增加平台", "twitter /twitter/user/ 1")
        async with self.sessions.begin() as session:
            session.add(self.User(User_ID="account", User_Name="测试", Plantform="twitter"))
        with self.assertRaises(ValueError):
            await self.command("删除平台", "twitter")
        async with self.sessions() as session:
            self.assertIsNotNone(await session.get(self.Platform, "twitter"))
            self.assertIsNotNone(await session.get(self.User, "account"))

    async def test_unused_platform_can_be_deleted(self):
        await self.command("增加平台", "twitter /twitter/user/ 1")
        await self.command("删除平台", "twitter")
        async with self.sessions() as session:
            self.assertIsNone(await session.get(self.Platform, "twitter"))
        with self.assertRaises(ValueError):
            await self.command("删除平台", "twitter")

    async def test_delete_and_list_reject_extra_arguments(self):
        await self.command("增加平台", "twitter /twitter/user/ 1")
        for command, args in (("删除平台", "twitter extra"), ("平台列表", "extra")):
            with self.subTest(command=command), self.assertRaises(ValueError):
                await self.command(command, args)
        self.assertIn("twitter", await self.command("平台列表"))

    async def test_all_four_registered_commands_reject_non_superusers(self):
        event_data = {
            "id": "message", "timestamp": "2026-10-11T12:00:00+00:00",
            "content": "平台列表", "group_id": "group-a", "group_openid": "group-a",
            "author": {
                "id": "ordinary-member", "bot": False, "member_role": "member",
                "member_openid": "ordinary-member",
            },
        }
        for name, command in (
            ("platform_add", "增加平台"), ("platform_update", "修改平台"),
            ("platform_delete", "删除平台"), ("platform_list", "平台列表"),
        ):
            event = GroupMessageCreateEvent.model_validate({**event_data, "content": command})
            state = {}
            TrieRule.get_value(None, event, state)
            matcher = getattr(self.rss, name)
            self.assertFalse(await matcher.rule(None, event, state))
            admin = event.model_copy(deep=True)
            admin.author.member_openid = "admin-member"
            self.assertTrue(await matcher.rule(None, admin, state))

    async def test_registered_handlers_apply_the_selected_operation(self):
        replies = []

        async def finish(message):
            replies.append(str(message))
            raise FinishedException

        async def invoke(matcher, text):
            with patch.object(self.rss, "get_session", self.sessions), patch.object(matcher, "finish", finish):
                with self.assertRaises(FinishedException):
                    await matcher.handlers[0].call(args=Message(text))

        await invoke(self.rss.platform_add, "twitter /twitter/user/ 1")
        async with self.sessions() as session:
            self.assertEqual((await session.get(self.Platform, "twitter")).need_trans, "1")
        await invoke(self.rss.platform_update, "twitter /changed/ 0")
        async with self.sessions() as session:
            platform = await session.get(self.Platform, "twitter")
            self.assertEqual((platform.url, platform.need_trans), ("/changed/", "0"))
        await invoke(self.rss.platform_list, "")
        self.assertIn("twitter", replies[-1])
        self.assertIn("/changed/", replies[-1])
        await invoke(self.rss.platform_delete, "twitter")
        async with self.sessions() as session:
            self.assertIsNone(await session.get(self.Platform, "twitter"))


if __name__ == "__main__":
    unittest.main()
