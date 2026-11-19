# 内部图片同步 API

[返回项目首页](../README.md) · [部署说明](deployment.md) · [RSS 使用指南](rss.md)

供同一 VPS 上独立部署的 aiaibot 拉取图片元数据。复用 NoneBot/FastAPI 的 HTTP 服务和 SQLite 数据库，不另起服务器、不下载或代理图片，也不修改 QQ 推送状态。

## 数据来源与边界

- 按账户列表 `User` 抓取全部账号，每个账号每轮采集一次，没有群订阅也更新。采集与 QQ 推送独立运行；启动立即采集，之后每 `REFRESH_TIME` 分钟一轮（默认 20），QQ 离线和夜间也继续。
- 每次响应的全部有效条目补存到 `Content`，不受群的启动静默、推送篇数、转发开关影响。翻译仅在实际推送需要时补充。
- `Detail` 保持各群的发送和跳过记录；图片 API 只读，不把被拉取的文章标为已向 QQ 发送。
- QQ 推送每 `RSS_PUSH_INTERVAL` 秒检查一次（默认 60），只读取最新有效 RSS 快照，仍按群订阅和篇数设置发送。慢推送、图片重试和 QQ 限速不会占用采集锁。
- `rss_image_sync` 是同一数据库中的轻量索引：每篇含图片的文章首次缓存时分配递增序号，与 `Content` 原子提交。反复抓取或补充译文不会重新分配序号；纯文字文章也缓存，但不出现在图片 API 中。
- 入库失败的原始条目保存在 `rss_ingest_queue`，独立退避补写；补写成功才原子创建图片索引并清除任务，aiaibot 后续按原游标即可拉到，不需要重置游标或等待 RSS 再返回原文章。
- 升级迁移自动为已有的有效图片缓存建立索引，保留原始 `Content` 和 `Detail`。历史索引按缓存 ID 排序建立；后续按入库顺序递增，都不代表发布时间顺序。

“全量补拉”指数据库已有缓存，以及后续订阅 RSS 响应中的全部条目。过去被静默跳过、未缓存且已不在 RSS 中的条目无法恢复。本接口不调用 X 历史抓取，也不保证原始图片 URL 永久可下载。

该接口提供每篇文章首次登记后的读取，不是文章编辑/删除的变更流；同一 ID 后续图片列表被修改时，不重新投递该文章。数据库应持久保存；不要删除同步索引、回滚该迁移或用旧备份替换数据库后继续沿用原游标。恢复旧备份或重建索引后，aiaibot 应从 `0` 幂等重放。

## 启用配置

在 nsybot 的 `.env.prod` 填写：

```dotenv
DRIVER=~fastapi+~websockets+~httpx
PORT=12035
RSS_IMAGE_SYNC_ENABLED=true
RSS_IMAGE_SYNC_TOKEN=替换为独立随机Token
```

Token 可用 `python -c 'import secrets; print(secrets.token_urlsafe(32))'` 生成，并安全地写入两个项目各自的环境配置。该 Token 与 QQ、RSSHub 和翻译密钥无关。默认关闭，关闭时返回 `404`；启用但 Token 为空或只有空白时配置校验失败，不会以无鉴权方式运行。Token 通过 `Authorization` 请求头发送，不放进 URL 查询参数。

容器启动会执行 `nb orm upgrade` 完成历史回填；本地部署先手动运行该命令。同步 API 不在 OpenAPI 文档中列出。缓存损坏的历史图片列表会在迁移日志中明确记录；原始 Content 保留，后续该条目再次出现在 RSS 响应中时会从原响应重建缓存和索引。

## 两个项目通过 Docker 内网连接

一次性在 VPS 建立专用网络：

```bash
docker network create --internal bot-sync
```

在 nsybot 项目目录启动，后续更新也使用同一组 Compose 文件：

```bash
docker compose -f docker-compose.yml -f docker-compose.image-sync.yml up -d --build
```

可改为先 `pull` 再 `up -d` 使用发布镜像。扩展配置让 nsybot 同时加入自己的默认网络与共享网络，容器内监听 `0.0.0.0`，共享网络中的固定别名为 `nsybot-sync`。基础 Compose 使用 `expose`，没有 `ports`，不会发布宿主机或公网端口。各自的默认网络继续供 RSSHub、QQ 和图片下载出站使用。

在 aiaibot **自己的** Compose 中，将现有服务接入同一网络（保留其镜像、数据卷及其他配置）：

```yaml
services:
  aiaibot:
    environment:
      # 接入时在 aiaibot 中读取这些配置；nsybot 不负责修改 aiaibot 代码。
      NSYBOT_IMAGE_SYNC_URL: http://nsybot-sync:12035/internal/v1/images
      NSYBOT_IMAGE_SYNC_TOKEN: ${NSYBOT_IMAGE_SYNC_TOKEN:?请配置相同Token}
    networks:
      - default
      - image-sync

networks:
  image-sync:
    external: true
    name: bot-sync
```

