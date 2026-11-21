"""RSS normalization releases its parser before optional external work."""

import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
from feedparser import FeedParserDict

from rss_test_support import load_rss_plugin


class RSSNormalizationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.TemporaryDirectory(prefix="nsybot-normalization-")
        load_rss_plugin(cls.root.name)

    @classmethod
    def tearDownClass(cls):
        cls.root.cleanup()

    def tracked_parser(self):
        trees = []

        def parse(*args, **kwargs):
            tree = BeautifulSoup(*args, **kwargs)
            trees.append(tree)
            return tree

        return trees, parse

    async def test_oversized_entry_is_rejected_before_parsing_or_translation(self):
        from nsy.plugins.rssget import format_json

        trees, parse = self.tracked_parser()
        translated_inputs = []

        class Translator:
            async def main(self, text):
                translated_inputs.append(text)
                return "译文"

        # The entire staged entry counts, including metadata outside the HTML body.
        entry = FeedParserDict(summary="body", metadata="界" * 30)
        for if_need_trans in (0, 1):
            with self.subTest(if_need_trans=if_need_trans), patch.object(
                format_json.config, "rss_entry_max_bytes", 64,
            ), patch.object(format_json, "BeautifulSoup", parse):
                with self.assertRaisesRegex(ValueError, "^EntryTooLarge$"):
                    await format_json.Format().extract_content(entry, if_need_trans, translator=Translator())
        self.assertEqual(len(trees), 0, "oversized entries must not allocate an HTML parse tree")
        self.assertEqual(translated_inputs, [], "oversized entries must not invoke a translator")

    async def test_entry_budget_counts_utf8_bytes_and_accepts_exact_limit(self):
        from nsy.plugins.rssget import format_json

        # {"summary": "界"} occupies exactly 18 UTF-8 bytes with ensure_ascii=False.
        entry = FeedParserDict(summary="界")
        with patch.object(format_json.config, "rss_entry_max_bytes", 18):
            result = await format_json.Format().extract_content(entry, 0)
        self.assertEqual(result["text"], "界")
        with patch.object(format_json.config, "rss_entry_max_bytes", 17):
            with self.assertRaisesRegex(ValueError, "^EntryTooLarge$"):
                await format_json.Format().extract_content(entry, 0)

    async def test_extract_parses_once_and_preserves_quote_images_and_media_priority(self):
        from nsy.plugins.rssget import format_json, trans_msg

        entry = FeedParserDict(
            title="fallback", published="unknown date", link="https://x.com/example/status/123",
            summary='<p>Original <b>body</b></p><img src="https://img/body.jpg">'
            '<div class="rsshub-quote"><p>Quoted text</p>'
            '<img src="https://img/quote.jpg"><img src="https://img/body.jpg"></div>',
            media_content=[{"type": "image/jpeg", "url": "https://img/media.jpg"}],
            links=[{"rel": "enclosure", "type": "image/jpeg", "href": "https://img/attachment.jpg"}],
        )
        trees, parse = self.tracked_parser()
        with patch.object(format_json, "BeautifulSoup", parse), patch.object(trans_msg, "BeautifulSoup", parse):
            result = await format_json.Format().extract_content(entry, 0)

        self.assertEqual(len(trees), 1, "one entry must allocate only one HTML parse tree")
        self.assertTrue(trees[0].decomposed)
        self.assertEqual(result, {
            "title": "fallback", "time": "unknown date", "link": "https://x.com/example/status/123",
            "text": "Original \nbody", "trans_text": None,
            "images": ["https://img/media.jpg", "https://img/body.jpg", "https://img/quote.jpg"],
        })

    async def test_extract_releases_parser_before_awaiting_translation(self):
        from nsy.plugins.rssget import format_json, trans_msg

        trees, parse = self.tracked_parser()
        translated_inputs, released = [], []

        class Translator:
            async def main(self, text):
                translated_inputs.append(text)
                released.append(bool(trees) and all(tree.decomposed for tree in trees))
                return "译文+第二行"

        entry = {
            "content": [{"value": '<p>Source</p><div class="rsshub-quote">Quote</div>'
                         '<img src="https://img/source.jpg">'}],
            "enclosures": [{"type": "image/jpeg", "href": "https://img/attachment.jpg"}],
        }
        with patch.object(format_json, "BeautifulSoup", parse), patch.object(trans_msg, "BeautifulSoup", parse):
            result = await format_json.Format().extract_content(entry, 1, translator=Translator())

        self.assertEqual(released, [True], "translation must not retain the HTML tree across network waits")
        self.assertEqual(translated_inputs, ["Source"])
        self.assertEqual(result["trans_text"], "译文\n第二行")
        self.assertEqual(result["images"], ["https://img/attachment.jpg", "https://img/source.jpg"])

    async def test_translation_capacity_is_shared_and_queue_wait_does_not_consume_timeout(self):
        from nsy.plugins.rssget import format_json

        first_started, next_started, all_parsed, release = (
            asyncio.Event(), asyncio.Event(), asyncio.Event(), asyncio.Event()
        )
        trees, parse = self.tracked_parser()
        active = peak = 0

        def parse_and_signal(*args, **kwargs):
            tree = parse(*args, **kwargs)
            if len(trees) == 3:
                all_parsed.set()
            return tree

        class Translator:
            async def main(self, text):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                (first_started if text == "one" else next_started).set()
                try:
                    await release.wait()
                    return f"译文 {text}"
                finally:
                    active -= 1

        tasks = []
        with patch.object(format_json, "_translation_capacity", asyncio.Semaphore(1), create=True), patch.object(
            format_json, "BeautifulSoup", parse_and_signal,
        ):
            try:
                tasks.append(asyncio.create_task(format_json.Format().extract_content(
                    {"summary": "one"}, 1, translator=Translator(),
                )))
                await asyncio.wait_for(first_started.wait(), 1)
                # The first request keeps its original timeout; queued requests must receive
                # their entire shorter timeout only after the occupied capacity is released.
                with patch.object(format_json, "TRANSLATION_TIMEOUT", 0.02):
                    tasks.extend(asyncio.create_task(format_json.Format().extract_content(
                        {"summary": text}, 1, translator=Translator(),
                    )) for text in ("two", "three"))
                    await asyncio.wait_for(all_parsed.wait(), 1)
                    with self.assertRaises(TimeoutError):
                        await asyncio.wait_for(next_started.wait(), 0.04)
                    self.assertTrue(all(tree.decomposed for tree in trees))
                    release.set()
                    results = await asyncio.wait_for(asyncio.gather(*tasks), 1)
            finally:
                release.set()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        self.assertEqual(peak, 1, "all Format instances must share one translator request slot")
        self.assertEqual([result["text"] for result in results], ["one", "two", "three"])
        self.assertEqual([result["trans_text"] for result in results], ["译文 one", "译文 two", "译文 three"])

    async def test_cancelling_translation_holder_and_waiter_releases_capacity(self):
        from nsy.plugins.rssget import format_json

        first_started, all_parsed = asyncio.Event(), asyncio.Event()
        trees, parse = self.tracked_parser()
        translated_inputs = []

        def parse_and_signal(*args, **kwargs):
            tree = parse(*args, **kwargs)
            if len(trees) == 3:
                all_parsed.set()
            return tree

        class Translator:
            async def main(self, text):
                translated_inputs.append(text)
                if text == "holder":
                    first_started.set()
                    await asyncio.Event().wait()
                return f"译文 {text}"

        tasks = []
        with patch.object(format_json, "_translation_capacity", asyncio.Semaphore(1), create=True), patch.object(
            format_json, "BeautifulSoup", parse_and_signal,
        ):
            try:
                tasks.append(asyncio.create_task(format_json.Format().extract_content(
                    {"summary": "holder"}, 1, translator=Translator(),
                )))
                await asyncio.wait_for(first_started.wait(), 1)
                tasks.extend(asyncio.create_task(format_json.Format().extract_content(
                    {"summary": text}, 1, translator=Translator(),
                )) for text in ("cancelled waiter", "survivor"))
                await asyncio.wait_for(all_parsed.wait(), 1)
                tasks[1].cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await tasks[1]
                tasks[0].cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await tasks[0]
                survivor = await asyncio.wait_for(tasks[2], 1)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        self.assertEqual(translated_inputs, ["holder", "survivor"])
        self.assertEqual(survivor["trans_text"], "译文 survivor")

    async def test_quote_helpers_release_trees_after_returning_plain_values(self):
        from nsy.plugins.rssget import trans_msg

        trees, parse = self.tracked_parser()
        html = '<p>Keep</p><div class="rsshub-quote"><p>Remove</p></div>'
        with patch.object(trans_msg, "BeautifulSoup", parse):
            quoted = await trans_msg.if_trans({"description": html})
            cleaned = await trans_msg.remove_html_tag_soup(html)
        self.assertTrue(all(tree.decomposed for tree in trees), "standalone quote helpers must release tree cycles")
        self.assertTrue(quoted)
        self.assertEqual(cleaned, "<p>Keep</p>")


class OptionalSDKStartupTests(unittest.TestCase):
    def test_loading_rss_does_not_import_optional_external_sdks(self):
        repository = Path(__file__).resolve().parents[1]
        code = """
import json
import sys
import tempfile
sys.path.insert(0, "tests")
from rss_test_support import load_rss_plugin
with tempfile.TemporaryDirectory(prefix="nsybot-lazy-sdk-") as root:
    rss = load_rss_plugin(root)
    from nsy.plugins.rssget.format_json import Format, PLATFORMS
    assert callable(Format)
    assert set(PLATFORMS) == {0, 1, 2, 3, 9}
    prefixes = ("twikit", "alibabacloud_", "openai")
    print(json.dumps(sorted(name for name in sys.modules if name.startswith(prefixes))))
"""
        completed = subprocess.run(
            [sys.executable, "-c", code], cwd=repository, capture_output=True, text=True, check=True,
        )
        imported = json.loads(completed.stdout.splitlines()[-1])
        self.assertEqual(imported, [], "disabled SDKs must not occupy startup memory")


if __name__ == "__main__":
    unittest.main()
