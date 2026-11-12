import ast

from nonebot.log import logger
from nonebot_plugin_orm import get_session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .models import Content, ImageSync
from .models_method import ContentManager


async def update_text(dic):
    """缓存尽力写入；缓存失败不阻断当前原文推送。"""
    images = list(dict.fromkeys(dic.get("images") or []))
    values = {key: dic.get(key) for key in (
        "title", "time", "link", "text", "trans_text", "username",
    )}
    values.update(image_num=str(len(images)), images=str(images) if images else None)
    for attempt in range(2):
        try:
            async with get_session() as session:
                existing = await ContentManager.get_Sign_by_student_id(session, dic["id"])
                if existing is None:
                    session.add(Content(id=dic["id"], **values))
                else:
                    for key, value in values.items():
                        if key == "trans_text" and value is None and existing.trans_text:
                            continue
                        setattr(existing, key, value)
                # 先写 Content，再登记索引；两者原子提交，翻译更新不会产生新序号。
                await session.flush()
                if images and await session.scalar(select(ImageSync.seq).where(ImageSync.content_id == dic["id"])) is None:
                    session.add(ImageSync(content_id=dic["id"]))
                await session.commit()
            return True
        except IntegrityError:
            # 并发文章缓存插入冲突，关闭回滚会话后重读并更新。
            if attempt:
                logger.warning("文章缓存并发写入失败，当前仍将发送原文")
        except SQLAlchemyError as exc:
            logger.warning(f"文章缓存写入失败，当前仍将发送原文：{type(exc).__name__}")
            return False
    return False


async def get_text(id) -> dict[str, str]:
    async with (get_session() as db_session):
        dic = {}
        msg = await ContentManager.get_Sign_by_student_id(db_session, id)
        if msg is None:
            return None
        image_num = msg.image_num
        id = msg.id
        username = msg.username
        title = msg.title
        time = msg.time
        link = msg.link
        text = msg.text
        trans_text = msg.trans_text

        dic["id"] = id
        dic["title"] = title
        dic["time"] = time
        dic["link"] = link
        dic["text"] = text
        dic["trans_text"] = trans_text
        dic["username"] = username
        dic["image_num"] = image_num
        if int(image_num) == 0:
            dic["images"] = None
            logger.info(f"成功获取对于 {username} 的 {id} 推文")
            return dic
        else:
            images = ast.literal_eval(msg.images)
            if not isinstance(images, list) or not all(isinstance(url, str) for url in images):
                raise ValueError("文章缓存的图片列表格式无效")
            dic["images"] = images
            logger.info(f"成功获取对于 {username} 的 {id} 推文")
            return dic


async def cache_entries(entries_info, username: str) -> None:
    """按群订阅抓取，但完整缓存本轮条目；翻译留给实际推送。"""
    from .format_json import Format

    for entry, article_id in entries_info:
        try:
            try:
                cached = await get_text(article_id)
            except (ValueError, SyntaxError, TypeError, AttributeError):
                cached = None
            if cached is None:
                content = await Format().extract_content(entry, 0)
                content.update(id=article_id, username=username)
                await update_text(content)
        except (SQLAlchemyError, ValueError, TypeError, AttributeError) as exc:
            logger.warning(f"文章 {article_id} 全量缓存失败，将在下轮重试：{type(exc).__name__}")


async def cache_feed(entries, username: str) -> None:
    """手动查询同样复用已取得的响应，不发起额外 RSS 请求。"""
    from .get_id import get_id

    entries_info, seen = [], set()
    for entry in entries:
        try:
            article_id = await get_id(entry)
        except (ValueError, TypeError, AttributeError):
            continue
        if article_id not in seen:
            entries_info.append((entry, article_id))
            seen.add(article_id)
    await cache_entries(entries_info, username)
