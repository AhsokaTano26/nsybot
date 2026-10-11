# 部署说明

[返回项目首页](../README.md) · [QQ 官方 Bot 接入](qq-official-bot.md)

推荐使用 Docker Compose。部署前在 QQ 开放平台创建机器人，获取 AppID 与 AppSecret；接入方式和 OpenID 的获取见 [QQ 官方 Bot 接入](qq-official-bot.md)。

## Docker

```bash
git clone https://github.com/AhsokaTano26/nsybot.git
cd nsybot
mkdir -p data
cp .env.example .env.prod
```

编辑 `.env.prod`，将示例占位值替换为实际配置，完成后启动：

```bash
docker compose up -d
docker compose logs -f nonebot
```

容器启动时自动执行 `nb orm upgrade`，创建或升级数据表，无需手动创建空数据库文件。`./data` 挂载到容器的 `/app/data`，用于保存 SQLite 数据；更新前备份该目录。

发布镜像为 [tano26/nsybot:latest](https://hub.docker.com/r/tano26/nsybot/tags)，也可从当前代码构建：

```bash
docker compose up -d --build
```

使用发布镜像更新：

```bash
docker compose pull
docker compose up -d
```

默认使用 WebSocket 接收事件。若使用 Webhook，需要配置公网回调和端口映射，见 [QQ 接入说明](qq-official-bot.md#配置)。

## 环境配置

完整示例见 [`.env.example`](../.env.example)。常用配置如下：

| 配置 | 用途 |
| --- | --- |
| `QQ_APP_ID` / `QQ_APP_SECRET` | QQ 官方机器人的 AppID 与 AppSecret |
| `QQ_USE_WEBSOCKET` | 默认 `true`，使用官方 WebSocket 事件连接 |
| `SUPERUSERS` | 超管成员 OpenID 的 JSON 数组，如 `'["member_openid"]'` |
| `SQLALCHEMY_DATABASE_URL` | Docker 使用 `sqlite+aiosqlite:////app/data/db.sqlite3` |
| `RSSHUB_HOST` | RSSHub 实例地址；插件默认 `https://rsshub.app`，需替换示例占位值 |
| `RSSHUB_HOST_BACK` | 备用实例地址的 JSON 数组，可设为 `[]` |
| `REFRESH_TIME` | RSS 更新间隔，单位分钟，默认 `20` |
| `API_KEY` / `MODEL_NAME` | DeepSeek API Key 与翻译模型名 |
| `TARGET_GROUP_OPENID` | 可选的运维通知群 OpenID |
| `BIRTHDAY_REMINDER_ENABLED` | 生日定时提醒开关，默认 `true` |

当前默认翻译器为 DeepSeek，不使用 `SECRET_KEY`。代码中还保留百度、阿里等翻译类；切换翻译器需要修改 RSS 插件中的实例，不能只靠更换密钥完成。

未使用的可选配置应清空或删除示例占位值，例如 `TARGET_GROUP_OPENID`、`UT_URL`、`DETECT_URL`、`GROUP_CQU_EF`。群与成员身份使用官方 OpenID；本群所有成员可订阅，超管负责全局管理。

## 本地运行

建议使用 Python 3.12，与 Docker 镜像一致。在项目根目录执行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
mkdir -p data
cp .env.example .env.prod
```

填写 `.env.prod`，并将数据库地址改为相对本地路径：

```dotenv
SQLALCHEMY_DATABASE_URL=sqlite+aiosqlite:///data/db.sqlite3
```

创建 `.env`，选择运行环境：

```dotenv
ENVIRONMENT=prod
```

应用迁移后启动：

```bash
nb orm upgrade
python run.py
```

也可使用 `nb run` 启动。开发时复制 `.env.example` 为 `.env.dev`，填写本地配置与数据库地址，并将 `.env` 中的环境改为 `ENVIRONMENT=dev`。

## 首次使用

- RSS：先按 [RSS 使用指南](rss.md) 配置平台、添加可访问用户，再在目标群订阅。
- 生日：按 [生日插件说明](birthday.md#启用) 导入预设、设置原群名并订阅标签。
