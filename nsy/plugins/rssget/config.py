from pydantic import BaseModel
from nonebot import get_driver  # 导入 get_driver 函数，用于获取 NoneBot 驱动器


class Config(BaseModel):
    """Plugin Config Here"""
    ignored_groups: list[int] = [200214779, 210146004,524239640,925265706,929711368]
    if_first_time_start: bool = True

# 从 NoneBot 驱动器的配置字典中解析配置对象
Config = Config.parse_obj(get_driver().config.dict())