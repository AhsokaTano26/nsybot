# QQ 官方 Bot 部署说明

本项目已使用 `nonebot-adapter-qq` 接入 QQ 官方 Bot，不再需要 NapCat、QQ
客户端登录或 OneBot WebSocket 服务。部署配置使用扁平环境变量，启动时自动
生成适配器内部需要的 `QQ_BOTS` JSON。

## 配置

以 `.env.example` 创建 `.env.prod`，并在 QQ 开放平台创建机器人后填写：

```dotenv
DRIVER=~fastapi+~websockets+~httpx
QQ_IS_SANDBOX=false
QQ_APP_ID=<AppID>
QQ_APP_SECRET=<AppSecret>
QQ_APP_TOKEN=
QQ_USE_WEBSOCKET=true
SUPERUSERS='["<member_openid>"]'
TARGET_GROUP_OPENID=<group_openid>
```

`QQ_C2C_GROUP_AT_MESSAGES=true`（默认）用于群内 @ 机器人的指令和私聊指令。
`QQ_APP_TOKEN` 是适配器 1.7.x 的兼容必填字段，通常可留空。若需多机器人或
特殊 Intent，可直接填写 `QQ_BOTS`。当同时设置完整的 `QQ_APP_ID` 与
`QQ_APP_SECRET` 时，扁平字段优先；仅设置 `QQ_BOTS` 时则保留其高级多机器人配置。

默认使用 QQ 官方 Bot 的 WebSocket 事件连接。若改用 Webhook，设置
`QQ_USE_WEBSOCKET=false`，并把驱动改为 `~fastapi+~httpx`，再在 QQ 开放平台配置
`https://<公网域名>/qq/webhook` 回调地址。

## OpenID 与权限

官方群接口的 `group_openid` 和 `member_openid` 都是字符串，不能填 QQ 群号或
QQ 号。第一次在目标群 @ 机器人后，从事件日志取得两个值，并分别写入：

- `SUPERUSERS`：允许跨群查询、用户管理、群发和运维等全局命令的成员；
- `IGNORED_GROUP_OPENIDS` / `BROADCAST_BAN_OPENIDS`：群过滤名单；
- `TARGET_GROUP_OPENID`：可选的运维通知群。

`ADMIN_OPENIDS` 已废弃且不会被读取。本群订阅、取消订阅、群组配置，以及私聊
“导入关注”均向所有用户开放；后者仍需要由用户自行提供目标 `group_openid` 与 X
登录凭据。

数据库迁移会将 `Group_config.group_id` 转为字符串。原来保存的 QQ 群号不能
自动映射为官方群 OpenID，需在官方群里重新执行一次“群组配置”和“订阅”。

## 行为变化

- 原 OneBot 合并转发已经改为 QQ Markdown；RSS 正文与翻译合为一条 Markdown，
  图片通过官方群富媒体接口逐张发送。
- 每 20 分钟的 RSS 定时任务和 `/send` 广播保留，均调用官方群主动消息接口。
- 独立 `bot_group` 表记录机器人已知所在群、真实入群时间、首次登记及最近在群
  证据。入群事件登记，普通群消息自动补录/确认，`GROUP_DEL_ROBOT` 事件会将
  群登记与 RSS 订阅、群配置一起删除。超级管理员可发送 `群列表 [页码]` 查看。
- 升级迁移从 RSS 订阅、群配置及存在时的生日群记录一次性补录历史群，标为
  待确认；历史真实入群时间留空。当前接入未进行完整群列表同步，因此没有记录
  的旧群需等待下一次群消息补登记；“清理失效订阅”报告差异而不猜测退群。
- “导入关注”私聊参数中的目标群改为 `group_openid`。

## 本地启动

Docker 会在 `prestart.sh` 中自动转换配置。本地可使用 `python run.py` 或 `nb run`：
两者都会在 NoneBot 加载 QQ 适配器前完成扁平变量转换。
