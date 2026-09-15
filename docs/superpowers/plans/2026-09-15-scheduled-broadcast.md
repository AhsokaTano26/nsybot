# 定时推送插件（broadcast）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `nsy/plugins/broadcast/` 插件，按「群注册表」向指定群聊定时发送活动消息，首个场景是代号 `CQU_EF` 的群每日 12:00 / 18:00 收到法批定制活动消息。

**Architecture:** 把与 RSS 无关的通用 QQ 工具模块 `nsy/plugins/rssget/qq.py` 上移为 `nsy/qq_utils.py`，供 `rssget` 与新插件共用。新插件分成三层：`config.py` 管群注册表与开关，`messages.py` 管消息内容与渲染，`__init__.py` 管发送流程、定时任务注册和超管手动触发命令。

**Tech Stack:** Python 3.13（`.venv`）、NoneBot2 2.5.0、nonebot-adapter-qq 1.7.2、nonebot-plugin-apscheduler 0.5.0、pydantic 2.13.5、loguru

**Spec:** `docs/superpowers/specs/2026-09-15-scheduled-broadcast-design.md`

## Global Constraints

- **Commit 信息只写一句话**，且**不得出现 Claude / Anthropic / Co-Authored-By / "Generated with"** 等任何 AI 署名或生成标记。不带 body，不带 footer。
- **用 `.venv/bin/python` 验证**，命令前加 `PYTHONPATH=.`，工作目录为仓库根 `/Users/tano/Documents/GitHub/personal/nsybot`。系统 Python 3.11/3.13/3.14 都没有装 `nonebot.adapters.qq`。
- **绝对不要运行 `nb run`、`bot.py` 或 `run.py`**，也不要调用 `nonebot.run()`。仓库根目录的 `.env` 是**生产配置**（含真实 QQ AppSecret、API Key、群 OpenID），跑起来会真的连上 QQ 并给真实群发消息。所有验证脚本一律用 `nonebot.init(driver="~none")` 加载插件，只用 `~none` 驱动。
- **不引入 pytest**，不新增测试依赖。验证用一次性脚本（`python - <<'PY'` heredoc），脚本不入库。
- 所有新增函数写类型注解；日志统一用 `from nonebot.log import logger`。
- 每个任务结束时提交，提交信息按上面的一句话规则。

---

### Task 1: 把 `qq.py` 上移为 `nsy/qq_utils.py`

`qq.py` 里的函数（Markdown 截断、引用块、远程图片下载上传、主动发群消息）与 RSS 无关。独立插件若直接 `import nsy.plugins.rssget.qq`，会连带执行 `rssget/__init__.py`，把全部 RSS 命令和定时任务在导入期就注册掉。先把它挪到顶层共享位置。

**Files:**
- Move: `nsy/plugins/rssget/qq.py` → `nsy/qq_utils.py`（内容零改动）
- Modify: `nsy/plugins/rssget/__init__.py:31-34`
- Modify: `nsy/plugins/rssget/functions.py:17`
- Modify: `nsy/plugins/rssget/send_msg.py:5`

**Interfaces:**
- Consumes: 无
- Produces: 模块 `nsy.qq_utils`，导出 `article_card`、`card`、`code_block`、`command_keyboard`、`download_image`、`error`、`file_image`、`group_openid`、`info`、`is_c2c_event`、`is_group_event`、`markdown`、`quote_block`、`quoted_card`、`send_group_markdown`、`send_group_message`、`success`、`truncate_markdown`、`user_openid`、`warning`。签名全部不变。后续任务用到的是 `markdown(content: str) -> MessageSegment`、`quote_block(content: str) -> str`、`send_group_message(bot, group_id: str, message) -> Any`、`download_image(url: str, client=None) -> tuple[bytes, str]`、`file_image(data: bytes, file_name: str) -> MessageSegment`、`user_openid(event) -> str`、`success(body, title=...) -> MessageSegment`、`error(body, title=...) -> MessageSegment`。

- [ ] **Step 1: 记录改动前状态**

