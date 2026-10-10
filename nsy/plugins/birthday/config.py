from pydantic import BaseModel


class Config(BaseModel):
    """群主动订阅后才发送；此开关用于全局停用定时提醒。"""

    birthday_reminder_enabled: bool = True
