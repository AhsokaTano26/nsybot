from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""
    if_connected: bool = False
    ignored_groups: list = [200214779, 210146004, 524239640, 925265706, 824993838, 922940475, 929711368]  # 替换为实际群号
    target_groups: int = 1051726332