from nonebot_plugin_orm import get_session
from nonebot.log import logger
from sqlalchemy.exc import SQLAlchemyError
import ast

from .models_method import ContentManger
async def update_text(dic):
    id = dic["id"]
    title = dic["title"]
    time = dic["time"]
    link = dic["link"]
    text = dic["text"]
    trans_text = dic["trans_text"]
    username = dic["username"]
    if dic["images"]:
        image_num = len(dic["images"])
        image = dic["images"]
        images = str(image)
        try:
            async with (get_session() as db_session):
                existing_lanmsg = await ContentManger.get_Sign_by_student_id(
                        db_session, id)
                if existing_lanmsg:  # 更新记录
                        logger.info(f"对于 {username} 的 {id} 推文已存在")
                else:
                    try:
                        # 写入数据库
                        await ContentManger.create_signmsg(
                            db_session,
                            id=id,
                            username=username,
                            title=title,
                            time=time,
                            link=link,
                            text=text,
                            trans_text=trans_text,
                            image_num=image_num,
                            images=images
                            )
                        logger.info(f"成功创建对于 {username} 的 {id} 推文")
                    except Exception as e:
                        logger.error(f"创建对于 {username} 的 {id} 推文时发生错误: {e}")
        except SQLAlchemyError as e:
            logger.error(f"数据库操作错误: {e}")
    else:
        try:
            async with (get_session() as db_session):
                existing_lanmsg = await ContentManger.get_Sign_by_student_id(
                        db_session, id)
                if existing_lanmsg:  # 更新记录
                        logger.info(f"对于 {username} 的 {id} 推文已存在")
                else:
                    try:
                        # 写入数据库
                        await ContentManger.create_signmsg(
                            db_session,
                            id=id,
                            username=username,
                            title=title,
                            time=time,
                            link=link,
                            text=text,
                            trans_text=trans_text,
                            image_num=0,
                            )
                        logger.info(f"成功创建对于 {username} 的 {id} 推文")
                    except Exception as e:
                        logger.error(f"创建对于 {username} 的 {id} 推文时发生错误: {e}")
        except SQLAlchemyError as e:
            logger.error(f"数据库操作错误: {e}")
    return True




async def get_text(id) -> dict[str, str]:
    async with (get_session() as db_session):
        dic = {}
        msg = await ContentManger.get_Sign_by_student_id(db_session, id)
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
            dic["images"] = images
            logger.info(f"成功获取对于 {username} 的 {id} 推文")
            return dic