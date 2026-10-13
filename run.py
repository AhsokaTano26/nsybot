"""Run nsybot locally with flat QQ official Bot environment variables."""

from __future__ import annotations

import os

import nonebot
from dotenv import load_dotenv
from nonebot.adapters.qq import Adapter as QQAdapter

from nsy.qq_bootstrap import materialize_qq_bots


def prepare_environment() -> None:
    """Load local env files and materialize QQ_BOTS before NoneBot starts."""
    load_dotenv(".env")
    environment = os.getenv("ENVIRONMENT", "prod")
    load_dotenv(f".env.{environment}", override=False)
    materialize_qq_bots()


def initialize_bot() -> None:
    """初始化配置、适配器和插件；供本地与 Docker ASGI 入口共用。"""
    prepare_environment()
    nonebot.init()
    nonebot.get_driver().register_adapter(QQAdapter)
    nonebot.load_from_toml("pyproject.toml")


def main() -> None:
    initialize_bot()
    nonebot.run()


if __name__ == "__main__":
    main()