Run:
```bash
grep -rn "from \.qq import" nsy/
```
Expected: 3 行命中（`rssget/__init__.py`、`rssget/functions.py`、`rssget/send_msg.py`）。

- [ ] **Step 2: 移动文件（保留 git 历史）**

Run:
```bash
git mv nsy/plugins/rssget/qq.py nsy/qq_utils.py
```
Expected: 无输出，`git status` 显示 `renamed: nsy/plugins/rssget/qq.py -> nsy/qq_utils.py`。

- [ ] **Step 3: 改 `nsy/plugins/rssget/__init__.py` 的 import**

把原有的（第 31-34 行）：
```python
from .qq import (article_card, command_keyboard, download_image, error,
                 file_image, group_openid, info, is_c2c_event, is_group_event,
                 markdown, quoted_card, send_group_message, success,
                 user_openid, warning)
```
替换为（保持原位置、原缩进，仅改模块路径）：
```python
from nsy.qq_utils import (article_card, command_keyboard, download_image,
                          error, file_image, group_openid, info, is_c2c_event,
                          is_group_event, markdown, quoted_card,
                          send_group_message, success, user_openid, warning)
```

- [ ] **Step 4: 改 `nsy/plugins/rssget/functions.py` 的 import**

把第 17 行：
```python
from .qq import article_card, download_image, error, file_image, info, send_group_message
```
替换为：
```python
from nsy.qq_utils import article_card, download_image, error, file_image, info, send_group_message
```

- [ ] **Step 5: 改 `nsy/plugins/rssget/send_msg.py` 的 import**

把第 5 行：
```python
from .qq import download_image, error, file_image, send_group_message
```
替换为：
```python
from nsy.qq_utils import download_image, error, file_image, send_group_message
```
（`send_msg.py` 是废弃文件，改它只为保证仍可导入。）

- [ ] **Step 6: 确认没有残留引用**

Run:
```bash
grep -rn "from \.qq import\|from \. import qq" nsy/
```
Expected: 无输出（退出码 1）。

- [ ] **Step 7: 验证新模块能导入且函数可用**

Run:
```bash
cd /Users/tano/Documents/GitHub/personal/nsybot && PYTHONPATH=. .venv/bin/python -c "
from nsy.qq_utils import quote_block, markdown, file_image
assert quote_block('a\n\nb') == '> a\n>\n> b', repr(quote_block('a\n\nb'))
seg = markdown('# t\n\n> b')
assert seg.type == 'markdown', seg.type
assert seg.data['markdown'].content == '# t\n\n> b'
img = file_image(b'x', 'y.png')
assert img.type == 'file_image', img.type
print('nsy.qq_utils OK')
"
```
Expected: `nsy.qq_utils OK`

- [ ] **Step 8: 验证 rssget 插件仍能完整加载**

这是本任务真正的回归验证：插件加载会真正执行 `from nsy.qq_utils import (...)`，任何名字写错或路径写错都会在这里炸出来。

Run:
```bash
cd /Users/tano/Documents/GitHub/personal/nsybot && PYTHONPATH=. .venv/bin/python -c "
import nonebot
nonebot.init(driver='~none')
p = nonebot.load_plugin('nsy.plugins.rssget')
assert p is not None, 'rssget 加载失败'
print('rssget loaded, matchers =', len(p.matcher))
" 2>&1 | tail -5
```
Expected: 末尾出现 `rssget loaded, matchers = 28`（数量只要 > 0 即可，说明命令全部注册成功）。**不应出现任何 Traceback。**

- [ ] **Step 9: Commit**

```bash
git add nsy/qq_utils.py nsy/plugins/rssget/__init__.py nsy/plugins/rssget/functions.py nsy/plugins/rssget/send_msg.py
git commit -m "refactor: 把通用 QQ 工具模块上移为 nsy.qq_utils"
```

---

### Task 2: broadcast 插件的配置与消息定义

**Files:**
- Create: `nsy/plugins/broadcast/config.py`
- Create: `nsy/plugins/broadcast/messages.py`
- Modify: `.env.example`（文件末尾追加）

