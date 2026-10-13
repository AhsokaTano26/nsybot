"""为 RSS 集成测试加载真实插件，不连接外部服务。"""

from pathlib import Path

import nonebot


def load_rss_plugin(test_root: str):
    try:
        driver = nonebot.get_driver()
    except ValueError:
        nonebot.init(
            driver="~fastapi",
            sqlalchemy_database_url="sqlite+aiosqlite:///:memory:",
            localstore_data_dir=Path(test_root) / "data",
            localstore_cache_dir=Path(test_root) / "cache",
            localstore_config_dir=Path(test_root) / "config",
            log_level="ERROR",
        )
        driver = nonebot.get_driver()
    driver.config.api_key = "test-rss-key"
    driver.config.superusers = {"admin-member"}
    driver.config.command_start = {""}
    nonebot.require("nonebot_plugin_orm")
    plugin = nonebot.get_plugin("rssget") or nonebot.load_plugin("nsy.plugins.rssget")
    if plugin is None:
        raise AssertionError("RSS 插件应能加载")
    return plugin.module
