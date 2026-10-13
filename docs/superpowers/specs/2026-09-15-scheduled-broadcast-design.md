# 定时推送插件（broadcast）设计

日期：2026-09-15

## 目标

新增一个独立 NoneBot 插件，向「群注册表」中登记的群聊定时发送活动消息。首个
使用场景是代号 `CQU_EF` 的群：每日 12:00 和 18:00 推送一条法批定制活动消息
（一条 QQ Markdown + 两张图片）。

## 需求确认

| 项 | 决定 |
| --- | --- |
| 群标识 | 代码用业务代号（`CQU_EF`），环境变量提供实际的 `group_openid` |
| 推送时长 | 环境变量开关控制，默认关；活动结束改环境变量重启即停 |
| 渲染 | 正文用 Markdown 引用块（`>`），链接用 Markdown 链接 `[文字](url)` |
| 标题 | 加一行 `#` 标题 |
| 图片 | 文本消息后再逐张发独立图片消息（下载后经官方富媒体接口上传） |
| 手动触发 | 提供超管限定命令，且不受开关限制，便于上线前试发 |
| 测试 | 不加 pytest；`render()` 是纯函数，用一次性脚本比对输出 |

## 架构

新增插件 `nsy/plugins/broadcast/`，与 `rssget`、`detect` 平级。它依赖一组通用
QQ 工具函数（Markdown 截断、引用块、远程图片下载上传、主动发群消息），这些函数
目前位于 `nsy/plugins/rssget/qq.py`。

把该模块上移为 `nsy/qq_utils.py`（与既有的 `nsy/qq_bootstrap.py` 同级，符合本仓库
顶层共享模块的惯例）。原因：这些函数与 RSS 无关；且独立插件若直接
`import nsy.plugins.rssget.qq`，会连带执行 `rssget/__init__.py`，把全部 RSS 命令和
定时任务在 broadcast 的导入期就注册掉，插件加载顺序变成隐式耦合。

### 文件改动

| 文件 | 改动 |
| --- | --- |
| `nsy/qq_utils.py` | `git mv` 自 `nsy/plugins/rssget/qq.py`，内容零改动 |
| `nsy/plugins/rssget/__init__.py` | import 行改为 `from nsy.qq_utils import ...` |
| `nsy/plugins/rssget/functions.py` | 同上 |
| `nsy/plugins/rssget/send_msg.py` | 同上（该文件已废弃，仅保证可导入） |
| `nsy/plugins/broadcast/config.py` | 新增 |
| `nsy/plugins/broadcast/messages.py` | 新增 |
| `nsy/plugins/broadcast/__init__.py` | 新增 |
| `.env.example` | 新增 2 个环境变量 |
| `CLAUDE.md` | 插件清单补充 broadcast（**仅本地编辑，不提交**：该文件被 `.gitignore:165` 忽略且从未被跟踪） |

## 配置

`nsy/plugins/broadcast/config.py`：

```python
from pydantic import BaseModel

# 已登记的群聊代号。新增群聊 = 在此加一个代号，并补一组对应字段：
# GROUP_<代号> 提供群 OpenID，<代号>_PUSH_ENABLED 控制是否注册定时任务。
_KNOWN_KEYS = ("CQU_EF",)


class Config(BaseModel):
    """定时推送配置。"""

    group_cqu_ef: str | None = None
    cqu_ef_push_enabled: bool = False

    @property
    def group_registry(self) -> dict[str, str]:
        """业务代号 -> group_openid；未配置 OpenID 的代号不会出现。"""
        registry = {key: getattr(self, f"group_{key.lower()}") for key in _KNOWN_KEYS}
        return {key: openid for key, openid in registry.items() if openid}

    def push_enabled(self, key: str) -> bool:
        """该代号是否开启定时推送。"""
        return bool(getattr(self, f"{key.lower()}_push_enabled", False))
```

NoneBot 2.5 的 `get_plugin_config` 会把环境变量按字段名大小写不敏感地喂给插件
Config，因此 `GROUP_CQU_EF` 映射到 `group_cqu_ef`，与既有的 `UT_URL`、
`DETECT_URL` 同一机制。

