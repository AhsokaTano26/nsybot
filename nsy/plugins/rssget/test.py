import feedparser
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from io import BytesIO
from PIL import Image
from rich.console import Console


def get_rss_feed(url):
    """获取并解析 RSS 内容"""
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return feedparser.parse(response.content)
    except Exception as e:
        print(f"获取内容失败: {e}")
        return None


def get_terminal_size():
    """获取终端显示尺寸"""
    try:
        from shutil import get_terminal_size as gts
        return gts().columns // 2, gts().lines - 10
    except:
        return (40, 20)  # 默认尺寸


def show_terminal_image(url, max_size=None):
    """在终端显示图片"""
    try:
        response = requests.get(url, stream=True, timeout=10)
        img = Image.open(BytesIO(response.content))

        # 自动缩放图片
        if max_size:
            img.thumbnail((max_size[0] * 10, max_size[1] * 6))  # 根据字符比例调整

        console = Console()
        with console.capture() as capture:
            console.print(f"[image]{url}")
        return capture.get()
    except Exception as e:
        print(f"图片显示失败: {e}")
        return None


def extract_images(entry):
    """提取图片链接（优化版）"""
    sources = set()

    # 从媒体内容提取
    for media in getattr(entry, 'media_content', []):
        if media.get('type', '').startswith('image/'):
            sources.add(media['url'])

    # 从附件提取
    for enc in getattr(entry, 'enclosures', []):
        if enc.get('type', '').startswith('image/'):
            sources.add(enc.href)

    # 从HTML描述提取
    if hasattr(entry, 'description'):
        soup = BeautifulSoup(entry.description, 'html.parser')
        for img in soup.find_all('img', src=True):
            sources.add(img['src'])

    return list(sources)


def display_feed(feed):
    """带图片展示的内容显示"""
    if not feed or not feed.entries:
        print("没有获取到内容")
        return

    console = Console()
    console.print(f"\n[bold cyan]=== {feed.feed.title} ===", justify="center")

    if feed.entries:
        entry = feed.entries[0]
        # 基本信息
        published = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
        console.print(f"\n[bright_yellow]📌 {entry.title}[/]")
        console.print(f"⏰ {published}  🔗 [link]{entry.link}")

        # 清理后的文本内容
        if hasattr(entry, 'description'):
            clean_text = BeautifulSoup(entry.description, 'html.parser').get_text()
            console.print(f"[dim]{clean_text}[/]")

        # 图片显示
        images = extract_images(entry)
        if images:
            console.print("\n🖼️ [bold]图片预览:[/]")
            term_size = get_terminal_size()
            for url in images:  # 最多显示3张图片
                console.print(f"  [dim]图片地址: {url}[/]")
                show_terminal_image(url, max_size=term_size)
                console.print("\n")
        else:
            console.print("\n[dim]无图片内容[/]")

        console.print("-" * 40)


if __name__ == "__main__":
    # 配置信息
    RSSHUB_INSTANCE = "https://rsshub.app"  # 推荐使用自建实例
    TWITTER_USER = "bang_dream_info"  # 替换目标用户名

    feed_url = f"{RSSHUB_INSTANCE}/twitter/user/{TWITTER_USER}"

    console = Console()
    with console.status("[bold green]正在获取最新动态..."):
        feed_data = get_rss_feed(feed_url)

    if feed_data:
        display_feed(feed_data)