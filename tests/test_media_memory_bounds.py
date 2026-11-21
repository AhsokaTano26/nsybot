import asyncio
import unittest
from unittest.mock import patch

import httpx

from nsy import qq_utils


class MediaMemoryBoundsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        slot = patch.object(qq_utils, '_image_capacity', asyncio.Semaphore(1))
        slot.start()
        self.addCleanup(slot.stop)

    async def test_image_redirect_body_is_not_buffered(self):
        reads = []
        class Redirect(httpx.AsyncByteStream):
            async def __aiter__(self):
                reads.append(True)
                yield b'x' * 6400

        def response(request):
            if request.url.path == '/start':
                return httpx.Response(302, headers={'Location': '/final'}, stream=Redirect())
            return httpx.Response(200, headers={'content-type': 'image/png'}, content=b'png')
        async with httpx.AsyncClient(transport=httpx.MockTransport(response), follow_redirects=True) as client:
            data, _ = await qq_utils.download_image('https://example.invalid/start', client)
        self.assertEqual(data, b'png')
        self.assertEqual(reads, [])

    async def test_compressed_image_is_rejected_before_unbounded_decoding(self):
        class Compressed(httpx.AsyncByteStream):
            async def __aiter__(self):
                raise AssertionError('must reject before reading')
                yield b''

        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
            httpx.Response(200, headers={'content-type': 'image/png', 'content-encoding': 'gzip'}, stream=Compressed())
        )) as client:
            with self.assertRaisesRegex(ValueError, '压缩'):
                await qq_utils.download_image('https://example.invalid/image', client)

    async def test_cancelled_image_transfer_releases_capacity(self):
        entered = asyncio.Event()

        async def transfer():
            async with qq_utils.image_transfer_slot():
                entered.set()
                await asyncio.Event().wait()

        first = asyncio.create_task(transfer())
        await asyncio.wait_for(entered.wait(), 1)
        entered.clear()
        second = asyncio.create_task(transfer())
        await asyncio.sleep(0)
        self.assertFalse(entered.is_set())
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        await asyncio.wait_for(entered.wait(), 1)
        second.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await second

    async def test_expired_send_deadlines_are_pruned_without_changing_pacing(self):
        limiter = qq_utils.ActiveMessageLimiter(clock=lambda: 10)
        limiter.bot_next['old'] = 1
        limiter.group_next[('old', 'left')] = 1
        async with limiter.turn('current', 'group'):
            pass
        self.assertNotIn('old', limiter.bot_next)
        self.assertNotIn(('old', 'left'), limiter.group_next)

    async def test_quote_image_total_is_bounded_before_any_broadcast(self):
        import tempfile
        from pathlib import Path
        import nonebot
        from nonebot.adapters.qq import Message, MessageSegment
        from unittest.mock import AsyncMock

        try:
            nonebot.get_driver()
        except ValueError:
            nonebot.init(driver='~fastapi', log_level='ERROR', localstore_data_dir=Path(tempfile.mkdtemp()))
        if nonebot.get_plugin('birthday') is None:
            nonebot.load_plugin('nsy.plugins.birthday')
        from nsy.plugins.birthday import quotes
        quote = Message([MessageSegment.image('https://example.invalid/1.png'), MessageSegment.image('https://example.invalid/2.png')])
        with patch.object(quotes, 'MAX_QUOTE_IMAGE_BYTES', 10, create=True), patch.object(
            quotes, 'download_image', AsyncMock(return_value=(b'123456', 'image.png')),
        ):
            with self.assertRaisesRegex(ValueError, '总量'):
                await quotes.quote_messages(quote)


if __name__ == '__main__':
    unittest.main()
