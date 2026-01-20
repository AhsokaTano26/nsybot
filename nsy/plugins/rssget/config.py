from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""
    # 插件配置
    rsshub_host: str = "https://rsshub.app"
    rsshub_host_back: str | None = None
    refresh_time: int = 20
    model_name: str = "None"
    api_key: str | None = None
    secret_key: str | None = None
    self_id: int = 10001
    ut_url: str | None = None

    # 卡片生成配置
    card_enabled: bool = True
    card_width: int = 600
    card_font_path: str | None = None

    # 群组配置
    ignored_groups: list[int] = []
    if_first_time_start: bool = True

    # 帮助信息
    help_msg_1: str = """nsy 推文助手：订阅三步走
——————
想让机器人自动转发推特/b站？请按以下顺序操作：
第一步：查 🔍
发送命令：
用户列表
确认你想看的博主是否在名单里。
第二步：加 ➕
如果你想看的博主不在名单里，请联系public@tano.asia
发送博主信息申请添加：
用户ID 用户ID 平台名
第三步：订 🔔
名单里有了之后，发送订阅命令：
订阅 用户ID 群号
例：订阅 aibaaiai 群号
——————
📜常用命令快捷手册：
🔹随便看看：
•看最新推文：rss 用户ID
•看往期文章：rss 用户ID 序号
•用户推文集：文章列表 用户ID
🔹管理订阅：
•查看所有订阅：订阅列表
•取消订阅：取消订阅 用户ID 群号
•查群订阅详情：查询 群组 群号
•查询博主被哪些群订阅：查询 用户 用户ID
⚠️避坑小贴士：
1.必须是列表里的用户才能订阅，不在请联系开发者！
2.用户ID指推特用户主页@之后内容或者b站uid！
2.只有群组管理员/群主可增加订阅或取消订阅。
3.指令之间要有空格，不要带 {} 括号。
4.序号不填默认为 0（最新一条）。
——————
⭐ 项目开源地址：
https://github.com/AhsokaTano26/nsybot"""

    help_msg_2: str = """群组功能设置 (V3.1.0)
——————
你可以通过发送 群组配置 加上六个数字，来决定机器人的工作方式。
数字 1 代表开启，数字 0 代表关闭。
🔢六位数字分别对应：

1.转发推文（博主转发别人推文要发吗？）
2.自我转发（博主转发自己的内容要发吗？）
3.中文翻译（需要自动翻译成中文吗？）
4.图片提示（需要提示共有几张图吗？）
5.合并发送（多条推文合成合并消息吗？）
6.卡片模式（推文渲染成图片卡片发送？）

💡懒人专用（直接复制）：
•【推荐配置】： 群组配置 1 0 1 1 1 0
•【卡片模式】： 群组配置 1 0 1 1 0 1
•【全部开启】： 群组配置 1 1 1 1 1 1

⚠️ 注意事项：
六个数字之间必须有空格。
如果你直接发送 群组配置（不带数字），系统会默认按推荐配置运行。
即：1 0 1 1 0 0
——————"""
