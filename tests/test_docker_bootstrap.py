"""Docker ASGI 入口必须初始化 NoneBot，而不启动第二个服务器。"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DockerBootstrapTests(unittest.TestCase):
    def test_rss_loads_orm_without_another_plugin_preloading_it(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="nsybot-rss-bootstrap-") as directory:
            env = os.environ.copy()
            env.update({"PYTHONPATH": str(root), "API_KEY": "test-key", "PYTHONDONTWRITEBYTECODE": "1"})
            result = subprocess.run(
                [sys.executable, "-c", (
                    "from pathlib import Path\n"
                    "import nonebot\n"
                    "nonebot.init(driver='~fastapi', log_level='ERROR', "
                    "sqlalchemy_database_url='sqlite+aiosqlite:///:memory:', "
                    "localstore_data_dir=Path('data'), localstore_cache_dir=Path('cache'), "
                    "localstore_config_dir=Path('config'))\n"
                    "assert nonebot.get_plugin('nonebot_plugin_orm') is None\n"
                    "plugin = nonebot.load_plugin('nsy.plugins.rssget')\n"
                    "assert plugin is not None, 'RSS 插件必须能独立加载'\n"
                    "assert nonebot.get_plugin('nonebot_plugin_orm') is not None\n"
                )],
                cwd=directory, env=env, text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_asgi_import_initializes_nonebot_and_loads_rss(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="nsybot-asgi-test-") as directory:
            (Path(directory) / "pyproject.toml").write_text((root / "pyproject.toml").read_text())
            shutil.copytree(root / "nsy", Path(directory) / "nsy", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            env = os.environ.copy()
            env.update({
                "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1",
                "DRIVER": "~fastapi+~httpx", "LOG_LEVEL": "ERROR",
                "QQ_APP_ID": "test-app", "QQ_APP_SECRET": "test-secret",
                "QQ_USE_WEBSOCKET": "false",
                "API_KEY": "test-key", "SQLALCHEMY_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
                "LOCALSTORE_DATA_DIR": directory, "LOCALSTORE_CACHE_DIR": directory,
                "LOCALSTORE_CONFIG_DIR": directory, "ALEMBIC_STARTUP_CHECK": "false",
                "RSS_IMAGE_SYNC_ENABLED": "true", "RSS_IMAGE_SYNC_TOKEN": "bootstrap-test-token",
                "APSCHEDULER_CONFIG": '{"apscheduler.timezone":"America/New_York"}',
                "RSS_PUSH_INTERVAL": "17",
            })
            result = subprocess.run(
                [sys.executable, "-c", (
                    "import nonebot\n"
                    "from docker._main import app\n"
                    "assert callable(app)\n"
                    "assert nonebot.get_plugin('rssget') is not None\n"
                    "import time\n"
                    "rss = nonebot.get_plugin('rssget').module\n"
                    "collect = [j for j in rss.scheduler.get_jobs() if j.func == rss.auto_update_func]\n"
                    "push = [j for j in rss.scheduler.get_jobs() if j.func == rss.auto_push_func]\n"
                    "assert len(collect) == len(push) == 1\n"
                    "assert abs(collect[0].next_run_time.timestamp() - time.time()) < 30, '启动采集不能受调度器时区影响'\n"
                    "assert push[0].trigger.interval.total_seconds() == 17\n"
                    "import asyncio, httpx\n"
                    "async def check_auth():\n"
                    "    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as client:\n"
                    "        response = await client.get('/internal/v1/images')\n"
                    "        assert response.status_code == 401, response.text\n"
                    "asyncio.run(check_auth())\n"
                )],
                cwd=directory, env=env, text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
