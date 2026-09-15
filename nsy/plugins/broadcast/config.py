from pydantic import BaseModel

# 已登记的群聊代号。新增群聊 = 在此加一个代号，并补一组对应字段：
# GROUP_<代号> 提供群 OpenID，<代号>_PUSH_ENABLED 控制是否注册定时任务。
_KNOWN_KEYS = ("CQU_EF",)


class Config(BaseModel):
    """定时推送配置。"""

    group_cqu_ef: str | None = None
    cqu_ef_push_enabled: bool = False

    @property
    def group_registry(self) -> dict[str, str]:
        """业务代号 -> group_openid；未配置 OpenID 的代号不会出现。"""
        registry = {key: getattr(self, f"group_{key.lower()}") for key in _KNOWN_KEYS}
        return {key: openid for key, openid in registry.items() if openid}

    def push_enabled(self, key: str) -> bool:
        """该代号是否开启定时推送。"""
        return bool(getattr(self, f"{key.lower()}_push_enabled", False))
