import httpx
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from datetime import datetime, timedelta
from io import BytesIO
from nonebot.log import logger

from .config import Config
from nonebot import get_plugin_config

config = get_plugin_config(Config)


class AvatarManager:
    """头像管理器 - 获取、缓存和生成头像"""

    CACHE_DIR = Path("data/avatars")
    CACHE_EXPIRE_DAYS = 7
    DEFAULT_SIZE = 80

    # 默认头像背景色
    COLORS = [
        (29, 155, 240),   # Twitter蓝
        (255, 122, 0),    # 橙色
        (0, 186, 124),    # 绿色
        (120, 86, 255),   # 紫色
        (249, 24, 128),   # 粉色
    ]

    def __init__(self):
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async def get_avatar(self, user_id: str, username: str) -> Image.Image:
        """
        获取用户头像

        Args:
            user_id: 用户ID
            username: 用户名（用于生成默认头像）

        Returns:
            PIL Image 对象
        """
        # 1. 检查文件缓存
        cache_path = self.CACHE_DIR / f"{user_id}.png"
        if cache_path.exists():
            mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
            if datetime.now() - mtime < timedelta(days=self.CACHE_EXPIRE_DAYS):
                try:
                    return Image.open(cache_path).convert("RGBA")
                except Exception as e:
                    logger.warning(f"读取头像缓存失败: {e}")

        # 2. 尝试从 RSSHub 获取头像
        avatar_url = await self._fetch_avatar_url(user_id)
        if avatar_url:
            avatar = await self._download_avatar(avatar_url)
            if avatar:
                try:
                    avatar.save(cache_path, "PNG")
                    logger.info(f"已缓存用户 {user_id} 的头像")
                except Exception as e:
                    logger.warning(f"保存头像缓存失败: {e}")
                return avatar

        # 3. 生成默认头像
        logger.info(f"为用户 {username} 生成默认头像")
        return self._generate_default_avatar(username)

    async def _fetch_avatar_url(self, user_id: str) -> str | None:
        """从 RSSHub feed 中提取头像 URL"""
        import feedparser

        rsshub_host = config.rsshub_host
        feed_url = f"{rsshub_host}/twitter/user/{user_id}"
        logger.info(f"尝试从 {feed_url} 获取头像")

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(feed_url)
                if resp.status_code != 200:
                    logger.warning(f"获取RSS失败，状态码: {resp.status_code}")
                    return None

                feed = feedparser.parse(resp.content)

                # RSSHub Twitter 路由在 feed.feed.image 中包含头像
                if hasattr(feed.feed, 'image') and hasattr(feed.feed.image, 'href'):
                    logger.info(f"从 feed.feed.image 获取到头像: {feed.feed.image.href}")
                    return feed.feed.image.href

                # 备用：尝试从 author_detail 获取
                if feed.entries and hasattr(feed.entries[0], 'author_detail'):
                    author = feed.entries[0].author_detail
                    if hasattr(author, 'href'):
                        logger.info(f"从 author_detail 获取到头像: {author.href}")
                        return author.href

                # 再备用：尝试从 feed.feed.author_detail 获取
                if hasattr(feed.feed, 'author_detail'):
                    author = feed.feed.author_detail
                    if hasattr(author, 'avatar'):
                        logger.info(f"从 feed.author_detail.avatar 获取到头像: {author.avatar}")
                        return author.avatar

                logger.warning(f"RSS中未找到头像信息，feed属性: {dir(feed.feed)}")

        except Exception as e:
            logger.warning(f"获取头像URL失败: {e}")

        return None

    async def _download_avatar(self, url: str) -> Image.Image | None:
        """下载头像图片"""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    image = Image.open(BytesIO(resp.content))
                    # 调整大小并转换格式
                    image = image.resize(
                        (self.DEFAULT_SIZE, self.DEFAULT_SIZE),
                        Image.Resampling.LANCZOS
                    )
                    return image.convert("RGBA")
        except Exception as e:
            logger.warning(f"下载头像失败: {e}")

        return None

    def _generate_default_avatar(self, username: str) -> Image.Image:
        """生成带首字母的默认头像"""
        # 根据用户名选择颜色
        bg_color = self.COLORS[hash(username) % len(self.COLORS)]

        # 创建图片
        img = Image.new("RGBA", (self.DEFAULT_SIZE, self.DEFAULT_SIZE), bg_color)
        draw = ImageDraw.Draw(img)

        # 获取首字母
        initial = username[0].upper() if username else "?"

        # 加载字体
        font = self._get_font(36)

        # 计算文字位置（居中）
        bbox = draw.textbbox((0, 0), initial, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (self.DEFAULT_SIZE - text_width) // 2
        y = (self.DEFAULT_SIZE - text_height) // 2 - bbox[1]

        # 绘制文字
        draw.text((x, y), initial, fill=(255, 255, 255), font=font)

        return img

    def _get_font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """获取字体，带回退机制"""
        font_paths = [
            # 自定义字体路径
            config.card_font_path if config.card_font_path else "",
            # Windows
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            # macOS
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            # Linux
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]

        for path in font_paths:
            if path and Path(path).exists():
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue

        # 回退到默认字体
        return ImageFont.load_default()

    def make_circle(self, avatar: Image.Image) -> Image.Image:
        """将头像裁剪为圆形"""
        size = avatar.size[0]

        # 创建圆形蒙版
        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, size, size), fill=255)

        # 创建输出图片
        output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        output.paste(avatar, (0, 0))
        output.putalpha(mask)

        return output


# 全局实例
avatar_manager = AvatarManager()
