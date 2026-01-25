import time
from datetime import datetime
from typing import List

import feedparser
import httpx
import requests
from nonebot import get_bot, get_plugin_config
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger
from nonebot_plugin_orm import get_session
from sqlalchemy.exc import SQLAlchemyError

from .config import Config
from .format_json import Format
from .get_id import get_id
from .models_method import (ContentManager, DetailManager, GroupconfigManager,
                            PlantformManager, UserManager)
from .trans_msg import if_self_trans, if_trans, remove_html_tag_soup
from .update_text import get_text, update_text


async def User_get():
    async with (get_session() as db_session):
        sheet1 = await UserManager.get_all_student_id(db_session)
        return sheet1

async def User_name_get(id):
    async with (get_session() as db_session):
        sheet1 = await UserManager.get_Sign_by_student_id(db_session,id)
        return sheet1

# 配置项
TIMEOUT = 30  # 请求超时时间
config = get_plugin_config(Config)

async def fetch_feed(url: str) -> dict:
    """异步获取并解析RSS内容"""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            time.sleep(5)
            resp = await client.get(url)
            resp.raise_for_status()
            return feedparser.parse(resp.content)
    except Exception as e:
        logger.opt(exception=False).error(f"RSS请求失败: {str(e)}")
        return {"error": f"获取内容失败: {str(e)}"}


