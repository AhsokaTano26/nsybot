import httpx
from nonebot import get_bot
from nonebot.log import logger
from nonebot.adapters.onebot.v11 import MessageSegment, Message

class SendMsg:
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

    async def send_text(self, entry, if_need_trans):
        logger.debug(f"send text: {entry}")