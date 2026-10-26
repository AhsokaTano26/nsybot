"""帮助菜单及公共按钮构造器遵守 QQ 的 5 行、5 列限制。"""

import tempfile
import unittest
from unittest.mock import patch

from nonebot.adapters.qq import GroupMessageCreateEvent, Message
from nonebot.exception import FinishedException

from nsy.qq_utils import command_keyboard
from rss_test_support import load_rss_plugin


class CommandKeyboardTests(unittest.TestCase):
    def test_full_keyboard_preserves_commands_and_input_modes(self):
        rows = [[(f"按钮{row}-{col}", f"命令{row}-{col}", col % 2 == 0)
                 for col in range(5)] for row in range(5)]
        keyboard = command_keyboard(rows).data["keyboard"].content
        self.assertEqual(len(keyboard.rows), 5)
        self.assertEqual(len({button.id for row in keyboard.rows for button in row.buttons}), 25)
        self.assertEqual(keyboard.rows[4].buttons[4].action.data, "命令4-4")
        self.assertTrue(keyboard.rows[0].buttons[0].action.enter)
        self.assertFalse(keyboard.rows[0].buttons[1].action.enter)

    def test_invalid_dimensions_fail_before_sending_to_qq(self):
        button = ("按钮", "命令", True)
        for rows in ([], [[]], [[button]] * 6, [[button] * 6]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                command_keyboard(rows)


class HelpKeyboardTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_root = tempfile.TemporaryDirectory(prefix="nsybot-help-tests-")
        cls.rss = load_rss_plugin(cls.test_root.name)

    @classmethod
    def tearDownClass(cls):
        cls.test_root.cleanup()

    async def test_member_and_admin_help_send_legal_keyboards_without_losing_commands(self):
        group_commands = {
            "rss <用户ID> [序号]", "文章列表 <用户ID>", "用户列表", "群信息",
            "订阅", "取消订阅", "查询 群组", "查看配置", "群组配置",
            "群组配置 推送数量 <0-5>", "群组配置 转发 <开/关>", "群组配置 翻译 <开/关>",
        }
        admin_commands = {
            "订阅列表", "查询 群组 <群OpenID>", "查询 用户 <用户ID>",
            "增加用户 <用户ID> <用户名> <平台名>", "删除用户 <用户ID>", "清理失效订阅",
            "订阅统计", "群列表", "发送统计", "refresh", "/发送 <内容>", "/信号", "/信号否",
            "平台列表", "增加平台 <平台名> <RSSHub路由前缀> <翻译0/1>",
            "修改平台 <平台名> <RSSHub路由前缀> <翻译0/1>", "删除平台 <平台名>",
        }
        for member in ("member", "admin-member"):
            with self.subTest(member=member):
                event = GroupMessageCreateEvent.model_validate({
                    "id": "message", "timestamp": "2026-10-26T03:18:51+00:00",
                    "content": "help", "group_id": "group", "group_openid": "group",
                    "author": {"id": member, "member_openid": member, "bot": False,
                               "member_role": "member"},
                })
                replies = []

                async def send(message):
                    replies.append(Message(message))

                async def finish(message):
                    replies.append(Message(message))
                    raise FinishedException

                with patch.object(self.rss.help, "send", send), patch.object(self.rss.help, "finish", finish):
                    with self.assertRaises(FinishedException):
                        await self.rss.help.handlers[0].call(event=event)

                commands = set()
                for message in replies:
                    for segment in message:
                        if segment.type != "keyboard":
                            continue
                        rows = segment.data["keyboard"].content.rows
                        self.assertTrue(1 <= len(rows) <= 5, f"帮助键盘包含 {len(rows)} 行")
                        for row in rows:
                            self.assertTrue(1 <= len(row.buttons) <= 5)
                            commands.update(button.action.data for button in row.buttons)
                expected = group_commands | admin_commands if member == "admin-member" else group_commands
                self.assertEqual(commands, expected)


if __name__ == "__main__":
    unittest.main()
