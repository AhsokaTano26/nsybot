from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""
    target_groups: int = 1051726332
    detect_url: str = "None"