**Interfaces:**
- Consumes: `nsy.qq_utils.quote_block`（Task 1 产出）
- Produces:
  - `nsy.plugins.broadcast.config.Config`，pydantic `BaseModel`，字段 `group_cqu_ef: str | None`（默认 `None`）、`cqu_ef_push_enabled: bool`（默认 `False`）；属性 `group_registry -> dict[str, str]`；方法 `push_enabled(key: str) -> bool`
  - `nsy.plugins.broadcast.messages.BroadcastMessage`，frozen dataclass，字段 `key: str`、`title: str`、`hours: tuple[int, ...]`、`body: str`、`images: tuple[str, ...] = ()`；方法 `render() -> str`
  - `nsy.plugins.broadcast.messages.CQU_EF: BroadcastMessage`
  - `nsy.plugins.broadcast.messages.MESSAGES: dict[str, BroadcastMessage]`

- [ ] **Step 1: 写 `nsy/plugins/broadcast/config.py`**

```python
from pydantic import BaseModel


class Config(BaseModel):
    """定时推送配置。

    群注册表由下方字段汇总：GROUP_<代号> 提供群 OpenID，
    <代号>_PUSH_ENABLED 控制是否注册定时任务。
    新增群聊 = 加一组字段 + 在 group_registry / push_enabled 里各登记一行。
    """

    group_cqu_ef: str | None = None
    cqu_ef_push_enabled: bool = False

    @property
    def group_registry(self) -> dict[str, str]:
        """业务代号 -> group_openid；未配置 OpenID 的代号不会出现。"""
        registry = {"CQU_EF": self.group_cqu_ef}
        return {key: openid for key, openid in registry.items() if openid}

    def push_enabled(self, key: str) -> bool:
        """该代号是否开启定时推送。"""
        return {"CQU_EF": self.cqu_ef_push_enabled}.get(key, False)
```

- [ ] **Step 2: 写 `nsy/plugins/broadcast/messages.py`**

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

注意：`body` 里的两个字符串字面量之间**没有空格**，拼接后第一行必须是
`各位老师，……请填写尺码。`，第二行以 `【腾讯文档】` 开头。

- [ ] **Step 3: 追加 `.env.example`**

在 `.env.example` **文件末尾**追加（前面留一个空行）：

```dotenv

# 定时推送（broadcast 插件）
# 群注册表：GROUP_<代号> 填写该群的 group_openid，留空则该代号不可用。
GROUP_CQU_EF=your-cqu-ef-group-openid
# 是否注册每日 12:00 / 18:00 的定时推送，默认关闭。手动触发命令「推送 CQU_EF」不受此开关限制。
CQU_EF_PUSH_ENABLED=false
```

- [ ] **Step 4: 验证配置默认值与注册表行为**

Run:
```bash
cd /Users/tano/Documents/GitHub/personal/nsybot && PYTHONPATH=. .venv/bin/python -c "
from nsy.plugins.broadcast.config import Config

default = Config()
assert default.group_registry == {}, default.group_registry
assert default.push_enabled('CQU_EF') is False
assert default.push_enabled('UNKNOWN') is False

configured = Config(group_cqu_ef='test-openid', cqu_ef_push_enabled=True)
assert configured.group_registry == {'CQU_EF': 'test-openid'}, configured.group_registry
assert configured.push_enabled('CQU_EF') is True
print('config OK')
"
```
Expected: `config OK`

- [ ] **Step 5: 验证渲染结果逐字正确**

这是本次改动里唯一能被自动化钉死的输出内容，断言必须与实际渲染结果逐字一致。