两个项目仍各自构建、更新、重启，不共享 SQLite 文件或宿主机目录。跨项目网络的配置方式见 [Docker 官方文档](https://docs.docker.com/compose/how-tos/networking/#use-an-existing-external-network)。网络名如需自定义，在 nsybot 的 shell 或根目录 `.env` 设置 `NSYBOT_SYNC_NETWORK`，并同步调整 aiaibot 中的 `name`；`.env.prod` 的 `env_file` 不参与 Compose 文件插值。自定义 `PORT` 时也要同步修改 aiaibot URL。

若部署已有公网 Webhook 反向代理，应拒绝转发 `/internal/`。默认 WebSocket 部署无需任何公网入口。建议保持单 worker（镜像默认 `MAX_WORKERS=1`），避免多个进程重复运行 RSS 定时任务。

## 请求和响应

```http
GET /internal/v1/images?cursor=0&limit=100
Authorization: Bearer <Token>
```

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| `cursor` | `0` | 上一页的 `next_cursor`，十进制字符串；只读严格大于该序号的数据 |
| `limit` | `100` | 每页文章数，范围 `1–200`；每篇返回全部图片 URL |

```json
{
  "items": [
    {
      "seq": "42",
      "id": "nsybot现有RSS条目ID",
      "tweet_id": "1234567890",
      "author": "作者显示名称",
      "author_handle": "example",
      "published_at": "2026-11-12T12:34:00+08:00",
      "published_at_raw": "2026-11-12 12:34",
      "link": "https://x.com/example/status/1234567890",
      "images": ["https://pbs.twimg.com/media/example.jpg?format=jpg&name=orig"]
    }
  ],
  "next_cursor": "42",
  "has_more": false
}
```

`id` 沿用 RSS 的去重 ID（通常是 GUID/链接的 MD5），适合本地唯一键；`tweet_id` 和 `author_handle` 从 X/Twitter 原文链接提取，无法识别的平台或历史链接返回 `null`。`author` 是现有缓存中的订阅作者显示名称，转发或引用时不一定是被引用的原作者。`link` 保留原文链接。

`images` 保留 RSS 采集时的原始 URL 和顺序，只删除完全相同的重复项，不改写参数、不返回 QQ 临时地址。`published_at` 根据现有缓存的北京时间转为带时区的 ISO 8601，缓存通常只有分钟精度；未知或无法解析时返回 `null`，同时保留 `published_at_raw`，不会因时间不明而排除条目。旧缓存缺少作者或链接时对应字段也可为 `null`。

`seq` 和 `next_cursor` 使用字符串，避免 JavaScript 大整数丢失精度；序号可有间隙，客户端应原样保存，不自行加一。接口严格按序号升序分页，因此较晚入库的旧推文也能通过当前游标读到。

| 状态码 | 含义 |
| --- | --- |
| `200` | 请求成功，可能是空页；响应带 `Cache-Control: no-store` |
| `401` | 缺少、无效或错误的 Bearer Token，附带 `WWW-Authenticate: Bearer` |
| `404` | API 未启用 |
| `422` | 游标不合法、超过 SQLite 整数范围或分页大小超限 |
| `5xx` | 数据库或缓存读取失败；客户端不得推进游标，应记录错误并重试 |

## 增量同步与历史补拉

1. 首次同步用 `cursor=0`，或不传游标，从头读取所有历史图片文章。
2. aiaibot 先把整页元数据和图片下载任务持久化；文章按 `id`、图片任务按 `(id, URL)` 做唯一键或 upsert。
3. 只有整页持久化成功后，才保存返回的 `next_cursor`；最好与本地写入放在同一事务。下载任务可稍后执行，单张下载失败不会丢失待重试任务。
4. `has_more=true` 时继续请求下一页；为 `false` 时等待下一轮，继续使用同一游标轮询。
5. 空页返回 `items=[]`、`has_more=false`，`next_cursor` 保持请求值。网络中断或任何非 200 响应时保留旧游标重试。
6. 需要重新补拉时，另建一个从 `0` 开始的游标，依赖本地唯一键幂等重放；不修改 nsybot 或 QQ 的去重记录。

HTTP 重试可能重读同一页，服务端无法知道 aiaibot 是否已提交数据；服务端稳定序号加上客户端幂等入库、提交后推进游标，才能在断线和重启后实现不漏项、无重复落库。接口不会维护共享的“已消费”状态，因此多个消费者可以独立保存游标。

可从 aiaibot 容器内用已配置的环境变量验证连通性：

```bash
python -c 'import os, urllib.request; r=urllib.request.Request(os.environ["NSYBOT_IMAGE_SYNC_URL"]+"?cursor=0&limit=1", headers={"Authorization": "Bearer "+os.environ["NSYBOT_IMAGE_SYNC_TOKEN"]}); print(urllib.request.urlopen(r).read().decode())'
```

排查时先查看 `docker network inspect bot-sync`，确认两个容器都接入该网络，再检查 nsybot 日志中的迁移与缓存错误。该 URL 仅供共享 Docker 网络使用，宿主机与公网不能通过此别名直接访问。
