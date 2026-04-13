from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""
    target_groups: int = 658521872
    detect_url: str = "None"
