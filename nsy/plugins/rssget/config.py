from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""
    ignored_groups: list[int] = [200214779, 210146004,524239640,925265706,929711368]
    if_first_time_start: bool = True