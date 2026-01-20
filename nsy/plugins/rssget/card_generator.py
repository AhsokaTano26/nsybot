"""
Twitter 风格推文卡片生成器

使用 Pillow 和 Pilmoji 生成支持中英日韩文及彩色 Emoji 的推文卡片图片。

字体要求:
    - 推荐使用 Noto Sans CJK 字体以获得最佳的多语言支持
    - 将字体文件放置于 data/fonts/ 目录下
    - 支持的字体格式: .ttf, .otf, .ttc

依赖:
    - Pillow: 图像处理
    - pilmoji: Emoji 渲染支持
    - httpx: 异步图片下载
"""

import asyncio
import re
from io import BytesIO
from pathlib import Path

import httpx
from nonebot import get_plugin_config
from nonebot.log import logger
from PIL import Image, ImageDraw, ImageFont
from pilmoji import Pilmoji
from pilmoji.source import (AppleEmojiSource, GoogleEmojiSource,
                            TwitterEmojiSource)

from .avatar_manager import avatar_manager
from .config import Config

config = get_plugin_config(Config)

# 需要清理的特殊 Unicode 字符（会导致方框显示）
_INVISIBLE_CHARS = re.compile(
    r'[\uFE0F\uFE0E\u200D\u200B\u200C\u200E\u200F\u2060\u2061\u2062\u2063\u2064\uFEFF]'
)


def _clean_text(text: str) -> str:
    """清理文本中可能导致方框显示的不可见字符"""
    if not text:
        return text
    # 移除变体选择符和零宽字符（pilmoji 处理 emoji 后可能残留）
    return _INVISIBLE_CHARS.sub('', text)