`.env.example` 新增：

```dotenv
# 定时推送（broadcast 插件）
# 群注册表：GROUP_<代号> 填写该群的 group_openid，留空则该代号不可用。
GROUP_CQU_EF=your-cqu-ef-group-openid
# 是否注册每日 12:00 / 18:00 的定时推送，默认关闭。手动触发命令不受此开关限制。
CQU_EF_PUSH_ENABLED=false
```

## 消息定义

`nsy/plugins/broadcast/messages.py`：

```python
from dataclasses import dataclass

from nsy.qq_utils import quote_block


@dataclass(frozen=True)
class BroadcastMessage:
    """一条可复用的定时推送内容。"""

    key: str                      # 业务代号，与群注册表一致
    title: str                    # Markdown 标题
    hours: tuple[int, ...]        # 每日推送的整点时刻
    body: str                     # Markdown 正文，逐行渲染为引用行
    images: tuple[str, ...] = ()  # 图片地址，逐张作为独立图片消息发送

    def render(self) -> str:
        """渲染为 QQ Markdown：标题 + 引用块正文。"""
        return f"# {self.title}\n\n{quote_block(self.body)}"


CQU_EF = BroadcastMessage(
    key="CQU_EF",
    title="🧥 EF邦多利马群法批定制 · 第二弹",
    hours=(12, 18),
    body=(
        "各位老师，EF邦多利马群法批好评如潮第二弹开始了。"
        "如有需求，请填写表格，定制信息空白，默认原版，同时请填写尺码。\n"
        "【腾讯文档】[法批定制]"
        "(https://docs.qq.com/sheet/DVVJTZnNZdmFIcHh5?tab=BB08J2)"
    ),
    images=(
        "https://img.tano.asia/i/47b932ae-cc92-4ca8-8f9b-a462846b6f27.png",
        "https://img.tano.asia/i/d03d97db-ebf6-43b4-be80-77afff7057e0.png",
    ),
)

MESSAGES: dict[str, BroadcastMessage] = {CQU_EF.key: CQU_EF}
```

`MESSAGES` 以业务代号为键，让定时任务和手动命令都能按代号通用地取内容，与
`group_registry` 的键一一对应。

### 渲染结果

`CQU_EF.render()` 的输出：

```
# 🧥 EF邦多利马群法批定制 · 第二弹

> 各位老师，EF邦多利马群法批好评如潮第二弹开始了。如有需求，请填写表格，定制信息空白，默认原版，同时请填写尺码。
> 【腾讯文档】[法批定制](https://docs.qq.com/sheet/DVVJTZnNZdmFIcHh5?tab=BB08J2)
```

`quote_block()` 处理空行时会输出单独的 `>`。整条消息经 `markdown()` 发送，
因此自动受 3500 字截断保护约束。

## 发送流程

`nsy/plugins/broadcast/__init__.py` 中的 `send_broadcast(key) -> bool`，定时任务与
手动命令共用：

1. 从 `MESSAGES` 取内容，从 `config.group_registry` 取 `group_openid`；任一缺失则
   记 error 日志并返回 `False`。
2. `get_bot()` 获取 bot 实例，抛 `ValueError` 时记 error 并返回 `False`。
3. 发送 Markdown 消息。失败则记 error 并中止——没有配文时发图无意义——返回 `False`。
4. 逐张 `download_image(url)` → `file_image(data, file_name)` → `send_group_message`。
   单张失败只记 error 日志并继续下一张。
5. 图片全部成功后返回 `True`，记 info 日志「推送 <代号> 已完成，目标群 …」；有图片
   失败时同样返回 `True`（文本已在群里），但汇总日志降为 warning 并带上失败张数，
   避免「已完成」掩盖部分失败。

返回值语义：只有第 3 步的 Markdown 文本真正发出才返回 `True`，此后图片仍可能失败；
第 1～3 步任一提前退出都返回 `False`。手动命令按这个布尔值选择回复哪种卡片。

正常情况共发送 3 条消息：1 条 Markdown + 2 张图片。

## 定时任务

