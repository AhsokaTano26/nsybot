"""扁平 QQ 凭据生成新版适配器可直接使用的配置。"""

import json
import unittest
from unittest.mock import patch

from nonebot.adapters.qq.config import Config

from nsy.qq_bootstrap import build_qq_bots


class QQBootstrapTests(unittest.TestCase):
    def test_flat_credentials_work_without_forwarding_retired_bot_token(self):
        with patch.dict("os.environ", {
            "QQ_APP_ID": "test-app", "QQ_APP_SECRET": "test-secret",
            "QQ_APP_TOKEN": "retired-token", "QQ_USE_WEBSOCKET": "true",
        }, clear=True):
            payload = json.loads(build_qq_bots())
        self.assertNotIn("token", payload[0], "新版配置不再传递旧 Bot Token")
        bot = Config(qq_bots=payload).qq_bots[0]
        self.assertEqual((bot.id, bot.secret), ("test-app", "test-secret"))
        self.assertTrue(bot.use_websocket)
        self.assertTrue(bot.intent.c2c_group_at_messages)
        self.assertTrue(bot.intent.group_members)


if __name__ == "__main__":
    unittest.main()
