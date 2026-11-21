# 性能与资源预算

生产继续使用 Python 3.12，采集间隔为 20 分钟。`docker-compose.yml` 限制整个容器为十进制 300 MB（不是 300 MiB），`memswap_limit` 与 `mem_limit` 相同；Linux 按页向下取整可能显示 299,999,232 字节。内存约束涵盖 Gunicorn 主进程、唯一 worker、线程及容器计入的文件缓存。镜像构建过程不属于运行容器预算。

## 业务状态

`nsy/plugins/rssget/state_machines.py` 用标准库枚举、不可变数据和纯函数表示业务决策，不依赖 NoneBot、HTTP 或数据库，不引入状态机框架或常驻子进程。QQ 命令和调度器调用相同的业务入口。

| 决策 | 状态和动作 |
| --- | --- |
| 采集轮次 | 未探测、有效、连续故障、暂停；区分账号失效、全源故障和限流，计算暂停与恢复动作 |
| 链路健康 | 输入前后可用性及检测时间，输出退避截止时间和 Kuma 心跳入队决定 |
| 文章写入 | 已提交、旧版本已被替代、仍需补偿；文章、图片索引、对应版本的队列确认保持原子提交 |
| 入库重试 | 输入失败次数和时间，输出下一次重试时间；30 秒起，最多 1 小时 |
| 群投递 | 已处理、启动静默、窗口外、被群设置过滤、允许发送；继续使用原有 Detail 记录 |

数据库和网络操作仍在现有业务模块执行。采集、补偿、QQ 投递分别使用原有独立锁；Twitter 上下线仍交给 Uptime Kuma，不从 QQ 发通知。没有新增账号级抓取重试队列。

## 内存与执行边界

- 单条正文只建一个 BeautifulSoup 树，提取全部图片后移除引用正文；翻译前主动释放树。推送仅为实际待发送的条目检查引用标记，历史已处理条目不重复解析。
- twikit、OpenAI 和阿里 SDK 在首次使用时导入，首次使用后仍占内存。图片 API 只读取需要的六列元数据，序列化前释放数据库会话。
- 翻译请求每个 worker 同时只运行一个，等待时不保留 HTML 树；60 秒翻译超时从取得时隙后开始计算，取消会释放时隙。
- RSS 最多并发读取两个响应；默认解压后 4 MiB，包含 gzip/deflate 解压限制。重定向最多五次，中间正文直接关闭。HTTP 错误诊断最多读取 16 KiB，诊断失败仍尊重状态码与 Retry-After。
- RSS 在 feedparser 前扫描结构：最多 500 条、20,000 个 XML 元素、64 层嵌套，不接受 DTD 或不规范 XML。响应不截断为成功数据，也不覆盖旧快照；超限时切备用源，格式错误保留原有三次重试后切备用。账号资源超限本身不会触发 Twitter 全局下线。
- 单条原始 JSON 默认 256 KiB。已排队的超限条目保留；尚未接受的超限 RSS 无法仅靠入库补偿恢复，仍受上游窗口限制。
- 补偿默认每批最多 100 条、4 MiB，并在条目之间检查 1 秒预算。单条执行不被强制打断，因此这不是严格的 1 秒超时。先读取 ID、版本和字节数，再加载预算内的正文；旧版本不能清除新数据。生产 SQLite 使用 `octet_length` 从记录元数据读取字节数，需要 **SQLite 3.43+**；当前 Docker 镜像验证为 3.46.1。
- 所有现有图片发送入口共用一个下载至上传完成的时隙，单张最多 10 MiB；图片仍使用原 URL，不缩图。下载要求 HTTP identity 编码，意外压缩明确失败。生日语录仍先准备附件再广播，全部图片总量最多 10 MiB，超限时在任何发送前报错。
- 手动 RSS 查询与文章列表共用一个完整请求时隙，避免大量命令同时保留大响应。选择面板缓存最多 512 项，并清理过期项；发送限速字典清理到期时隙。