class rss_get():
    async def send_onebot_image(self,img_url: str, group_id, num):
        """OneBot 专用图片发送方法"""
        bot = get_bot()
        num += 1
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                # 下载图片数据
                resp = await client.get(img_url)
                resp.raise_for_status()

                # 构造图片消息段
                image_seg = MessageSegment.image(resp.content)

                # 发送图片
                await bot.call_api("send_group_msg", **{
                    "group_id": group_id,
                    "message": image_seg
                })

        except Exception as e:
            logger.opt(exception=False).error(f"意外错误|图片发送失败: {str(e)}  第 {num} 次重试")
            if num <= 3:
                await self.send_onebot_image(img_url, group_id, num)
            else:
                await bot.call_api("send_group_msg", **{
                    "group_id": group_id,
                    "message": f"意外错误|图片下载失败：{e} \n已达到最大重试次数"
                })

    async def send_text(self,
                        group_id: int,
                        content: dict,
                        if_need_trans: int,
                        if_is_self_trans: bool,
                        if_is_trans: bool
                        ):
        logger.opt(exception=False).info(f"正在发送内容")
        async with (get_session() as db_session):
            bot = get_bot()
            if_need_trans = True if if_need_trans == 1 else False #文章来源平台是否需要翻译
            try:
                group_config = await GroupconfigManager.get_Sign_by_group_id(db_session, group_id)
                if group_config:
                    if_need_user_trans = group_config.if_need_trans
                    if_need_self_trans = group_config.if_need_self_trans
                    if_need_translate = group_config.if_need_translate
                    if_need_photo_num_mention = group_config.if_need_photo_num_mention
                    if_need_merged_message = group_config.if_need_merged_message
                    logger.opt(exception=False).info(f"成功获取群组配置: {group_config}")
                else:
                    if_need_user_trans = True
                    if_need_self_trans = False
                    if_need_translate = True
                    if_need_photo_num_mention = True
                    if_need_merged_message = True
                    logger.opt(exception=False).info(f"使用默认群组配置")
            except SQLAlchemyError:
                logger.opt(exception=False).error(f"数据库错误")
                if_need_user_trans = True
                if_need_self_trans = False
                if_need_translate = True
                if_need_photo_num_mention = True
                if_need_merged_message = True
                logger.opt(exception=False).info(f"使用默认群组配置")

            if (if_is_self_trans and if_need_self_trans) or (if_is_trans and if_need_user_trans) or (not if_is_self_trans and not if_is_trans):
                # 构建文字消息
                msg = [
                    f"🐦 用户 {content["username"]} 最新动态\n"
                    f"⏰ {content['time']}\n"
                    f"🔗 {content['link']}"
                    "\n📝 正文："
                    f"{content['text']}"
                ]

                trans_msg = [
                    f"{content["trans_text"]}"
                    f"\n【翻译由{config.model_name}提供】"
                ]

                if if_need_merged_message:
                    await self.handle_merge_send(group_id=group_id, msg=msg, trans_msg=trans_msg, content=content)
                else:
                    await bot.call_api("send_group_msg", **{
                        "group_id": group_id,
                        "message": "\n".join(msg)
                    })

                    if if_need_trans and if_need_translate:

                        await bot.call_api("send_group_msg", **{
                            "group_id": group_id,
                            "message": "\n".join(trans_msg)
                        })

                    logger.info("成功发送文字信息")

                    # 发送图片（单独处理）
                    if content["images"]:
                        if if_need_photo_num_mention:
                            await bot.call_api("send_group_msg", **{
                                "group_id": group_id,
                                "message": f"🖼️ 检测到 {len(content['images'])} 张图片..."
                            })
                        for index, img_url in enumerate(content["images"], 1):
                            await self.send_onebot_image(img_url, group_id, num=0)

                    logger.info("成功发送图片信息")

    @staticmethod
    async def handle_merge_send(group_id, msg, trans_msg, content):
        bot = get_bot()
        # --- 1. 准备节点内容 ---

        forward_nodes = []

        # 节点 1：原文
        node1_content = MessageSegment.text(msg)
        node1 = MessageSegment.node_custom(
            user_id=config.self_id,
            nickname="Ksm 初号机",
            content=node1_content,
        )
        forward_nodes.append(node1)

        # 节点 2：翻译
        if None not in trans_msg:
            node2_content = MessageSegment.text(trans_msg)
            node2 = MessageSegment.node_custom(
                user_id=config.self_id,
                nickname="Ksm 初号机",
                content=node2_content,
            )
            forward_nodes.append(node2)

        # 节点3：图片
        if content["images"]:
            message_segments: List[MessageSegment] = [
                MessageSegment.text("")
            ]
            for index, img_url in enumerate(content["images"], 1):
                # 添加图片消息段
                message_segments.append(
                    MessageSegment.image(img_url)
                )
            node3_content = Message(message_segments)
            node3 = MessageSegment.node_custom(
                user_id=config.self_id,
                nickname="Ksm 初号机",
                content=node3_content,
            )
            forward_nodes.append(node3)


        # --- 3. 打包发送 ---
        # 将节点列表转换为一个包含所有转发节点的 Message 对象
        forward_message = Message(forward_nodes)

        try:
            # 发送合并打包消息
            await bot.send_group_msg(group_id=group_id, message=forward_message)
            logger.info(f"发送群 {group_id} 合并转发消息成功")
        except Exception as e:
            logger.error(f"发送群 {group_id} 合并转发消息失败: {e}")



    async def handle_rss(self,userid: str, group_id_list: list):
        """处理RSS推送"""
        async with (get_session() as db_session):
            sheet1 = await User_get()
            if userid in sheet1:
                plantform = await UserManager.get_Sign_by_student_id(db_session,userid)
                plantform = plantform.Plantform
                plantform_name = await PlantformManager.get_Sign_by_student_id(db_session,plantform)
                url = plantform_name.url
                if_need_trans = int(plantform_name.need_trans)
                feed_url = f"{config.rsshub_host}{url}{userid}"
                user = await User_name_get(userid)
                username = user.User_Name
                # 获取数据
                data = await fetch_feed(feed_url)

                if "error" in data:
                    logger.opt(exception=False).error(data["error"])


                if len(data.get("entries")) == 0 or not data.get("entries"):
                    logger.error("该用户暂无动态或不存在,尝试使用备用地址")
                    try:
                        URL = config.ut_url + f"?status=up&msg={plantform_name.name}可能暂时不可用,尝试使用备用地址&ping="
                        requests.get(URL)
                    except Exception as e:
                        logger.opt(exception=False).error(f"发送状态检查时发生错误: {e}")


                    if config.rsshub_host_back is not None:
                        feed_url_back = f"{config.rsshub_host_back}{url}{userid}"
                        data = await fetch_feed(feed_url_back)
                        if len(data.get("entries")) == 0 or not data.get("entries"):
                            logger.error("备用地址该用户暂无动态或不存在")
                            try:
                                URL = config.ut_url + f"?status=up&msg={plantform_name.name}备用地址可能暂时不可用&ping="
                                requests.get(URL)
                            except Exception as e:
                                logger.opt(exception=False).error(f"发送状态检查时发生错误: {e}")
                            return
                    else:
                        return

                try:
                    URL = config.ut_url + f"?status=down&msg={plantform_name.name}已恢复正常&ping="
                    requests.get(URL)
                except Exception as e:
                    logger.opt(exception=False).error(f"发送状态检查时发生错误: {e}")

                # 处理最新五条推文
                for data_number in range(0,3):
                    logger.info(f"正在处理 {userid} | {username} 的第 {data_number + 1} 条数据")
                    latest = data.entries[data_number]
                    trueid = await get_id(latest)
                    for group_id in group_id_list:
                        try:
                            logger.info(f"正在处理 {group_id} 对 {userid} | {username}的订阅")
                            id_with_group = trueid + "-" + str(group_id)
                            if_is_self_trans = await if_self_trans(username,latest)
                            if_is_trans = await if_trans(latest)
                            try:
                                existing_lanmsg = await ContentManager.get_Sign_by_student_id(
                                    db_session, trueid)
                                if existing_lanmsg:  # 本地数据库是否有推文内容
                                    logger.info(f"该 {trueid} 推文本地已存在")
                                    content = await get_text(trueid)
                                    try:
                                        # 检查数据库中是否已存在该 id 的记录
                                        existing_lanmsg = await DetailManager.get_Sign_by_student_id(
                                            db_session, id_with_group)
                                        if existing_lanmsg:  # 更新记录
                                            logger.info(f"{id_with_group} 已发送")
                                        else:
                                            try:
                                                # 写入数据库
                                                await DetailManager.create_signmsg(
                                                    db_session,
                                                    id=id_with_group,
                                                    summary=content['text'],
                                                    updated=datetime.now(),
                                                )
                                                logger.info(f"创建数据: {content.get('id')}")
                                                if config.if_first_time_start:
                                                    logger.info("第一次启动，跳过发送")
                                                    logger.debug(f"if_first_time_start：{config.if_first_time_start}")
                                                else:
                                                    logger.debug(f"if_first_time_start：{config.if_first_time_start}")

                                                    await self.send_text(group_id=group_id,
                                                                         content=content,
                                                                         if_need_trans=if_need_trans,
                                                                         if_is_self_trans=if_is_self_trans,
                                                                         if_is_trans=if_is_trans,
                                                                         )

                                            except Exception as e:
                                                logger.opt(exception=False).error(
                                                    f"处理 {content.get('id')} 时发生错误: {e}")
                                    except SQLAlchemyError as e:
                                        logger.opt(exception=False).error(f"数据库操作错误: {e}")
                                else:  # 本地数据库没有推文内容
                                    logger.info(f"该 {trueid} 推文本地不存在")
                                    try:
                                        # 检查数据库中是否已存在该 id 的记录
                                        existing_lanmsg = await DetailManager.get_Sign_by_student_id(
                                            db_session, id_with_group)
                                        if existing_lanmsg:  # 更新记录
                                            logger.info(f"{id_with_group}已发送")
                                        else:
                                            content = await Format().extract_content(latest, if_need_trans)
                                            content["username"] = username
                                            content["id"] = trueid
                                            await update_text(content)
                                            try:
                                                # 写入数据库
                                                await DetailManager.create_signmsg(
                                                    db_session,
                                                    id=id_with_group,
                                                    summary=content['text'],
                                                    updated=datetime.now(),

                                                )
                                                logger.info(f"创建数据: {content.get('id')}")
                                                if config.if_first_time_start:
                                                    logger.info("第一次启动，跳过发送")
                                                    logger.debug(f"if_first_time_start：{config.if_first_time_start}")
                                                else:
                                                    logger.debug(f"if_first_time_start：{config.if_first_time_start}")

                                                    await self.send_text(
                                                        group_id=group_id,
                                                        content=content,
                                                        if_need_trans=if_need_trans,
                                                        if_is_self_trans=if_is_self_trans,
                                                        if_is_trans=if_is_trans,
                                                    )

                                            except Exception as e:
                                                logger.opt(exception=False).error(
                                                    f"处理 {content.get('id')} 时发生错误: {e}")
                                    except SQLAlchemyError as e:
                                        logger.opt(exception=False).error(f"数据库操作错误: {e}")

                            except Exception as e:
                                logger.opt(exception=False).error(f"处理 {latest.get('title')} 时发生错误: {e}")
                        except Exception as e:
                            logger.opt(exception=False).error(f"处理 {group_id} 对 {userid} 的订阅时发生错误: {e}")
                        time.sleep(0.1)

    async def change_config(self):
        config.if_first_time_start = False

    async def get_signal(self):
        return str(config.if_first_time_start)