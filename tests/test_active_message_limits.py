"""主动群消息应按真实时间限速，覆盖正文、附件和提示。"""

import asyncio
import unittest
from unittest.mock import patch

from nsy import qq_utils


class VirtualClock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


class ActiveMessageLimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assertTrue(hasattr(qq_utils, "ActiveMessageLimiter"), "主动发送缺少频率控制")
        self.clock = VirtualClock()
        self.limiter = qq_utils.ActiveMessageLimiter(clock=self.clock.time, sleeper=self.clock.sleep)

    async def test_same_group_stays_below_twenty_messages_in_any_minute(self):
        starts = []
        for _ in range(45):
            await self.limiter.wait("bot-a", "group-a")
            starts.append(self.clock.now)
        for start in starts:
            self.assertLessEqual(sum(start <= value < start + 60 for value in starts), 20)

    async def test_multiple_groups_share_bot_thirty_messages_per_minute_limit(self):
        starts = []
        for index in range(45):
            await self.limiter.wait("bot-a", f"group-{index}")
            starts.append(self.clock.now)
        for start in starts:
            self.assertLessEqual(sum(start <= value < start + 60 for value in starts), 30)

    async def test_independent_bots_do_not_share_a_quota(self):
        await self.limiter.wait("bot-a", "group-a")
        await self.limiter.wait("bot-b", "group-a")
        self.assertEqual(self.clock.now, 0)

    async def test_concurrent_requests_and_all_active_message_types_are_paced(self):
        sent_at = []

        class Bot:
            self_id = "bot-a"

            async def send_to_group(_, **kwargs):
                sent_at.append(self.clock.now)
                return {"id": "sent"}

        bot = Bot()
        with patch.object(qq_utils, "active_message_limiter", self.limiter):
            await asyncio.gather(*[
                qq_utils.send_group_message(bot, "group-a", message)
                for message in (
                    qq_utils.markdown("正文"), qq_utils.file_image(b"image", "image.jpg"),
                    qq_utils.error("附件失败"),
                )
            ])
        self.assertEqual(len(sent_at), 3)
        self.assertGreaterEqual(sent_at[-1] - sent_at[0], 6)

    async def test_delayed_upload_cannot_bunch_with_a_later_text_message(self):
        started, uploaded = asyncio.Event(), asyncio.Event()
        sent = []

        class Bot:
            self_id = "bot-a"

            async def send_to_group(_, group_openid, message):
                if message.type == "file_image":
                    started.set()
                    await uploaded.wait()
                sent.append((message.type, self.clock.now))

        with patch.object(qq_utils, "active_message_limiter", self.limiter):
            image = asyncio.create_task(qq_utils.send_group_message(Bot(), "group-a", qq_utils.file_image(b"image", "image.jpg")))
            await started.wait()
            text = asyncio.create_task(qq_utils.send_group_message(Bot(), "group-a", qq_utils.markdown("正文")))
            await asyncio.sleep(0)
            self.clock.now = 3.1
            uploaded.set()
            await asyncio.gather(image, text)
        self.assertEqual([kind for kind, _ in sent], ["file_image", "markdown"])
        self.assertGreaterEqual(sent[1][1] - sent[0][1], 3)


if __name__ == "__main__":
    unittest.main()
