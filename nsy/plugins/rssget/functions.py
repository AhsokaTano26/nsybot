import asyncio
from datetime import datetime
from typing import List
import random
import feedparser
import httpx
from nonebot import get_bot, get_plugin_config
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger
from nonebot_plugin_orm import get_session

from .config import Config
from .format_json import Format
from .get_id import get_id
from .models_method import (ContentManager, DetailManager, PlantformManager,
                            UserManager)
from .trans_msg import if_self_trans, if_trans
from .update_text import get_text, update_text

config = get_plugin_config(Config)

class NetworkManager:
    _client: httpx.AsyncClient = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            # 配置连接池：保持 20 个长连接，最多允许 50 个并发
            limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
            # 配置超时：连接 10s，读写 30s
            timeout = httpx.Timeout(30.0, connect=10.0)
            cls._client = httpx.AsyncClient(
                limits=limits,
                timeout=timeout,
                follow_redirects=True,
            )
        return cls._client

    @classmethod
    async def close(cls):
        if cls._client:
            await cls._client.aclose()
            logger.info("网络连接池已关闭")


# 消息发送全局限流（限制为3，防止过快发送导致风控，尤其是图片较多时）
_msg_semaphore = asyncio.Semaphore(3)

# 默认群组配置值
_DEFAULT_GROUP_CONFIG = {
    "if_need_trans": True,
    "if_need_self_trans": False,
    "if_need_translate": True,
    "if_need_photo_num_mention": True,
    "if_need_merged_message": True,
}


def _parse_group_config(group_config) -> dict:
    """从群组配置对象或None解析配置字典"""
    if group_config:
        return {
            "if_need_trans": group_config.if_need_trans,
            "if_need_self_trans": group_config.if_need_self_trans,
            "if_need_translate": group_config.if_need_translate,
            "if_need_photo_num_mention": group_config.if_need_photo_num_mention,
            "if_need_merged_message": group_config.if_need_merged_message,
        }
    return _DEFAULT_GROUP_CONFIG


async def fetch_feed(url: str) -> dict:
    """异步获取并解析RSS内容"""
    client = NetworkManager.get_client()
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)

        if parsed.bozo:  # feedparser 内部解析错误
            logger.warning(f"RSS 格式异常: {url}")

        return parsed
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP错误 {e.response.status_code}: {url}")
    except httpx.RequestError as e:
        logger.error(f"网络请求异常: {type(e).__name__} on {url}")
    except Exception as e:
        logger.exception(f"解析非预期错误: {url}")
    return {"entries": [], "error": "Fetch failed"}


