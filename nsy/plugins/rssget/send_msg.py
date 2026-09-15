import httpx
from nonebot import get_bot
from nonebot.log import logger

from nsy.qq_utils import download_image, error, file_image, send_group_message

class SendMsg:
    async def send_qq_image(self, img_url: str, group_id: str, num: int = 0):
        """QQ 官方 Bot 图片发送方法。"""
        bot = get_bot()
        num += 1
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                data, file_name = await download_image(img_url, client)
                await send_group_message(
                    bot, str(group_id), file_image(data, file_name)
                )

        except Exception as e:
            logger.opt(exception=False).error(f"意外错误|图片发送失败: {str(e)}  第 {num} 次重试")
            if num <= 3:
                await self.send_qq_image(img_url, group_id, num)
            else:
                await send_group_message(
                    bot, str(group_id),
                    error(f"图片发送失败：{e}\n\n已达到最大重试次数。", "🖼️ 图片发送失败"),
                )

    async def send_text(self, entry, if_need_trans):
        logger.debug(f"send text: {entry}")