调高字节上限、增加并发或加载额外插件后，应重新验证整个容器。300 MB 上限约束由 cgroup 强制执行，应用边界用于避免撞上 OOM；有限的压测不能证明任意账号数量、旧数据库异常大字段或任意外部服务响应都能正常处理。

## 本次验证结果

2026-11-21 在 Linux aarch64、Python 3.12.16、SQLite 3.46.1 的生产镜像中完成验证。本地 Python 3.13 和生产 Python 3.12 镜像各通过 **270 项测试**。完整 [容器报告](benchmarks/2026-11-21-container-memory.json) 保存了镜像 ID、各用例指标和 cgroup 事件。

| 指标 | 结果 |
| --- | --- |
| 整个容器峰值 | 299,999,232 字节，达到按页取整后的 300 MB 上限 |
| OOM / OOM kill | 0 / 0 |
| 全部用例完成 | 是，包含预热后的大图及 API 并发 |
| 数据验证 | 900 条文章、800 条图片同步索引；100 条失败任务恢复，超限条目仍留队列 |
| 采集配置 | 1,200 秒，单 worker |

测试中曾有约 113 MB 文件缓存，触及限制后 cgroup 成功回收缓存，`memory.events.max=515`，没有 OOM；这表示发生了内存压力，并不表示留有大量余量。报告是本地 Linux 容器的合成负载结果，尚未代替实际 VPS 的长期观测。

## 可复现容器验证

`tests/container_memory_probe.py` 在真实生产启动脚本、数据库迁移、Gunicorn 主进程和 worker 中运行。使用临时 SQLite、HTTPX 模拟服务和模拟 QQ 上传的 base64 编码，不读取生产 `.env.prod` 或 `data/`，不连接外网。只在显式设置测试 APP_MODULE 时启用；正常启动不加载它。

```bash
docker build -t nsybot-memory-300m:local .
docker run -d --name nsybot-memory-check --network none \
  --memory 300000000 --memory-swap 300000000 \
  -e APP_MODULE=tests.container_memory_probe:app \
  -e ENVIRONMENT=prod -e DRIVER=~fastapi+~httpx -e LOG_LEVEL=ERROR \
  -e API_KEY=memory-test-key -e SECRET_KEY=memory-test-secret -e MODEL_NAME=fixture \
  -e SQLALCHEMY_DATABASE_URL=sqlite+aiosqlite:////tmp/budget.sqlite3 \
  -e ALEMBIC_STARTUP_CHECK=false \
  -e LOCALSTORE_DATA_DIR=/tmp/data -e LOCALSTORE_CACHE_DIR=/tmp/cache \
  -e LOCALSTORE_CONFIG_DIR=/tmp/config -e QQ_BOTS='[]' \
  -e RSS_IMAGE_SYNC_ENABLED=true -e RSS_IMAGE_SYNC_TOKEN=memory-test-token \
  -e BIRTHDAY_REMINDER_ENABLED=false -e REFRESH_TIME=20 \
  nsybot-memory-300m:local
docker logs -f nsybot-memory-check
```

等待 `MEMORY_REPORT`，要求 `ok=true`，`memory.events` 的 `oom` 与 `oom_kill` 都为 0，且 `peak_bytes` 不超过 `limit_bytes`。脚本读取 cgroup v2 的 `memory.peak`，涵盖启动迁移峰值；不以单个进程 RSS 或 Docker stats 的工作集代替容器峰值。结果同时记录匿名内存与文件缓存。验证结束后删除这个测试容器即可。

用例覆盖 20 个账号、每轮 400 篇、两个群的首次采集和新数据投递、重复轮次、SDK 首次加载、并发 200 条图片 API 查询与 10 MiB 图片上传、密集 HTML、100 条入库失败补偿及超限原始条目保留。为缩短验证，测试主动触发轮次并跳过真实发送间隔；会核对生产任务仍配置为 1,200 秒，QQ 限速另有回归测试。真实 RSSHub、QQ 网络和 VPS 上的长期表现需部署后继续观察。
