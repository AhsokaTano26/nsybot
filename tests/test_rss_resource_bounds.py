"""Feed budgets stop allocation before parsing, without silently accepting truncation."""

import asyncio
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import gzip
import zlib

import httpx

from rss_test_support import load_rss_plugin


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks, self.reads, self.closed = chunks, 0, False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


class RSSResourceBoundsTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.TemporaryDirectory(prefix="nsybot-resource-test-")
        load_rss_plugin(cls.root.name)

    @classmethod
    def tearDownClass(cls):
        cls.root.cleanup()

    async def asyncSetUp(self):
        from nsy.plugins.rssget import functions
        self.functions = functions
        self.limits = SimpleNamespace(**dict(functions.config.model_dump(), rss_feed_max_bytes=1024))
        patcher = patch.object(functions.NetworkManager, "_rss_capacity", asyncio.Semaphore(1), create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def fetch(self, stream, headers=None, status=200):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
            httpx.Response(status, stream=stream, headers=headers or {})
        )) as client:
            with patch.object(self.functions.NetworkManager, "get_client", return_value=client), patch.object(
                self.functions, "config", self.limits,
            ):
                return await self.functions._fetch_feed_once("https://rss.invalid/twitter/user/account")

    async def test_oversized_stream_is_not_fully_read_or_parsed(self):
        stream = Chunks([b"x" * 800] * 8)
        result = await self.fetch(stream)
        self.assertTrue(result.get("resource_limited"), "超限响应不能当作有效RSS")
        self.assertLess(stream.reads, 8)
        self.assertTrue(stream.closed)

    async def test_content_length_rejects_before_body_allocation(self):
        stream = Chunks([b"x" * 800] * 8)
        result = await self.fetch(stream, {"Content-Length": "6400"})
        self.assertTrue(result.get("resource_limited"))
        self.assertEqual(stream.reads, 0)

    async def test_gzip_limit_applies_to_decompressed_content(self):
        payload = b'<rss version="2.0"><channel><item><title>' + b'x' * 50000 + b'</title></item></channel></rss>'
        stream = Chunks([gzip.compress(payload)])
        result = await self.fetch(stream, {"Content-Encoding": "gzip"})
        self.assertTrue(result.get("resource_limited"))

    async def test_small_gzip_feed_is_complete_and_valid(self):
        payload = b'<rss version="2.0"><channel><item><title>Valid</title><guid>one</guid></item></channel></rss>'
        result = await self.fetch(Chunks([gzip.compress(payload)]), {"Content-Encoding": "gzip"})
        self.assertFalse(result.get("error"))
        self.assertEqual(result["entries"][0]["title"], "Valid")

    async def test_truncated_gzip_is_not_accepted_as_a_successful_feed(self):
        payload = b'<rss version="2.0"><channel><item><title>Valid</title><guid>one</guid></item></channel></rss>'
        result = await self.fetch(Chunks([gzip.compress(payload)[:-8]]), {"Content-Encoding": "gzip"})
        self.assertTrue(result.get("error"))
        self.assertFalse(result.get("resource_limited"), "坏编码属于源故障，不能绕过重试和链路故障检测")

    async def test_invalid_error_compression_preserves_rate_limit_and_retry_after(self):
        result = await self.fetch(Chunks([b'broken']), {
            'Content-Encoding': 'br', 'Retry-After': '3600',
        }, status=429)
        self.assertTrue(result.get('rate_limited'))
        self.assertEqual(result.get('retry_after'), 3600)

    async def test_raw_deflate_remains_supported(self):
        payload = b'<rss version="2.0"><channel><item><title>Valid</title></item></channel></rss>'
        encoder = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        result = await self.fetch(Chunks([encoder.compress(payload) + encoder.flush()]), {'Content-Encoding': 'deflate'})
        self.assertFalse(result.get('error'))
        self.assertEqual(result['entries'][0]['title'], 'Valid')

    async def test_many_tiny_entries_are_rejected_before_feedparser_allocation(self):
        self.limits.rss_feed_max_bytes = 1024 * 1024
        payload = b'<rss><channel>' + b'<item><title>x</title></item>' * 501 + b'</channel></rss>'
        with patch.object(self.functions.feedparser, 'parse', side_effect=AssertionError('must not parse')):
            result = await self.fetch(Chunks([payload]))
        self.assertTrue(result.get('resource_limited'))

    async def test_malformed_xml_cannot_bypass_structure_limits(self):
        self.limits.rss_feed_max_bytes = 1024 * 1024
        payload = b'<rss><channel><title>&nbsp;</title>' + b'<item><title>x</title></item>' * 501 + b'</channel></rss>'
        with patch.object(self.functions.feedparser, 'parse', side_effect=AssertionError('must not parse')):
            result = await self.fetch(Chunks([payload]))
        self.assertEqual(result.get('error'), 'MalformedFeed')
        self.assertEqual(result.get('entries'), [])

    async def test_redirect_body_is_closed_without_buffering(self):
        redirect = Chunks([b'x' * 800] * 8)
        def response(request):
            if request.url.path == '/start':
                return httpx.Response(302, headers={'Location': '/feed'}, stream=redirect)
            return httpx.Response(200, content=b'<rss version="2.0"><channel><title>ok</title></channel></rss>')
        async with httpx.AsyncClient(transport=httpx.MockTransport(response), follow_redirects=True) as client:
            with patch.object(self.functions.NetworkManager, 'get_client', return_value=client):
                result = await self.functions._fetch_feed_once('https://rss.invalid/start')
        self.assertFalse(result.get('error'))
        self.assertEqual(redirect.reads, 0)
        self.assertTrue(redirect.closed)
