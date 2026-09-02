"""Build the QQ adapter's structured configuration from flat environment variables."""

from __future__ import annotations

import json
import os


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_qq_bots() -> str:
    """Return a ``QQ_BOTS`` JSON value from the project's flat QQ_* variables."""
    app_id = os.getenv("QQ_APP_ID")
    app_secret = os.getenv("QQ_APP_SECRET")
    if not app_id or not app_secret:
        raise RuntimeError(
            "QQ_APP_ID and QQ_APP_SECRET are required when QQ_BOTS is not set"
        )

    bot = {
        "id": app_id,
        # 1.7.x keeps this legacy required field in its Pydantic model, although
        # Access Token authentication uses AppID and AppSecret.
        "token": os.getenv("QQ_APP_TOKEN", ""),
        "secret": app_secret,
        "intent": {
            "c2c_group_at_messages": _as_bool(
                os.getenv("QQ_C2C_GROUP_AT_MESSAGES"), True
            ),
            "group_members": _as_bool(os.getenv("QQ_GROUP_MEMBERS"), True),
            "guild_messages": _as_bool(os.getenv("QQ_GUILD_MESSAGES"), False),
        },
        "use_websocket": _as_bool(os.getenv("QQ_USE_WEBSOCKET"), False),
    }
    return json.dumps([bot], ensure_ascii=False, separators=(",", ":"))


def materialize_qq_bots() -> None:
    """Prefer complete flat credentials, otherwise preserve advanced QQ_BOTS."""
    if os.getenv("QQ_APP_ID") and os.getenv("QQ_APP_SECRET"):
        os.environ["QQ_BOTS"] = build_qq_bots()
        return
    if os.getenv("QQ_BOTS"):
        return
    os.environ["QQ_BOTS"] = build_qq_bots()
