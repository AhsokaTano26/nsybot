import asyncio
from datetime import datetime
import random
import feedparser
import httpx
from nonebot import get_bot, get_plugin_config
from nonebot.log import logger
from nonebot_plugin_orm import get_session

from .config import Config
from .format_json import Format
from .get_id import get_id
from .models_method import (ContentManager, DetailManager, PlantformManager,
                            UserManager)
from .trans_msg import if_self_trans, if_trans
from .update_text import get_text, update_text
from .qq import article_card, download_image, error, file_image, info, send_group_message

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
}


def _parse_group_config(group_config) -> dict:
    """从群组配置对象或None解析配置字典"""
    if group_config:
        return {
            "if_need_trans": group_config.if_need_trans,
            "if_need_self_trans": group_config.if_need_self_trans,
            "if_need_translate": group_config.if_need_translate,
            "if_need_photo_num_mention": group_config.if_need_photo_num_mention,
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

    async def send_qq_image(self, img_url: str, group_id: str, retry_count: int = 0):
        """发送官方 QQ 群图片，适配器负责将远程图片转为官方群富媒体。"""
        bot = get_bot()
        client = NetworkManager.get_client()

        try:
            # Twitter CDN 常会拒绝 QQ 服务端的二次拉取；先由机器人下载，再
            # 使用适配器的二进制上传流程发送给 QQ。
            data, file_name = await download_image(img_url, client)
            await send_group_message(bot, group_id, file_image(data, file_name))
            logger.info(f"图片发送成功")

        except (httpx.HTTPError, Exception) as e:
            if retry_count < 3:
                wait_time = (retry_count + 1) * 2  # 2s, 4s, 6s
                logger.warning(f"图片下载失败，{wait_time}s 后进行第 {retry_count + 1} 次重试: {e}")
                await asyncio.sleep(wait_time)
                await self.send_qq_image(img_url, group_id, retry_count + 1)
            else:
                logger.error(f"图片发送达到最大重试次数: {img_url}")
                # 只有最后一次失败才打扰用户
                await send_group_message(
                    bot, group_id, error(f"图片发送失败：{str(e)[:80]}", "🖼️ 图片发送失败")
                )

    async def send_text(self,
                        group_id: str,
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

        if (if_is_self_trans and if_need_self_trans) or (if_is_trans and if_need_user_trans) or (not if_is_self_trans and not if_is_trans):
            translation = None
            if if_need_trans and if_need_translate:
                translation = content.get("trans_text") or "（暂无翻译）"

            async with _msg_semaphore:
                await self.handle_markdown_send(
                    group_id=group_id,
                    content=content,
                    translation=translation,
                    if_need_photo_num_mention=if_need_photo_num_mention,
                )

    @staticmethod
    async def handle_markdown_send(
        group_id: str,
        content: dict,
        translation: str | None = None,
        if_need_photo_num_mention: bool = True,
    ):
        bot = get_bot()
        # 官方 QQ 群不支持 OneBot 自定义合并转发节点；将原文和翻译合为
        # 一条 Markdown，图片仍按官方群富媒体逐张发送。
        try:
            await send_group_message(
                bot,
                group_id,
                article_card(content, translation, config.model_name if translation else None),
            )
            images = content.get("images") or []
            if images and if_need_photo_num_mention:
                await send_group_message(
                    bot,
                    group_id,
                    info(f"共 {len(images)} 张，正在逐张发送。", "🖼️ 图片附件"),
                )
            for img_url in images:
                await rss_get().send_qq_image(img_url, group_id)
            logger.info(f"发送群 {group_id} Markdown 消息成功")
        except Exception as e:
            logger.error(f"发送群 {group_id} Markdown 消息失败: {e}")


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
