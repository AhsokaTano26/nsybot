"""RSS 正文分页保留全文，且不依赖外部服务。"""

import unittest

from nsy import qq_utils


def markdown_text(message):
    return message.data["markdown"].content


def quoted_chunks(page):
    """Remove only generated quote prefixes, retaining source whitespace."""
    chunks = []
    lines = []
    for line in page.split("\n"):
        if line.startswith("> "):
            lines.append(line[2:].replace("\r> ", "\r"))
        elif lines:
            chunks.append("\n".join(lines))
            lines = []
    if lines:
        chunks.append("\n".join(lines))
    return chunks


def article_sections(pages):
    sections = {"original": [], "translation": []}
    section = "original"
    for page in pages:
        lines = []
        for line in page.split("\n"):
            if line.startswith("> "):
                lines.append(line[2:].replace("\r> ", "\r"))
                continue
            if lines:
                sections[section].append("\n".join(lines))
                lines = []
            if line.startswith("🌐 译文"):
                section = "translation"
        if lines:
            sections[section].append("\n".join(lines))
    return {name: "".join(chunks) for name, chunks in sections.items()}


class RSSArticleMessageTests(unittest.TestCase):
    def render(self, text, translation=None, **metadata):
        renderer = getattr(qq_utils, "article_messages", None)
        self.assertTrue(callable(renderer), "RSS must expose a complete article pager")
        content = {
            "username": "测试账号", "time": "2026-10-25 12:00",
            "link": "https://example.com/post", "text": text,
            "images": ["https://example.com/photo.jpg"],
        }
        content.update(metadata)
        messages = renderer(content, translation, "测试模型" if translation else None)
        self.assertIsInstance(messages, list)
        self.assertTrue(messages)
        self.assertTrue(all(message.type == "markdown" for message in messages))
        pages = [markdown_text(message) for message in messages]
        self.assertTrue(all(len(page) <= qq_utils.MAX_MARKDOWN_CHARS for page in pages))
        self.assertTrue(all("内容过长，已自动截断" not in page for page in pages))
        self.assertTrue(all("photo.jpg" not in page for page in pages))
        return pages

    def test_short_original_and_translation_share_one_compact_page(self):
        pages = self.render("first line\n\nlast line", "第一行\n\n最后一行")
        self.assertEqual(len(pages), 1)
        self.assertIn("@测试账号", pages[0])
        self.assertIn("2026-10-25 12:00", pages[0])
        self.assertIn("[查看原文](https://example.com/post)", pages[0])
        self.assertIn("🌐 译文", pages[0])
        self.assertNotIn("# ", pages[0])
        self.assertNotIn("正文", pages[0])
        self.assertNotIn("1/1", pages[0])
        self.assertEqual(article_sections(pages), {
            "original": "first line\n\nlast line",
            "translation": "第一行\n\n最后一行",
        })

    def test_all_unicode_whitespace_and_translation_survive_in_order(self):
        original = "\n  开头 🐦 e\u0301\r\n\n" + ("原文段落 🧑🏽‍💻\n\n" * 900) + "结尾  \n\n"
        translation = "\nTranslated 🌍\n\n" + ("Full translation with spaces.\n\n" * 400) + "END\n"
        pages = self.render(original, translation)
        self.assertGreater(len(pages), 3)
        self.assertEqual(article_sections(pages), {
            "original": original, "translation": translation,
        })
        for index, page in enumerate(pages, 1):
            self.assertIn(f"{index}/{len(pages)}", page)
        first_translation = next(index for index, page in enumerate(pages) if "🌐 译文" in page)
        self.assertTrue(all("🌐 译文" in page for page in pages[first_translation:]))

    def test_page_prefers_complete_paragraphs(self):
        first = "甲" * 2100 + "\n\n"
        second = "乙" * 2000
        pages = self.render(first + second)
        self.assertEqual(len(pages), 2)
        self.assertEqual(quoted_chunks(pages[0]), [first])
        self.assertEqual(quoted_chunks(pages[1]), [second])

    def test_long_paragraph_prefers_line_then_space_boundaries(self):
        for first in ("甲" * 2000 + "\n", "甲" * 2000 + " "):
            with self.subTest(boundary=repr(first[-1])):
                second = "乙" * 2000
                pages = self.render(first + second)
                self.assertEqual(quoted_chunks(pages[0]), [first])
                self.assertEqual(article_sections(pages)["original"], first + second)

    def test_long_unbroken_unicode_is_split_without_losing_characters(self):
        original = "🛰️漢e\u0301" * 2400
        translation = "译" * 8000
        pages = self.render(original, translation)
        self.assertGreater(len(pages), 4)
        self.assertEqual(article_sections(pages), {
            "original": original, "translation": translation,
        })

    def test_blank_lines_are_budgeted_and_preserved(self):
        original = "\n" * 4000
        pages = self.render(original)
        self.assertGreater(len(pages), 1)
        self.assertEqual(article_sections(pages)["original"], original)

    def test_oversized_metadata_cannot_consume_or_truncate_the_body(self):
        original = "完整原文" * 2200
        translation = "完整翻译" * 1500
        renderer = getattr(qq_utils, "article_messages", None)
        self.assertTrue(callable(renderer), "RSS must expose a complete article pager")
        messages = renderer({
            "username": "作者" * 5000, "time": "时间" * 5000,
            "link": "https://example.com/" + "x" * 10000, "text": original,
        }, translation, "模型" * 5000)
        pages = [markdown_text(message) for message in messages]
        self.assertTrue(all(len(page) <= qq_utils.MAX_MARKDOWN_CHARS for page in pages))
        self.assertIn("原文链接过长", pages[0])
        self.assertEqual(article_sections(pages), {
            "original": original, "translation": translation,
        })

    def test_source_markdown_stays_inside_its_quote_block(self):
        original = "```python\n" + "print('source')\n" * 300 + "```\n> # source heading\n"
        translation = "```\n未闭合代码块\n\n译文尾部"
        pages = self.render(original, translation)
        self.assertEqual(article_sections(pages), {
            "original": original, "translation": translation,
        })
        translation_page = next(page for page in pages if "🌐 译文" in page)
        self.assertIn("\n\n🌐 译文", translation_page)
        self.assertTrue(all(line.startswith("> ") for page in pages for line in page.split("\n") if "```" in line))

    def test_carriage_return_lines_remain_quoted_without_changing_source(self):
        original = "```\r# source heading\r\r> source quote\r"
        pages = self.render(original, "译文")
        self.assertIn("> ```\r> # source heading\r> \r> > source quote\r> ", pages[0])
        self.assertEqual(article_sections(pages), {
            "original": original, "translation": "译文",
        })

    def test_legacy_article_card_is_compact_and_does_not_truncate(self):
        original = "保留正文" * 1800
        page = markdown_text(qq_utils.article_card({"username": "作者", "text": original}))
        self.assertNotIn("# ", page)
        self.assertNotIn("内容过长，已自动截断", page)
        self.assertEqual(article_sections([page])["original"], original)


if __name__ == "__main__":
    unittest.main()