```python
def _register_jobs() -> None:
    """登记定时任务；未配置群 OpenID 或未开启推送的代号会被跳过。"""
    for key, message in MESSAGES.items():
        if not config.group_registry.get(key):
            logger.warning(f"定时推送 {key} 未配置群 OpenID，跳过注册")
            continue
        if not config.push_enabled(key):
            logger.info(f"定时推送 {key} 未启用，跳过注册")
            continue
        scheduler.add_job(
            send_broadcast,
            CronTrigger(
                hour=",".join(map(str, message.hours)),
                minute=0,
                timezone="Asia/Shanghai",
            ),
            args=[key],
            id=f"broadcast:{key}",
            misfire_grace_time=60,
            replace_existing=True,
        )
        logger.info(f"已注册定时推送 {key}，每日 {message.hours} 时发送")
```

在模块导入时调用一次。`misfire_grace_time=60` 与仓库现有任务一致。

触发时刻一律是北京时间，`CronTrigger` 因此显式指定 `timezone="Asia/Shanghai"`。
APScheduler 只把调度器的 `apscheduler.timezone` 注入字符串形式的触发器，已经
构造好的 trigger 对象会被原样使用，缺省时回落到进程本地时区（容器里即
`Dockerfile` 的 `TZ`）。不显式指定的话，推送时刻就隐式依赖运行环境，改动基础
镜像或去掉 `TZ` 都会让推送整体偏移 8 小时且没有任何报错。

APScheduler 使用内存 jobstore，进程重启后 `next_run_time` 按当前时间重算，因此
重启不会补发已错过的 12:00 推送；`misfire_grace_time` 只在事件循环被阻塞导致
任务错过触发点时生效。

## 手动触发命令

```python
broadcast_cmd = on_command("推送", priority=10, block=True, rule=Rule(is_superuser))
```

- 仅超级管理员可用（`user_openid(event) in get_driver().config.superusers`），
  官方群聊和私聊均可使用。
- 不受 `CQU_EF_PUSH_ENABLED` 限制——这正是它的用途：上线前先手动试发确认排版，
  开关关着也能用。
- 用法 `推送 CQU_EF`。代号大小写不敏感。
- 按 `send_broadcast` 的返回值回复：`True` 才回复成功卡片；`False` 回复失败卡片，
  提示检查该代号的群 OpenID（`GROUP_<代号>`）是否配置，并查看日志中的具体原因
  ——上线前试发时若群 OpenID 没配好，必须看到失败而不是「已发送」。
  代号未知则回复可用代号列表（`MESSAGES` 的键）。
- 命令名 `推送` 与现有命令无冲突（已核对 `nsy/plugins/*/__init__.py` 全部
  `on_command`）。
- 不复用 `rssget` 的 `ignore_group` 规则：命令只发给注册表里的目标群，与命令
  发出地无关。

## 验证

仓库没有 pytest，不新增测试依赖。

1. `render()` 是纯函数，写一次性脚本打印 `CQU_EF.render()`，与上文「渲染结果」
   逐字比对，确认引用块换行和 Markdown 链接正确。
2. 导入与插件加载检查用仓库根目录的 `.venv/bin/python`（Python 3.13）执行，命令前
   加 `PYTHONPATH=.`：系统 Python 都没有装 `nonebot.adapters.qq`。验证方式是用
   `nonebot.init(driver="~none")` 加载插件——`rssget` 能完整加载证明 `nsy.qq_utils`
   搬迁没有破坏调用方，`broadcast` 能加载并注册出 job 证明 Task 3 的接线正确。
3. 端到端只能在真实群里验证：部署后先不带 `CQU_EF_PUSH_ENABLED` 启动，用
   `推送 CQU_EF` 手动发一次确认排版，再打开开关。

## 不做的事

- 不做数据库表和管理命令：只有一个活动，环境变量加手动触发已覆盖调试与补发。
- 不做每群不同的推送时间：时间写在 `BroadcastMessage.hours` 里，目前只有一组。
- 不重构 `rssget` 的其他部分，不移动 `is_superuser` / `ignore_group` 等规则函数。
