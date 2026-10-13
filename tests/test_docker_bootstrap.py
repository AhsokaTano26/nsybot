"""Docker ASGI 入口必须初始化 NoneBot，而不启动第二个服务器。"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DockerBootstrapTests(unittest.TestCase):
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
                "QQ_APP_TOKEN": "", "QQ_USE_WEBSOCKET": "false",
                "API_KEY": "test-key", "SQLALCHEMY_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
                "LOCALSTORE_DATA_DIR": directory, "LOCALSTORE_CACHE_DIR": directory,
                "LOCALSTORE_CONFIG_DIR": directory, "ALEMBIC_STARTUP_CHECK": "false",
            })
            result = subprocess.run(
                [sys.executable, "-c", (
                    "import nonebot\n"
                    "from docker._main import app\n"
                    "assert callable(app)\n"
                    "assert nonebot.get_plugin('rssget') is not None\n"
                )],
                cwd=directory, env=env, text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
