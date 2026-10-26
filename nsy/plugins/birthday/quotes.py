"""将引用的生日语录逐群发送，保留正文及各个富媒体附件。"""

from collections.abc import Callable
import re

from markdown_it import MarkdownIt
from nonebot.adapters.qq import Bot, Message, MessageSegment
from nonebot.log import logger
from sqlalchemy.ext.asyncio import AsyncSession

from nsy.qq_utils import MAX_MARKDOWN_CHARS, download_image, file_image, send_group_message

from .store import BirthdayStore


async def quote_messages(quote: Message) -> list[MessageSegment]:
    """先准备全部附件；正文与媒体分开发，避免适配器只发送其中一部分。"""
    media_types = {"image", "audio", "video", "file"}
    text_types = {"text", "emoji", "mention_user", "mention_channel", "mention_everyone"}
    if any(segment.type not in media_types | text_types for segment in quote):
        raise ValueError("引用消息含有暂不支持的消息类型，请引用文本、图片、语音、视频或文件。")

    messages = []
    text = quote.extract_content(escape_text=False)
    if text.strip():
        boundaries = {len(text)}
        if len(text) > MAX_MARKDOWN_CHARS:
            # 只在完整顶层块之间切分；单个代码块、列表或行内格式不能截断。
            offsets = [0, *(match.end() for match in re.finditer(r"\r\n|\r|\n", text))]
            env = {}
            tokens = MarkdownIt("commonmark").parse(text, env)
            if env.get("references"):
                raise ValueError("引用内容过长且含引用式链接，请改为行内链接或拆分原文后重新引用。")
            boundaries.update(offsets[token.map[0]] for token in tokens if token.level == 0 and token.map)
        start = 0
        while start < len(text):
            end = max((pos for pos in boundaries if start < pos <= start + MAX_MARKDOWN_CHARS), default=start)
            if end == start:
                raise ValueError(f"引用消息的单段富文本过长（最多 {MAX_MARKDOWN_CHARS} 字符），请拆分原文后重新引用。")
            messages.append(MessageSegment.markdown(text[start:end]))
            start = end

    for segment in quote:
        if segment.type == "image":
            try:
                data, file_name = await download_image(segment.data["url"])
            except Exception as exc:
                logger.warning(f"生日语录图片准备失败: {exc}")
                raise ValueError("生日语录图片准备失败，未向任何群发送，请稍后重试。") from exc
            messages.append(file_image(data, file_name))
        elif segment.type in media_types:
            messages.append(segment.copy())
    if not messages:
        raise ValueError("引用消息内容为空，请引用要发送的生日语录。")
    return messages


async def broadcast_quote(
    bot: Bot,
    source_group_id: str,
    quote: Message,
    session_factory: Callable[[], AsyncSession],
) -> tuple[int, int]:
    """仅向仍有生日标签订阅的其他群发送；返回完整成功群数和失败群数。"""
    # 在数据库会话外下载和发送，复用同一份图片字节，不修改昵称提醒状态。
    async with session_factory() as session:
        groups = [
            group.group_id for group in await BirthdayStore(session).list_groups()
            if group.subscribed_tags and group.group_id != source_group_id
        ]
    if not groups:
        return 0, 0

    messages = await quote_messages(quote)
    sent = failed = 0
    for group_id in groups:
        try:
            for message in messages:
                await send_group_message(bot, group_id, message.copy())
        except Exception as exc:
            failed += 1
            logger.warning(f"生日语录发送失败，群 {group_id}: {exc}")
            continue
        sent += 1
    logger.info(f"生日语录发送完成：成功 {sent} 群，失败 {failed} 群，已排除来源群 {source_group_id}")
    return sent, failed
