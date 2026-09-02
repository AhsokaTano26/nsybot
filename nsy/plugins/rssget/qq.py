"""QQ 官方 Bot 的消息与事件辅助函数。

业务代码只通过本模块处理官方群 OpenID、群消息和 Markdown，避免再次
耦合到 OneBot 的 ``group_id``、CQ 码或自定义合并转发节点。
"""

from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx
from nonebot.adapters.qq import Bot, Event, Message, MessageSegment
from nonebot.adapters.qq.event import C2CMessageCreateEvent, GroupMessageCreateEvent

MAX_IMAGE_BYTES = 10 * 1024 * 1024
# QQ Markdown 的实际限制会随消息类型调整。这里采用低于常见上限的保守值，
# 为代码块闭合和截断提示预留空间，避免整条消息被接口拒绝。
MAX_MARKDOWN_CHARS = 3500
_TRUNCATION_NOTICE = "\n\n> 内容过长，已自动截断。"
_IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_IMAGE_HEADERS = {
    "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
    "Referer": "https://x.com/",
    "User-Agent": "Mozilla/5.0 (compatible; nsybot/1.0)",
}


def group_openid(event: GroupMessageCreateEvent) -> str:
    """返回 QQ 官方群聊的稳定标识。"""
    return str(event.group_openid)


def user_openid(event: Event) -> str:
    """返回 QQ 官方事件中的用户 OpenID。"""
    return str(event.get_user_id())


async def is_group_event(event: Event) -> bool:
    return isinstance(event, GroupMessageCreateEvent)


async def is_c2c_event(event: Event) -> bool:
    return isinstance(event, C2CMessageCreateEvent)


async def send_group_message(
    bot: Bot,
    group_id: str,
    message: str | Message | MessageSegment,
):
    """向官方群主动发送文本、Markdown 或富媒体消息。"""
    if isinstance(message, str):
        message = markdown(message)
    return await bot.send_to_group(group_openid=str(group_id), message=message)


async def send_group_markdown(bot: Bot, group_id: str, markdown: str):
    """使用官方群 Markdown 替代 OneBot 合并转发。"""
    return await send_group_message(
        bot, group_id, MessageSegment.markdown(markdown)
    )


def markdown(content: str) -> MessageSegment:
    return MessageSegment.markdown(truncate_markdown(content))


def truncate_markdown(content: str, limit: int = MAX_MARKDOWN_CHARS) -> str:
    """Keep QQ Markdown safely below the configured message length limit."""
    if len(content) <= limit:
        return content

    # Reserve room to close an open fenced code block and to explain truncation.
    body_limit = max(0, limit - len(_TRUNCATION_NOTICE) - 4)
    truncated = content[:body_limit].rstrip()
    if truncated.count("```") % 2:
        truncated += "\n```"
    return f"{truncated}{_TRUNCATION_NOTICE}"


def code_block(content: str) -> str:
    """Render external RSS text literally and prevent it from closing the block."""
    safe_content = (content or "（无内容）").replace("```", "``\u200b`")
    return f"```\n{safe_content}\n```"


def quote_block(content: str) -> str:
    """Render multi-line RSS text using the same quote style as message metadata."""
    return "\n".join(f"> {line}" if line else ">" for line in (content or "（无内容）").splitlines())


def card(title: str, body: str) -> MessageSegment:
    """Create a consistent QQ Markdown card for command and status replies."""
    return markdown(f"# {title}\n\n{body.strip()}")


def success(body: str, title: str = "✅ 操作完成") -> MessageSegment:
    return card(title, body)


def info(body: str, title: str = "ℹ️ 提示") -> MessageSegment:
    return card(title, body)


def warning(body: str, title: str = "⚠️ 请注意") -> MessageSegment:
    return card(title, body)


def error(body: str, title: str = "❌ 操作失败") -> MessageSegment:
    return card(title, body)


def article_card(
    content: dict,
    translation: str | None = None,
    translation_source: str | None = None,
) -> MessageSegment:
    """Render an RSS entry as one readable QQ Markdown message."""
    username = content.get("username", "未知用户")
    time = content.get("time", "未知时间")
    link = content.get("link")
    text = content.get("text") or "（无正文）"
    meta = f"> ⏰ {time}"
    if link:
        meta += f"  ·  [查看原文]({link})"

    parts = [
        f"# 🐦 @{username} 的新动态",
        meta,
        quote_block(f"📝 正文\n{text}"),
    ]
    if translation:
        parts.append(quote_block(f"🌐 中文翻译\n{translation}"))
        if translation_source:
            parts.append(f"> 翻译由 {translation_source} 提供")
    return markdown("\n\n".join(parts))


def file_image(data: bytes, file_name: str) -> MessageSegment:
    """创建由机器人上传二进制内容的官方群图片消息。"""
    return MessageSegment.file_image(data, file_name)


async def download_image(
    url: str, client: httpx.AsyncClient | None = None
) -> tuple[bytes, str]:
    """Download an image locally for upload, avoiding QQ's remote URL fetch."""
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=30, follow_redirects=True)

    try:
        assert client is not None
        async with client.stream("GET", url, headers=_IMAGE_HEADERS) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0]
            if content_type and content_type not in _IMAGE_EXTENSIONS:
                raise ValueError(f"远程地址未返回图片（Content-Type: {content_type}）")

            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    raise ValueError("图片超过 10 MiB 上传上限")
                chunks.append(chunk)

        suffix = _IMAGE_EXTENSIONS.get(content_type)
        if not suffix:
            suffix = PurePosixPath(urlparse(url).path).suffix or ".jpg"
        return b"".join(chunks), f"rss-image{suffix}"
    finally:
        if owns_client:
            await client.aclose()
