from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""
    igignored_groups: list[int] = [200214779, 210146004,524239640,925265706]