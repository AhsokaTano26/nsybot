# nsybot

基于 NoneBot2 的 QQ 官方机器人，将 RSS 更新推送到群聊，并提供生日提醒。

[快速开始](#快速开始) · [使用文档](#文档) · [Docker 镜像](https://hub.docker.com/r/tano26/nsybot/tags)

## 功能

- **RSS 推送**：通过 RSSHub 订阅多平台动态，定时推送到 QQ 群。
- **群内管理**：订阅选择面板、批量订阅，以及各群独立的推送设置。
- **中文翻译**：默认使用 DeepSeek，文章与翻译结果本地缓存。
- **生日提醒**：按标签订阅，每天北京时间 23:00 提醒手动修改或恢复群名称，并给出完整建议昵称；超管可引用富文本发送生日语录到其他生日订阅群。

## 快速开始

准备 Docker Compose 和 QQ 官方机器人账号：

```bash
git clone https://github.com/AhsokaTano26/nsybot.git
cd nsybot
mkdir -p data
cp .env.example .env.prod
```

按 [部署说明](docs/deployment.md) 填写 `.env.prod` 中的 QQ 凭据、RSSHub 和翻译配置，然后启动：

```bash
docker compose up -d
docker compose logs -f nonebot
```

首次使用，在群内 @ 机器人发送 `帮助`。RSS 需先配置平台与可访问用户；生日插件的启用步骤见下方文档。

## 文档

| 文档 | 内容 |
| --- | --- |
| [部署说明](docs/deployment.md) | Docker、本地运行、开发与环境配置 |
| [QQ 官方 Bot 接入](docs/qq-official-bot.md) | 凭据、WebSocket / Webhook、OpenID 与权限 |
| [RSS 使用指南](docs/rss.md) | 平台配置、订阅命令、群组设置与管理命令 |
| [生日提醒](docs/birthday.md) | 启用、订阅、昵称格式与提醒规则 |
| [生日数据导入](docs/birthday-import-commands.md) | 批量导入命令与关联标签 |
| [生日数据核查](docs/birthday-data-audit.md) | 角色与声优生日的核查结果和来源 |

## 致谢

[NoneBot2](https://github.com/nonebot/nonebot2) · [RSSHub](https://github.com/DIYgod/RSSHub) · [bot_tools](https://github.com/AhsokaTano26/bot_tools) · [QQ 开放平台](https://bot.q.qq.com/wiki/develop/api-v2/) · [百度机器翻译](https://cloud.baidu.com/doc/API/index.html) · [CQU Lanunion](https://baike.baidu.com/item/重庆大学蓝盟/18227014)
