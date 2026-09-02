from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""
    # QQ 官方群 OpenID；为空时仅记录连接状态，不发送群通知。
    target_group_openid: str | None = None
    # 可用性监控配置
    detect_url: str = "None"