Run:
```bash
cd /Users/tano/Documents/GitHub/personal/nsybot && PYTHONPATH=. .venv/bin/python -c "
from nsy.plugins.broadcast.messages import CQU_EF, MESSAGES

expected = (
    '# 🧥 EF邦多利马群法批定制 · 第二弹\n'
    '\n'
    '> 各位老师，EF邦多利马群法批好评如潮第二弹开始了。如有需求，请填写表格，定制信息空白，默认原版，同时请填写尺码。\n'
    '> 【腾讯文档】[法批定制](https://docs.qq.com/sheet/DVVJTZnNZdmFIcHh5?tab=BB08J2)'
)
actual = CQU_EF.render()
assert actual == expected, '\n--- 实际 ---\n' + actual + '\n--- 期望 ---\n' + expected

assert CQU_EF.hours == (12, 18), CQU_EF.hours
assert len(CQU_EF.images) == 2, CQU_EF.images
assert CQU_EF.images[0].endswith('47b932ae-cc92-4ca8-8f9b-a462846b6f27.png')
assert CQU_EF.images[1].endswith('d03d97db-ebf6-43b4-be80-77afff7057e0.png')
assert MESSAGES['CQU_EF'] is CQU_EF
print('render OK')
"
```
Expected: `render OK`

- [ ] **Step 6: Commit**

```bash
git add nsy/plugins/broadcast/config.py nsy/plugins/broadcast/messages.py .env.example
git commit -m "feat: 新增定时推送插件的群注册表配置与消息定义"
```

---

### Task 3: broadcast 插件的发送流程、定时任务与手动命令

**Files:**
- Create: `nsy/plugins/broadcast/__init__.py`
- Modify: `CLAUDE.md:52`（插件清单）、`CLAUDE.md:75-78`（定时任务清单）

**Interfaces:**
- Consumes:
  - `nsy.plugins.broadcast.config.Config`（Task 2）
  - `nsy.plugins.broadcast.messages.MESSAGES`、`BroadcastMessage`（Task 2）
  - `nsy.qq_utils` 的 `markdown`、`quote_block`、`send_group_message`、`download_image`、`file_image`、`success`、`error`、`user_openid`（Task 1）
- Produces:
  - 模块级 `config: Config`、`scheduler`、`broadcast_cmd`
  - `async def send_broadcast(key: str) -> None`
  - `_register_jobs() -> None`（模块导入时自动执行一次）
  - 超管命令 `推送 <代号>`

- [ ] **Step 1: 写 `nsy/plugins/broadcast/__init__.py`**

```python
"""定时推送插件。

按「群注册表」向指定群聊定时发送活动消息：代号到 group_openid 的映射来自配置
（``GROUP_<代号>``），消息内容来自 :mod:`nsy.plugins.broadcast.messages`。
"""

from apscheduler.triggers.cron import CronTrigger
from nonebot import get_bot, get_driver, get_plugin_config, on_command, require
from nonebot.adapters.qq import Event, Message
from nonebot.log import logger
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from nsy.qq_utils import (download_image, error, file_image, markdown,
                          send_group_message, success, user_openid)

from .config import Config
from .messages import MESSAGES, BroadcastMessage

__plugin_meta__ = PluginMetadata(
    name="定时推送",
    description="按群注册表向指定群聊定时发送活动消息",
    usage="推送 <代号>  # 超管手动触发一次定时推送",
    type="QQbot",
    config=Config,
)

config = get_plugin_config(Config)
scheduler = require("nonebot_plugin_apscheduler").scheduler


async def is_superuser(event: Event) -> bool:
    """仅超级管理员可手动触发推送。"""
    try:
        return user_openid(event) in set(get_driver().config.superusers)
    except ValueError:
        return False


async def send_broadcast(key: str) -> None:
    """向该代号登记的群发送一条推送，供定时任务与手动命令共用。

    先发 Markdown 文本，再逐张发图片。文本发送失败即中止——没有配文时发图
    没有意义；单张图片失败只记日志并继续下一张。
    """
    message: BroadcastMessage | None = MESSAGES.get(key)
    if message is None:
        logger.error(f"未知的推送代号: {key}")
        return

    group_id = config.group_registry.get(key)
    if not group_id:
        logger.error(f"推送 {key} 未配置群 OpenID，已跳过")
        return

    try:
        bot = get_bot()
    except ValueError as e:
        logger.error(f"推送 {key} 未能获取 bot 实例: {e}")
        return

    try:
        await send_group_message(bot, group_id, markdown(message.render()))
    except Exception as e:
        logger.opt(exception=True).error(f"推送 {key} 文本发送失败: {e}")
        return

    for index, url in enumerate(message.images, start=1):
        try:
            data, file_name = await download_image(url)
            await send_group_message(bot, group_id, file_image(data, file_name))
        except Exception as e:
            logger.opt(exception=True).error(
                f"推送 {key} 第 {index} 张图片发送失败: {e}"
            )

    logger.info(f"推送 {key} 已完成，目标群 {group_id}")


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
            CronTrigger(hour=",".join(map(str, message.hours)), minute=0),
            args=[key],
            id=f"broadcast:{key}",
            misfire_grace_time=60,
            replace_existing=True,
        )
        logger.info(f"已注册定时推送 {key}，每日 {message.hours} 时发送")


_register_jobs()


broadcast_cmd = on_command("推送", priority=10, block=True, rule=Rule(is_superuser))


@broadcast_cmd.handle()
async def handle_broadcast(args: Message = CommandArg()):
    """超管手动触发一次推送，不受推送开关限制。"""
    key = args.extract_plain_text().strip().upper()
    if key not in MESSAGES:
        available = "、".join(MESSAGES)
        await broadcast_cmd.finish(
            error(f"未知推送代号：{key or '（空）'}\n可用代号：{available}")
        )

    await send_broadcast(key)
    await broadcast_cmd.finish(success(f"已向 {key} 登记的群发送推送"))
```