class TwitterCardGenerator:
    """Twitter 风格卡片生成器"""

    # 颜色主题
    COLORS = {
        "background": (255, 255, 255),       # 白色背景
        "text_primary": (15, 20, 25),        # 主文本色
        "text_secondary": (83, 100, 113),    # 次要文本色
        "divider": (239, 243, 244),          # 分割线
        "trans_bg": (247, 249, 250),         # 翻译区背景
        "link": (29, 155, 240),              # 链接色
    }

    # 布局参数
    CARD_WIDTH = 600
    PADDING = 20
    AVATAR_SIZE = 56
    MAX_IMAGES = 4
    IMAGE_SPACING = 8

    def __init__(self):
        self._font_cache: dict[str, ImageFont.FreeTypeFont] = {}

    async def generate(self, content: dict) -> bytes:
        """
        生成卡片图片

        Args:
            content: 推文内容字典，包含 username, text, trans_text, time, link, images
            username: 用户ID（如 tanda_hazuki）
            可选: display_name 显示名称（如 反田葉月 哈酱，，，），如果没有则使用 username(userid)

        Returns:
            PNG 图片的 bytes
        """
        user_id = content.get("username", "Unknown")  # 用户ID，如 tanda_hazuki
        display_name = content.get("display_name", user_id)  # 显示名称，如 反田葉月
        text = content.get("text", "") or ""
        trans_text = content.get("trans_text")
        time_str = content.get("time", "") or ""
        images = (content.get("images") or [])[:self.MAX_IMAGES]

        # 获取头像
        avatar = await avatar_manager.get_avatar(user_id, display_name)
        avatar = avatar_manager.make_circle(avatar)
        avatar = avatar.resize((self.AVATAR_SIZE, self.AVATAR_SIZE), Image.Resampling.LANCZOS)

        # 预计算各区域高度
        content_width = self.CARD_WIDTH - 2 * self.PADDING

        # 文本字体
        text_font = self._get_font(16)
        display_name_font = self._get_font(15, bold=True)
        user_id_font = self._get_font(13)
        time_font = self._get_font(13)
        trans_font = self._get_font(15)

        # 计算原文高度
        text_lines = self._wrap_text(text, text_font, content_width)
        text_height = len(text_lines) * 24 if text_lines else 0

        # 计算翻译高度（包含标题、内容、来源标注）
        trans_lines = []
        trans_height = 0
        if trans_text:
            trans_lines = self._wrap_text(trans_text, trans_font, content_width - 24)
            # 标题(20) + 内容 + 来源(18) + 内边距(16) + 外边距(12)
            trans_height = 20 + len(trans_lines) * 22 + 18 + 16 + 12 if trans_lines else 0

        # 计算图片区域高度
        images_height = 0
        downloaded_images = []
        if images:
            downloaded_images = await self._download_images(images)
            if downloaded_images:
                images_height = self._calc_images_height(len(downloaded_images)) + 16

        # 计算总高度并创建画布
        header_height = self.AVATAR_SIZE + 20
        total_height = (
            self.PADDING +           # 顶部边距
            header_height +          # 头像和用户名
            text_height + 16 +       # 原文
            trans_height +           # 翻译（如果有）
            images_height +          # 图片（如果有）
            40 +                     # 底部区域
            self.PADDING             # 底部边距
        )

        image = Image.new("RGB", (self.CARD_WIDTH, total_height), self.COLORS["background"])
        draw = ImageDraw.Draw(image)

        y_offset = self.PADDING

        # 绘制头像和用户信息
        y_offset = self._draw_header(
            draw, image, avatar, display_name, user_id, time_str,
            display_name_font, user_id_font, time_font, y_offset
        )

        # 绘制原文和翻译
        y_offset = self._draw_content(
            draw, image, text_lines, trans_lines, text_font, trans_font, y_offset,
            has_translation=bool(trans_text and trans_lines)
        )

        # 绘制图片
        if downloaded_images:
            y_offset = self._draw_images(image, downloaded_images, y_offset)

        # 7. 绘制底部
        self._draw_footer(draw, y_offset)

        # 导出为 bytes
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """获取字体，带缓存"""
        cache_key = f"{size}_{bold}"
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]

        # 项目字体目录
        project_font_dir = Path("data/fonts")

        font_paths = [
            # 自定义字体（优先级最高）
            config.card_font_path if config.card_font_path else "",
            # 项目目录字体 - 推荐使用 Noto Sans CJK（支持中日韩英文）
            # 本地部署：下载 https://github.com/notofonts/noto-cjk/releases 放到 data/fonts/
            # Docker：apt install fonts-noto-cjk fonts-noto
            str(project_font_dir / ("NotoSansCJKsc-Bold.otf" if bold else "NotoSansCJKsc-Regular.otf")),
            str(project_font_dir / ("NotoSansCJK-Bold.ttc" if bold else "NotoSansCJK-Regular.ttc")),
            str(project_font_dir / "NotoSansSC-VariableFont_wght.ttf"),
            # Windows 字体
            "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",  # 微软雅黑（中日韩）
            "C:/Windows/Fonts/seguisym.ttf",  # Segoe UI Symbol（特殊符号）
            "C:/Windows/Fonts/yugothb.ttc" if bold else "C:/Windows/Fonts/yugothic.ttc",  # 游ゴシック（日文）
            "C:/Windows/Fonts/malgun.ttf",  # Malgun Gothic（韩文）
            "C:/Windows/Fonts/simsun.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            # macOS
            "/System/Library/Fonts/PingFang.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Apple Symbols.ttf",
            # Linux（apt install fonts-noto-cjk fonts-noto）
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        ]

        for path in font_paths:
            if path and Path(path).exists():
                try:
                    font = ImageFont.truetype(path, size)
                    self._font_cache[cache_key] = font
                    return font
                except Exception:
                    continue

        return ImageFont.load_default()

    def _wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
        """文本自动换行，支持中日英混排"""
        if not text:
            return []

        # 清理可能导致方框的不可见字符
        text = _clean_text(text)

        lines = []
        # 先按换行符分割
        paragraphs = text.split('\n')

        for paragraph in paragraphs:
            if not paragraph:
                lines.append("")
                continue

            current_line = ""
            for char in paragraph:
                test_line = current_line + char
                bbox = font.getbbox(test_line)
                if bbox[2] > max_width:
                    if current_line:
                        lines.append(current_line)
                    current_line = char
                else:
                    current_line = test_line

            if current_line:
                lines.append(current_line)

        return lines

    def _draw_header(
        self, draw: ImageDraw.ImageDraw, image: Image.Image,
        avatar: Image.Image, display_name: str, user_id: str, time_str: str,
        display_name_font: ImageFont.FreeTypeFont, user_id_font: ImageFont.FreeTypeFont,
        time_font: ImageFont.FreeTypeFont, y_offset: int
    ) -> int:
        """绘制头像和用户信息区域（Twitter风格）"""
        # 粘贴头像
        image.paste(avatar, (self.PADDING, y_offset), avatar)

        text_x = self.PADDING + self.AVATAR_SIZE + 12

        # 显示名称（粗体，主色）
        draw.text(
            (text_x, y_offset + 4),
            display_name,
            fill=self.COLORS["text_primary"],
            font=display_name_font
        )

        # @用户ID（灰色小字）
        draw.text(
            (text_x, y_offset + 22),
            f"@{user_id}",
            fill=self.COLORS["text_secondary"],
            font=user_id_font
        )

        # 时间（灰色小字，在@用户ID右边）
        user_id_bbox = draw.textbbox((text_x, y_offset + 22), f"@{user_id}", font=user_id_font)
        time_x = user_id_bbox[2] + 8  # @用户ID 右边留 8px 间距
        draw.text(
            (time_x, y_offset + 22),
            f"· {time_str}",
            fill=self.COLORS["text_secondary"],
            font=time_font
        )

        return y_offset + self.AVATAR_SIZE + 20

    def _draw_content(
        self, draw: ImageDraw.ImageDraw, image: Image.Image,
        text_lines: list[str], trans_lines: list[str],
        text_font: ImageFont.FreeTypeFont, trans_font: ImageFont.FreeTypeFont,
        y_offset: int, has_translation: bool = False
    ) -> int:
        """
        绘制原文和翻译内容
        """
        content_width = self.CARD_WIDTH - 2 * self.PADDING
        line_height_text = 24
        line_height_trans = 22

        # 使用单个 Pilmoji 上下文处理所有文本绘制
        # 使用 Twitter emoji 源，并在网络失败时回退到纯文本
        try:
            with Pilmoji(image, source=TwitterEmojiSource) as pilmoji:
                # 绘制原文
                for line in text_lines:
                    pilmoji.text(
                        (self.PADDING, y_offset),
                        line,
                        fill=self.COLORS["text_primary"],
                        font=text_font
                    )
                    y_offset += line_height_text

                y_offset += 16  # 原文后间距

                # 绘制翻译区域（如果有）
                if has_translation and trans_lines:
                    y_offset = self._draw_translation_block(
                        draw, pilmoji, y_offset, content_width,
                        trans_lines, line_height_trans
                    )
        except Exception as e:
            # 网络失败时回退到纯 PIL 绘制（无 emoji）
            logger.warning(f"Pilmoji 渲染失败，回退到纯文本模式: {e}")
            for line in text_lines:
                draw.text(
                    (self.PADDING, y_offset),
                    line,
                    fill=self.COLORS["text_primary"],
                    font=text_font
                )
                y_offset += line_height_text

            y_offset += 16

            if has_translation and trans_lines:
                y_offset = self._draw_translation_block_fallback(
                    draw, y_offset, content_width,
                    trans_lines, line_height_trans
                )

        return y_offset

    def _draw_translation_block(
        self, draw: ImageDraw.ImageDraw, pilmoji: Pilmoji,
        y_offset: int, content_width: int,
        trans_lines: list[str], line_height_trans: int
    ) -> int:
        """绘制翻译区块（使用 Pilmoji）"""
        trans_title_height = 20
        trans_content_height = len(trans_lines) * line_height_trans
        trans_footer_height = 18
        block_height = trans_title_height + trans_content_height + trans_footer_height + 16

        # 绘制翻译背景
        draw.rectangle(
            [self.PADDING, y_offset, self.PADDING + content_width, y_offset + block_height],
            fill=self.COLORS["trans_bg"]
        )
        # 左侧强调线
        draw.rectangle(
            [self.PADDING, y_offset, self.PADDING + 3, y_offset + block_height],
            fill=self.COLORS["link"]
        )

        # 翻译标题
        trans_title_font = self._get_font(12)
        pilmoji.text(
            (self.PADDING + 12, y_offset + 6),
            "📝 翻译",
            fill=self.COLORS["text_secondary"],
            font=trans_title_font
        )

        # 翻译内容
        trans_font = self._get_font(15)
        text_y = y_offset + trans_title_height + 8
        for line in trans_lines:
            pilmoji.text(
                (self.PADDING + 12, text_y),
                line,
                fill=self.COLORS["text_primary"],
                font=trans_font
            )
            text_y += line_height_trans

        # 翻译来源标注
        source_font = self._get_font(11)
        draw.text(
            (self.PADDING + 12, y_offset + block_height - 16),
            "由 DeepSeek 翻译",
            fill=self.COLORS["text_secondary"],
            font=source_font
        )

        return y_offset + block_height + 12

    def _draw_translation_block_fallback(
        self, draw: ImageDraw.ImageDraw,
        y_offset: int, content_width: int,
        trans_lines: list[str], line_height_trans: int
    ) -> int:
        """绘制翻译区块（回退模式，无 emoji）"""
        trans_title_height = 20
        trans_content_height = len(trans_lines) * line_height_trans
        trans_footer_height = 18
        block_height = trans_title_height + trans_content_height + trans_footer_height + 16

        # 绘制翻译背景
        draw.rectangle(
            [self.PADDING, y_offset, self.PADDING + content_width, y_offset + block_height],
            fill=self.COLORS["trans_bg"]
        )
        draw.rectangle(
            [self.PADDING, y_offset, self.PADDING + 3, y_offset + block_height],
            fill=self.COLORS["link"]
        )

        # 翻译标题（无 emoji）
        trans_title_font = self._get_font(12)
        draw.text(
            (self.PADDING + 12, y_offset + 6),
            "翻译",
            fill=self.COLORS["text_secondary"],
            font=trans_title_font
        )

        # 翻译内容
        trans_font = self._get_font(15)
        text_y = y_offset + trans_title_height + 8
        for line in trans_lines:
            draw.text(
                (self.PADDING + 12, text_y),
                line,
                fill=self.COLORS["text_primary"],
                font=trans_font
            )
            text_y += line_height_trans

        # 翻译来源标注
        source_font = self._get_font(11)
        draw.text(
            (self.PADDING + 12, y_offset + block_height - 16),
            "由 DeepSeek 翻译",
            fill=self.COLORS["text_secondary"],
            font=source_font
        )

        return y_offset + block_height + 12

    async def _download_images(self, urls: list[str]) -> list[Image.Image]:
        """并发下载图片"""
        async def download_single(client: httpx.AsyncClient, url: str) -> Image.Image | None:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return Image.open(BytesIO(resp.content)).convert("RGB")
            except Exception as e:
                logger.warning(f"下载图片失败 {url}: {e}")
            return None

        async with httpx.AsyncClient(timeout=20) as client:
            tasks = [download_single(client, url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        return [img for img in results if isinstance(img, Image.Image)]

    def _calc_images_height(self, count: int) -> int:
        """计算图片区域高度"""
        content_width = self.CARD_WIDTH - 2 * self.PADDING

        if count == 1:
            return int(content_width * 0.6)  # 16:10 比例
        elif count == 2:
            return int((content_width - self.IMAGE_SPACING) / 2 * 0.75)
        else:  # 3 or 4
            single_width = (content_width - self.IMAGE_SPACING) / 2
            return int(single_width * 0.75 * 2 + self.IMAGE_SPACING)

    def _draw_images(self, image: Image.Image, images: list[Image.Image], y_offset: int) -> int:
        """绘制图片网格"""
        content_width = self.CARD_WIDTH - 2 * self.PADDING
        count = len(images)

        if count == 1:
            # 单张图片 - 全宽
            img = images[0]
            target_height = int(content_width * 0.6)
            img = self._resize_cover(img, content_width, target_height)
            image.paste(img, (self.PADDING, y_offset))
            return y_offset + target_height + 16

        elif count == 2:
            # 两张图片 - 并排
            single_width = (content_width - self.IMAGE_SPACING) // 2
            single_height = int(single_width * 0.75)

            for i, img in enumerate(images):
                img = self._resize_cover(img, single_width, single_height)
                x = self.PADDING + i * (single_width + self.IMAGE_SPACING)
                image.paste(img, (x, y_offset))

            return y_offset + single_height + 16

        else:  # 3 or 4
            # 网格布局
            single_width = (content_width - self.IMAGE_SPACING) // 2
            single_height = int(single_width * 0.75)

            for i, img in enumerate(images[:4]):
                img = self._resize_cover(img, single_width, single_height)
                row = i // 2
                col = i % 2
                x = self.PADDING + col * (single_width + self.IMAGE_SPACING)
                y = y_offset + row * (single_height + self.IMAGE_SPACING)
                image.paste(img, (x, y))

            rows = (min(count, 4) + 1) // 2
            return y_offset + rows * single_height + (rows - 1) * self.IMAGE_SPACING + 16

    def _resize_cover(self, img: Image.Image, target_width: int, target_height: int) -> Image.Image:
        """裁剪并缩放图片以填充目标区域（cover模式）"""
        img_ratio = img.width / img.height
        target_ratio = target_width / target_height

        if img_ratio > target_ratio:
            # 图片更宽，按高度缩放后裁剪宽度
            new_height = target_height
            new_width = int(img.width * target_height / img.height)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            left = (new_width - target_width) // 2
            img = img.crop((left, 0, left + target_width, target_height))
        else:
            # 图片更高，按宽度缩放后裁剪高度
            new_width = target_width
            new_height = int(img.height * target_width / img.width)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            top = (new_height - target_height) // 2
            img = img.crop((0, top, target_width, top + target_height))

        return img

    def _draw_footer(self, draw: ImageDraw.ImageDraw, y_offset: int):
        """绘制底部区域"""
        footer_font = self._get_font(12)
        draw.text(
            (self.PADDING, y_offset),
            "via nsybot",
            fill=self.COLORS["text_secondary"],
            font=footer_font
        )


# 全局实例
card_generator = TwitterCardGenerator()
