"""运行配置、北京时间与翻译请求的真实边界测试。"""

import json
import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import AsyncMock, patch

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

    async def asyncSetUp(self):
        from nsy.plugins.rssget import functions

        patcher = patch.object(functions.NetworkManager, "_rss_backoffs", {}, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_primary_retries_three_times_before_trying_backup(self):
        from nsy.plugins.rssget import functions

        timeline, elapsed = [], 0
        valid = '<rss version="2.0"><channel><title>有效空窗口</title></channel></rss>'

        async def wait(delay):
            nonlocal elapsed
            elapsed += delay

        def respond(request):
            timeline.append((request.url.host, elapsed))
            return httpx.Response(503, text="unavailable") if request.url.host == "primary.invalid" else httpx.Response(200, text=valid)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.object(functions.NetworkManager, "get_client", return_value=client), patch.object(
                functions.config, "rsshub_host", "https://primary.invalid",
            ), patch.object(functions.config, "rsshub_host_back", ["https://backup.invalid"]), patch.object(
                functions.asyncio, "sleep", wait,
            ):
                data = await functions.rss_get()._fetch_user_feed("account", "/twitter/user/", "Twitter")
        self.assertTrue(data.get("version"))
        self.assertEqual(timeline, [("primary.invalid", 0), ("primary.invalid", 2),
            ("primary.invalid", 6), ("primary.invalid", 14), ("backup.invalid", 14)])

    async def test_primary_transient_failure_recovers_without_backup(self):
        from nsy.plugins.rssget import functions

        hosts, waits = [], []

        async def wait(delay):
            waits.append(delay)

        def respond(request):
            hosts.append(request.url.host)
            return httpx.Response(503) if len(hosts) == 1 else httpx.Response(200,
                text='<rss version="2.0"><channel><title>恢复</title></channel></rss>')

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.object(functions.NetworkManager, "get_client", return_value=client), patch.object(
                functions.config, "rsshub_host", "https://primary.invalid",
            ), patch.object(functions.config, "rsshub_host_back", ["https://backup.invalid"]), patch.object(
                functions.asyncio, "sleep", wait,
            ):
                await functions.rss_get()._fetch_user_feed("account", "/twitter/user/", "Twitter")
        self.assertEqual(hosts, ["primary.invalid", "primary.invalid"])
        self.assertEqual(waits, [2])

    async def test_network_error_and_invalid_feed_are_retried(self):
        from nsy.plugins.rssget import functions

        requests, waits = [], []

        async def wait(delay):
            waits.append(delay)

        def respond(request):
            requests.append(request)
            if len(requests) == 1:
                raise httpx.ConnectError("temporary", request=request)
            return httpx.Response(200, text="not an RSS feed" if len(requests) == 2 else
                '<rss version="2.0"><channel><title>恢复</title></channel></rss>')

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.object(functions.NetworkManager, "get_client", return_value=client), patch.object(functions.asyncio, "sleep", wait):
                data = await functions.fetch_feed("https://primary.invalid/twitter/user/account")
        self.assertTrue(data.get("version"))
        self.assertEqual(len(requests), 3)
        self.assertEqual(waits, [2, 4])

    async def test_long_retry_after_cools_primary_without_delaying_backup(self):
        from nsy.plugins.rssget import functions

        hosts, waits = [], []

        async def wait(delay):
            waits.append(delay)

        def respond(request):
            hosts.append(request.url.host)
            return httpx.Response(429, headers={"Retry-After": "3600"}) if request.url.host == "primary.invalid" else httpx.Response(200,
                text='<rss version="2.0"><channel><title>备用正常</title></channel></rss>')

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.object(functions.NetworkManager, "get_client", return_value=client), patch.object(
                functions.config, "rsshub_host", "https://primary.invalid",
            ), patch.object(functions.config, "rsshub_host_back", ["https://backup.invalid"]), patch.object(
                functions.asyncio, "sleep", wait,
            ):
                collector = functions.rss_get()
                await collector._fetch_user_feed("account", "/twitter/user/", "Twitter")
                await collector._fetch_user_feed("other", "/twitter/user/", "Twitter")
        self.assertEqual(hosts, ["primary.invalid", "backup.invalid", "backup.invalid"])
        self.assertEqual(waits, [])

    async def test_twitter_rate_limit_does_not_cool_other_platform_on_same_rsshub(self):
        from nsy.plugins.rssget import functions

        paths = []

        def respond(request):
            paths.append(request.url.path)
            if "/twitter/" in request.url.path:
                return httpx.Response(503, text="Twitter API rate limit exceeded", headers={"Retry-After": "3600"})
            return httpx.Response(200, text='<rss version="2.0"><channel><title>B站正常</title></channel></rss>')

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.object(functions.NetworkManager, "get_client", return_value=client):
                await functions.fetch_feed("https://shared.invalid/rsshub/twitter/user/account")
                await functions.fetch_feed("https://shared.invalid/rsshub/twitter/user/other")
                bili = await functions.fetch_feed("https://shared.invalid/rsshub/bilibili/user/account")
        self.assertEqual(paths, ["/rsshub/twitter/user/account", "/rsshub/bilibili/user/account"])
        self.assertTrue(bili.get("version"))

    async def test_retry_respects_cooldown_learned_while_waiting(self):
        from nsy.plugins.rssget import functions

        paths = []

        def respond(request):
            paths.append(request.url.path)
            if request.url.path.endswith("other"):
                return httpx.Response(429, headers={"Retry-After": "3600"})
            return httpx.Response(503)

        async def concurrent_rate_limit(delay):
            await functions.fetch_feed("https://shared.invalid/twitter/user/other")

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.object(functions.NetworkManager, "get_client", return_value=client), patch.object(
                functions.asyncio, "sleep", concurrent_rate_limit,
            ):
                result = await functions.fetch_feed("https://shared.invalid/twitter/user/account")
        self.assertEqual(paths, ["/twitter/user/account", "/twitter/user/other"])
        self.assertTrue(result["rate_limited"])

    async def test_concurrent_shorter_response_does_not_shorten_existing_cooldown(self):
        from nsy.plugins.rssget import functions

        clock = datetime(2026, 11, 19, 0, 0)
        both_started, release_shorter = asyncio.Event(), asyncio.Event()
        paths = []

        async def respond(request):
            paths.append(request.url.path)
            if request.url.path.endswith("long"):
                await both_started.wait()
                return httpx.Response(429, headers={"Retry-After": "3600"})
            both_started.set()
            await release_shorter.wait()
            return httpx.Response(429, headers={"Retry-After": "600"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.object(functions.NetworkManager, "get_client", return_value=client), patch.object(
                functions, "utc_now", return_value=clock,
            ):
                long = asyncio.create_task(functions.fetch_feed("https://shared.invalid/twitter/user/long"))
                short = asyncio.create_task(functions.fetch_feed("https://shared.invalid/twitter/user/short"))
                try:
                    await asyncio.wait_for(long, 2)
                finally:
                    release_shorter.set()
                    await asyncio.gather(short)
            with patch.object(functions.NetworkManager, "get_client", return_value=client), patch.object(
                functions, "utc_now", return_value=clock + timedelta(minutes=15),
            ):
                result = await functions.fetch_feed("https://shared.invalid/twitter/user/next")
        self.assertEqual(len(paths), 2, "较短的迟到响应不能让实例提前恢复请求")
        self.assertEqual(short.result()["retry_after"], 3600, "汇总状态也必须收到保留的最长冷却")
        self.assertEqual(result["retry_after"], 2700)

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

    async def test_rss_http_rate_limit_keeps_retry_after_and_wrapped_upstream_reason(self):
        from nsy.plugins.rssget import functions

        for status, body in ((429, "Too Many Requests"), (503, "Twitter API rate limit exceeded")):
            with self.subTest(status=status):
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
                    httpx.Response(status, text=body, headers={"Retry-After": "3600"})
                )) as client:
                    with patch.object(functions.NetworkManager, "get_client", return_value=client), patch.object(
                        functions.NetworkManager, "_rss_backoffs", {},
                    ):
                        result = await functions.fetch_feed("https://rss.invalid/twitter/user/account")
                self.assertTrue(result.get("rate_limited"))
                self.assertEqual(result.get("retry_after"), 3600)
                self.assertEqual(result.get("status_code"), status)

    async def test_refresh_interval_rejects_zero_and_negative_values(self):
        from nsy.plugins.rssget.config import Config

        for value in (0, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Config(refresh_time=value)
            with self.subTest(push_interval=value), self.assertRaises(ValueError):
                Config(rss_push_interval=value)
            with self.subTest(twitter_cooldown=value), self.assertRaises(ValueError):
                Config(rss_twitter_cooldown=value)
            with self.subTest(twitter_threshold=value), self.assertRaises(ValueError):
                Config(rss_twitter_failure_threshold=value)
            for field in ("rss_ingest_retry_interval", "rss_ingest_retry_batch", "rss_fetch_retry_base"):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    Config(**{field: value})

    async def test_retry_after_http_date_and_invalid_header(self):
        from nsy.plugins.rssget import functions

        later = datetime.now(timezone.utc) + timedelta(minutes=30)
        for header, expected_min in ((format_datetime(later, usegmt=True), 1790), ("bad header", 0)):
            with self.subTest(header=header):
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
                    httpx.Response(429, headers={"Retry-After": header})
                )) as client:
                    with patch.object(functions.NetworkManager, "get_client", return_value=client), patch.object(
                        functions.NetworkManager, "_rss_backoffs", {},
                    ), patch.object(functions.asyncio, "sleep", AsyncMock()):
                        result = await functions.fetch_feed("https://rss.invalid/twitter/user/account")
                self.assertGreaterEqual(result["retry_after"], expected_min)
                self.assertLessEqual(result["retry_after"], 1800)


if __name__ == "__main__":
    unittest.main()
