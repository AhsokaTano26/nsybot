from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""
    # 基础配置
    # QQ 官方 Bot 不暴露 QQ 群号；这里及数据库中均使用 group_openid。
    ignored_group_openids: list[str] = []
    broadcast_ban_openids: list[str] = []
    if_first_time_start: bool = True
    target_group_openid: str | None = None

    # RSSHub 配置
    rsshub_host: str = "https://rsshub.app"
    rsshub_host_back: list[str] | None = None

    # 翻译/AI 配置
    api_key: str | None = None
    secret_key: str | None = None
    model_name: str | None = None

    # 可用性监控配置
    ut_url: str | None = None

    # 更新时间配置
    refresh_time: int = 20

    # 帮助信息
    help_msg_1: str = """# 🤖 nsy 推文助手 · 本群快捷操作

本群所有成员均可使用下方功能；群 OpenID 会自动从当前会话读取。

> 点击“订阅面板”或“退订面板”可按编号批量选择；也可直接发送 `订阅 <用户ID>`。
> `rss` 与 `文章列表` 需要用户 ID，按钮会预填命令供你补充。
> 群组配置的参数顺序为：转发、自我转发、翻译、图片提示；`1` 为开、`0` 为关。
> 推荐配置：`群组配置 1 0 1 1`。"""
