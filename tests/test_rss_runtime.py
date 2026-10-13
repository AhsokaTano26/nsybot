"""运行配置、北京时间与翻译请求的真实边界测试。"""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI

from rss_test_support import load_rss_plugin


class RSSRuntimeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.TemporaryDirectory(prefix="nsybot-runtime-test-")
        cls.rss = load_rss_plugin(cls.root.name)

    @classmethod
    def tearDownClass(cls):
        cls.root.cleanup()

    async def test_deepseek_uses_configured_model_and_closes_http_client(self):
        from nsy.plugins.rssget import translation
        from nsy.plugins.rssget.config import Config

        requests = []

        async def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={
                "id": "test", "object": "chat.completion", "created": 0,
                "model": "configured-model", "choices": [{
                    "index": 0, "message": {"role": "assistant", "content": "测试译文"},
                    "finish_reason": "stop",
                }],
            })

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        self.addAsyncCleanup(client.aclose)

        def create_client(**kwargs):
            return AsyncOpenAI(http_client=client, **kwargs)

        with patch.object(translation, "get_config", return_value=Config(api_key="test-key", model_name="configured-model")), patch.object(
            translation, "AsyncOpenAI", create_client,
        ):
            result = await translation.DeepSeek().main("original text")
        self.assertEqual(result, "测试译文")
        self.assertEqual(requests[0]["model"], "configured-model")
        self.assertTrue(client.is_closed)

    async def test_rest_window_is_shanghai_time_even_with_utc_input(self):
        for hour, minute, expected in ((18, 0, True), (23, 30, True), (0, 1, False), (12, 0, False)):
            with self.subTest(hour=hour):
                now = datetime(2026, 10, 13, hour, minute, tzinfo=timezone.utc)
                self.assertEqual(self.rss.is_current_time_in_period("02:00", "08:00", now), expected)

    async def test_refresh_interval_rejects_zero_and_negative_values(self):
        from nsy.plugins.rssget.config import Config

        for value in (0, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Config(refresh_time=value)


if __name__ == "__main__":
    unittest.main()