- [ ] **Step 2: 验证未开启开关时不注册定时任务**

Run:
```bash
cd /Users/tano/Documents/GitHub/personal/nsybot && GROUP_CQU_EF=test-openid PYTHONPATH=. .venv/bin/python -c "
import nonebot
nonebot.init(driver='~none')
p = nonebot.load_plugin('nsy.plugins.broadcast')
assert p is not None, 'broadcast 加载失败'
from nonebot_plugin_apscheduler import scheduler
ids = [j.id for j in scheduler.get_jobs()]
assert 'broadcast:CQU_EF' not in ids, ids
print('disabled OK, jobs =', ids)
" 2>&1 | tail -3
```
Expected: 末尾为 `disabled OK, jobs = []`。**不应出现 Traceback。**

- [ ] **Step 3: 验证开启开关后按 12/18 点注册定时任务**

Run:
```bash
cd /Users/tano/Documents/GitHub/personal/nsybot && GROUP_CQU_EF=test-openid CQU_EF_PUSH_ENABLED=true PYTHONPATH=. .venv/bin/python -c "
import nonebot
nonebot.init(driver='~none')
nonebot.load_plugin('nsy.plugins.broadcast')
from nonebot_plugin_apscheduler import scheduler
job = scheduler.get_job('broadcast:CQU_EF')
assert job is not None, [j.id for j in scheduler.get_jobs()]
trigger = str(job.trigger)
assert \"hour='12,18'\" in trigger, trigger
assert \"minute='0'\" in trigger, trigger
print('enabled OK, trigger =', trigger)
" 2>&1 | tail -3
```
Expected: 末尾为 `enabled OK, trigger = cron[hour='12,18', minute='0']`。

- [ ] **Step 4: 验证发送流程（打桩，不发真实请求）**

这一步把 `get_bot` / `send_group_message` / `download_image` 换成打桩函数，检查发送顺序与内容，不产生任何网络请求。

Run:
```bash
cd /Users/tano/Documents/GitHub/personal/nsybot && GROUP_CQU_EF=test-openid PYTHONPATH=. .venv/bin/python -c "
import asyncio
import nsy.plugins.broadcast as b

calls = []

class FakeBot:
    pass

async def fake_send(bot, group_id, message):
    calls.append((group_id, message))

async def fake_download(url, client=None):
    return b'fake-bytes', 'fake.png'

b.get_bot = lambda: FakeBot()
b.send_group_message = fake_send
b.download_image = fake_download

asyncio.run(b.send_broadcast('CQU_EF'))

assert len(calls) == 3, len(calls)
group_ids = {c[0] for c in calls}
assert group_ids == {'test-openid'}, group_ids

seg0 = calls[0][1]
assert seg0.type == 'markdown', seg0.type
assert seg0.data['markdown'].content == b.MESSAGES['CQU_EF'].render()

for seg in (calls[1][1], calls[2][1]):
    assert seg.type == 'file_image', seg.type
    assert seg.data['file_name'] == 'fake.png'
    assert seg.data['content'] == b'fake-bytes'

print('send OK')
" 2>&1 | tail -3
```
Expected: 末尾为 `send OK`。

