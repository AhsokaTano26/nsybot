from nonebot import get_plugin_config, on_command
from nonebot.plugin import PluginMetadata

from .config import Config
import nonebot

nonebot.init(command_start={"", ""}, command_sep={".", " "})

__plugin_meta__ = PluginMetadata(
    name="small_child",
    description="",
    usage="",
    config=Config,
)

small_child1 = on_command("渡月", priority=10)
small_child2 = on_command("jsylx", priority=10)
small_child3 = on_command("富哥",aliases={"有钱"}, priority=10)
small_child4 = on_command("佑佑姐", aliases={"佑佑"},priority=10)
small_child5 = on_command("Shion", aliases={"ako酱"},priority=10)
@small_child1.handle()
async def handle_rss():
    await small_child1.send("渡月是好人")
@small_child2.handle()
async def handle_rss():
    await small_child1.send("jsylx怎么这么坏啊")
@small_child3.handle()
async def handle_rss():
    await small_child1.send("幕了")
@small_child4.handle()
async def handle_rss():
    await small_child1.send("是坏蛋美人哟❥(^_-)")
@small_child5.handle()
async def handle_rss():
    await small_child1.send("是铸币")