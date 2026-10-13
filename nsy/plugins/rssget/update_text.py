import ast

from nonebot.log import logger
from nonebot_plugin_orm import get_session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

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
                    from .models import Content
                    session.add(Content(id=dic["id"], **values))
                else:
                    for key, value in values.items():
                        setattr(existing, key, value)
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