class rss_get():
    @staticmethod
    async def report_status(status_url):
        """
        发送bot状态报告
        Args: status_url (str): uptime-kuma状态检查url
        """
        client = NetworkManager.get_client()

        # 使用 create_task 以后台执行，不等待响应直接继续处理下一个 RSS
        async def _do_report():
            try:
                await client.get(status_url, timeout=5)
            except Exception:
                pass

        asyncio.create_task(_do_report())

    async def send_onebot_image(self, img_url: str, group_id: int, retry_count: int = 0):
        """优化后的图片发送，支持连接池复用和优雅重试"""
        bot = get_bot()
        client = NetworkManager.get_client()

        try:
            resp = await client.get(img_url, timeout=20)
            resp.raise_for_status()

            await bot.call_api("send_group_msg", **{
                "group_id": group_id,
                "message": MessageSegment.image(resp.content)
            })
            logger.info(f"图片发送成功")

        except (httpx.HTTPError, Exception) as e:
            if retry_count < 3:
                wait_time = (retry_count + 1) * 2  # 2s, 4s, 6s
                logger.warning(f"图片下载失败，{wait_time}s 后进行第 {retry_count + 1} 次重试: {e}")
                await asyncio.sleep(wait_time)
                await self.send_onebot_image(img_url, group_id, retry_count + 1)
            else:
                logger.error(f"图片发送达到最大重试次数: {img_url}")
                # 只有最后一次失败才打扰用户
                await bot.send_group_msg(group_id=group_id, message=f"❌ 图片下载失败: {str(e)[:30]}")

    async def send_text(self,
                        group_id: int,
                        content: dict,
                        if_need_trans: int,
                        if_is_self_trans: bool,
                        if_is_trans: bool,
                        group_config=None
                        ):
        """
        发送推文内容到群组
        group_config: 预加载的群组配置对象（可选），避免每次查库
        """
        logger.opt(exception=False).info(f"正在发送内容到群 {group_id}")
        bot = get_bot()
        if_need_trans = True if if_need_trans == 1 else False

        # 使用预加载配置
        gc = _parse_group_config(group_config)
        if_need_user_trans = gc["if_need_trans"]
        if_need_self_trans = gc["if_need_self_trans"]
        if_need_translate = gc["if_need_translate"]
        if_need_photo_num_mention = gc["if_need_photo_num_mention"]
        if_need_merged_message = gc["if_need_merged_message"]

        if (if_is_self_trans and if_need_self_trans) or (if_is_trans and if_need_user_trans) or (not if_is_self_trans and not if_is_trans):
            # 构建文字消息
            msg = [
                f"🐦 用户 {content['username']} 最新动态\n"
                f"⏰ {content['time']}\n"
                f"🔗 {content['link']}"
                "\n📝 正文："
                f"{content['text']}"
            ]

            trans_msg = [
                f"{content['trans_text']}"
                f"\n【翻译由{config.model_name}提供】"
            ]

            if if_need_merged_message:
                async with _msg_semaphore:
                    await self.handle_merge_send(group_id=group_id, msg=msg, trans_msg=trans_msg, content=content)
            else:
                async with _msg_semaphore:
                    await bot.call_api("send_group_msg", **{
                        "group_id": group_id,
                        "message": "\n".join(msg)
                    })

                if if_need_trans and if_need_translate:
                    async with _msg_semaphore:
                        await bot.call_api("send_group_msg", **{
                            "group_id": group_id,
                            "message": "\n".join(trans_msg)
                        })

                logger.info("成功发送文字信息")

                # 发送图片（单独处理）
                if content["images"]:
                    if if_need_photo_num_mention:
                        async with _msg_semaphore:
                            await bot.call_api("send_group_msg", **{
                                "group_id": group_id,
                                "message": f"🖼️ 检测到 {len(content['images'])} 张图片..."
                            })
                        for index, img_url in enumerate(content["images"], 1):
                            await self.send_onebot_image(img_url, group_id)

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


    async def handle_rss(self, userid: str, group_id_list: list, group_configs: dict = None):
        """
        处理RSS推送
        group_configs: 预加载的 {group_id: Groupconfig} 字典（可选）
        """
        async with (get_session() as db_session):
            # 不再调用 User_get() 全表查询：调用方已确认用户有效
            user = await UserManager.get_Sign_by_student_id(db_session, userid)
            if not user:
                logger.error(f"用户 {userid} 不存在")
                return
            username = user.User_Name
            platform = await PlantformManager.get_Sign_by_student_id(db_session, user.Plantform)
            url = platform.url
            if_need_trans = int(platform.need_trans)
            feed_url = f"{config.rsshub_host}{url}{userid}"
            # 获取数据
            data = await fetch_feed(feed_url)

            if "error" in data:
                logger.opt(exception=False).error(data["error"])
                return

            # RssHub可用性检查
            if not data.get("entries"):
                logger.error("该用户暂无动态或不存在,尝试使用备用地址")
                try:
                    URL = config.ut_url + f"?status=up&msg={platform.name}可能暂时不可用,尝试使用备用地址&ping="
                    await self.report_status(URL)
                except Exception as e:
                    logger.opt(exception=False).error(f"发送状态检查时发生错误: {e}")

                if config.rsshub_host_back is not None:
                    for rsshub_url in config.rsshub_host_back:
                        feed_url_back = f"{rsshub_url}{url}{userid}"
                        data = await fetch_feed(feed_url_back)
                        if not data.get("entries"):
                            logger.error(f"备用地址 {rsshub_url}该用户暂无动态或不存在")
                            try:
                                URL = config.ut_url + f"?status=up&msg={platform.name}备用地址{rsshub_url}可能暂时不可用&ping="
                                await self.report_status(URL)
                            except Exception as e:
                                logger.opt(exception=False).error(f"发送状态检查时发生错误: {e}")
                            continue
                        logger.success(f"成功从备用地址获取数据: {rsshub_url}")
                    if not data.get("entries"):
                        logger.error("所有备用地址均不可用或暂无动态")
                        try:
                            URL = config.ut_url + f"?status=up&msg={platform.name}所有备用地址均失效&ping="
                            await self.report_status(URL)
                        except Exception as e:
                            logger.opt(exception=False).error(f"发送状态检查时发生错误: {e}")
                        return None
                else:
                    return

            try:
                URL = config.ut_url + f"?status=down&msg={platform.name}已恢复正常&ping="
                await self.report_status(URL)
            except Exception as e:
                logger.opt(exception=False).error(f"发送状态检查时发生错误: {e}")

            # 收集所有 entry 的 ID
            entries_info = []
            entry_count = min(3, len(data.entries))
            for data_number in range(entry_count):
                latest = data.entries[data_number]
                trueid = await get_id(latest)
                entries_info.append((latest, trueid))

            # 批量查询所有 Detail
            all_detail_ids = []
            for _, trueid in entries_info:
                for group_id in group_id_list:
                    all_detail_ids.append(f"{trueid}-{group_id}")
            existing_detail_ids = await DetailManager.get_existing_ids(db_session, all_detail_ids)

            # 逐条处理 entry
            for latest, trueid in entries_info:
                logger.info(f"正在处理 {userid} | {username} 的推文 {trueid}")

                if_is_self_trans = await if_self_trans(username, latest)
                if_is_trans = await if_trans(latest)

                # 只加载一次
                content = None
                content_loaded = False

                # 检查 Content 缓存
                existing_content = await ContentManager.get_Sign_by_student_id(db_session, trueid)

                for group_id in group_id_list:
                    id_with_group = f"{trueid}-{group_id}"
                    if id_with_group in existing_detail_ids:
                        logger.info(f"{id_with_group} 已发送")
                        continue

                    try:
                        # 按需加载
                        if not content_loaded:
                            if existing_content:
                                logger.info(f"该 {trueid} 推文本地已存在")
                                content = await get_text(trueid)
                            else:
                                logger.info(f"该 {trueid} 推文本地不存在")
                                content = await Format().extract_content(latest, if_need_trans)
                                content["username"] = username
                                content["id"] = trueid
                                await update_text(content)
                            content_loaded = True

                        # 写入 Detail 记录
                        await DetailManager.create_signmsg(
                            db_session,
                            id=id_with_group,
                            summary=content['text'],
                            updated=datetime.now(),
                        )
                        logger.info(f"创建数据: {content.get('id')}")

                        if config.if_first_time_start:
                            logger.info("第一次启动，跳过发送")
                        else:
                            # 使用预加载的群组配置
                            gc = group_configs.get(group_id) if group_configs else None
                            await self.send_text(
                                group_id=group_id,
                                content=content,
                                if_need_trans=if_need_trans,
                                if_is_self_trans=if_is_self_trans,
                                if_is_trans=if_is_trans,
                                group_config=gc,
                            )
                            # 发送完一条推文后随机等待1.5-3.5秒，避免过快发送导致风控
                            delay = random.uniform(1.5, 3.5)
                            await asyncio.sleep(delay)

                    except Exception as e:
                        logger.opt(exception=False).error(
                            f"处理 {group_id} 对 {userid} 的推文 {trueid} 时发生错误: {e}")

                    await asyncio.sleep(0.1)

    async def change_config(self):
        config.if_first_time_start = False

    async def get_signal(self):
        return str(config.if_first_time_start)
