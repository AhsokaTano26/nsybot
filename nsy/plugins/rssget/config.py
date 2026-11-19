from pydantic import BaseModel, Field, SecretStr, model_validator


class Config(BaseModel):
    """Plugin Config Here"""
    # 基础配置
    # QQ 官方 Bot 不暴露 QQ 群号；这里及数据库中均使用 group_openid。
    ignored_group_openids: list[str] = []
    broadcast_ban_openids: list[str] = []
    # 启动首轮按群检查上次成功推送时间；首轮完成或执行 /信号否 后置为 False。
    if_first_time_start: bool = True
    target_group_openid: str | None = None

    # RSSHub 配置
    rsshub_host: str = "https://rsshub.app"
    rsshub_host_back: list[str] | None = None

    # 翻译/AI 配置
    api_key: str | None = None
    secret_key: str | None = None
    model_name: str | None = None

    # Twitter 采集的 Uptime Kuma Push URL；通知渠道在 Kuma 中配置。
    ut_url: str | None = None

    # 更新时间配置
    refresh_time: int = Field(default=20, gt=0)
    # 采集与 QQ 推送独立调度；推送只读最近一次有效 RSS 快照。
    rss_push_interval: int = Field(default=60, gt=0)
    rss_ingest_retry_interval: int = Field(default=60, gt=0, le=3600)
    rss_ingest_retry_batch: int = Field(default=100, gt=0, le=1000)
    rss_fetch_retry_base: float = Field(default=2, gt=0, le=30)
    # 全部 RSSHub 失败时跨账号退避，防止连续请求扩大上游限流。
    rss_twitter_cooldown: int = Field(default=900, gt=0, le=86400)
    rss_twitter_failure_threshold: int = Field(default=3, gt=0, le=20)

    # 复用 NoneBot HTTP 服务；默认关闭，启用必须配置独立 Token。
    rss_image_sync_enabled: bool = False
    rss_image_sync_token: SecretStr | None = None

    @model_validator(mode="after")
    def validate_image_sync_token(self):
        token = self.rss_image_sync_token
        if self.rss_image_sync_enabled and (token is None or not token.get_secret_value().strip()):
            raise ValueError("启用图片同步 API 必须配置 RSS_IMAGE_SYNC_TOKEN")
        return self

    # 帮助信息
    help_msg_1: str = """# 🤖 nsy 推文助手 · 本群快捷操作

本群所有成员均可使用下方功能；群 OpenID 会自动从当前会话读取。

> 点击“订阅面板”或“退订面板”可按编号批量选择；也可直接发送 `订阅 <用户ID>`。
> `rss` 与 `文章列表` 需要用户 ID，按钮会预填命令供你补充。
> 发送 `群组配置` 查看全部设置；使用 `群组配置 翻译 开` 等命令单独修改。
> 默认每个账号每轮只推送最近 1 篇；`群组配置 推送数量 0` 表示全部未发送，1–5 表示最近篇数。"""