- [ ] **Step 5: 验证未知代号不会崩**

Run:
```bash
cd /Users/tano/Documents/GitHub/personal/nsybot && GROUP_CQU_EF=test-openid PYTHONPATH=. .venv/bin/python -c "
import asyncio
import nsy.plugins.broadcast as b

async def fake_send(bot, group_id, message):
    raise AssertionError('不应发送任何消息')

b.get_bot = lambda: object()
b.send_group_message = fake_send
asyncio.run(b.send_broadcast('NOPE'))
print('unknown key OK')
" 2>&1 | tail -3
```
Expected: 末尾为 `unknown key OK`（同时日志里有一行 `未知的推送代号: NOPE`）。

- [ ] **Step 6: 验证命令名不与现有命令冲突**

Run:
```bash
cd /Users/tano/Documents/GitHub/personal/nsybot && grep -rn 'on_command("推送"' nsy/
```
Expected: 只有一行命中，即 `nsy/plugins/broadcast/__init__.py`。

- [ ] **Step 7: 更新 `CLAUDE.md` 插件清单**

在 `CLAUDE.md:52` 的 Detect plugin 段落之后插入一个空行和：

```markdown
**Broadcast plugin** (`nsy/plugins/broadcast/`): 定时推送插件。按「群注册表」（配置里的 `GROUP_<代号>` 环境变量，业务代号如 `CQU_EF`）向指定群聊定时发送活动消息。首个场景是 `CQU_EF` 群每日 12:00 / 18:00 推送法批定制活动（一条 Markdown + 两张图片）。`<代号>_PUSH_ENABLED` 控制是否注册定时任务，默认关闭；超管命令 `推送 <代号>` 可手动触发且不受开关限制。
```

在 `CLAUDE.md:78` 的 Detect health check 之后追加一行：

```markdown
- Broadcast push: daily 12:00/18:00 for each enabled group key (in broadcast plugin)
```

- [ ] **Step 8: Commit**

```bash
git add nsy/plugins/broadcast/__init__.py CLAUDE.md
git commit -m "feat: 新增定时推送插件的发送流程与超管手动触发命令"
```

---

### Task 4: 上线前人工验证（需要真实部署，不在本地执行）

本地 `.env` 是生产配置且没有 QQ 长连接，无法端到端验证。这一步只能在部署环境做，属于**人工步骤**，不产生 commit。

- [ ] **Step 1: 部署时确认环境变量**

在部署环境的 `.env.prod` 里设置：

```dotenv
GROUP_CQU_EF=<CQU_EF 群的 group_openid>
CQU_EF_PUSH_ENABLED=false
```

群 OpenID 的获取方式：把机器人拉进目标群，在群里 @ 机器人发 `群信息`，消息返回的群 OpenID 可复制（见 `nsy/plugins/get_info/__init__.py`）。

- [ ] **Step 2: 先不打开开关，用超管命令试发一次**

部署后在任意会话（群聊或私聊）以超级管理员身份发送：

```
推送 CQU_EF
```

Expected: 目标群收到 1 条 Markdown 消息 + 2 张图片，共 3 条。**重点检查**：标题渲染、正文引用块换行、`法批定制` 链接可点击、两张图片都能看到。命令发起方会收到一条「已向 CQU_EF 登记的群发送推送」的卡片。

- [ ] **Step 3: 确认无误后打开开关**

把 `CQU_EF_PUSH_ENABLED` 改为 `true` 并重启。日志中应出现：

```
已注册定时推送 CQU_EF，每日 (12, 18) 时发送
```

- [ ] **Step 4: 活动结束后关闭**

把 `CQU_EF_PUSH_ENABLED` 改回 `false` 并重启即可停止定时推送，不需要改代码。
