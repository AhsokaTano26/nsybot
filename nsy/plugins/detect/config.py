from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""
    target_groups: int = 658521872
    # 可用性监控配置
    detect_url: str = "None"
