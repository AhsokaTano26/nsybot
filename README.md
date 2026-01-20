<h1><div style="text-align: center;">文章转发bot</div></h1>
<h4>这是一个以Python编写的QQ机器人插件，用于订阅RSS并实时以QQ消息推送</h4>

---
## 功能介绍
- 支持RSS订阅
- 支持QQ群消息推送
- 支持自定义推送内容
- 订阅内容翻译（默认DeepSeek翻译，需配置 ***API_KEY***）
- 对文章进行本地化储存，以减少对于RSSHub的访问次数，同时减少翻译API的调用次数
- 支持多平台订阅
- 默认对自我转发内容不进行推送，对于引用内容进行删除
- 使用Websocket推送
- **卡片模式**：将推文渲染为精美的图片卡片发送（支持中英日韩文及Emoji）
---
## 使用指南
- 考虑到有可能会订阅违规内容，因此本bot在订阅时会对订阅用户进行检查，允许访问列表储存在本地sqlite数据库中，管理者可通过增加用户/删除用户/用户列表功能对可访问用户进行增加/删除/查看操作
- 命令指南 ***{}内的内容为发起请求时填写内容*** ：  
> 推文查看: rss {用户名} {文章序列号(不填默认为0，即最新文章)}  
> 订阅列表：订阅列表  
> 开始订阅：订阅 {用户名} {推送群组}  
> 查询用户推文列表：文章列表 {用户名}  
> 取消订阅：取消订阅 {用户名} {推送群组}  
> 增加用户：增加用户 {用户ID} {用户名} {平台名}  
> 删除用户：删除用户 {用户ID} {用户名}  
> 用户列表：用户列表  
> 查询群组订阅：查询 群组 {群组ID}  
> 查询用户被订阅：查询 用户 {用户ID}  

### 群组配置（V3.1更新）
> 命令格式：
> ```
> 群组配置 {a} {b} {c} {d} {e} {f}
> ```
> 命令示例：  
> ```
> 群组配置 1 0 1 1 0 1
> ```
> 参数说明：  
> | 参数 | 说明 | 值 |
> |:---:|:---|:---:|
> | a | 是否转发他人推文 | 1=是, 0=否 |
> | b | 是否转发自我转发 | 1=是, 0=否 |
> | c | 是否翻译 | 1=是, 0=否 |
> | d | 是否提示图片数量 | 1=是, 0=否 |
> | e | 是否合并转发 | 1=是, 0=否 |
> | f | 是否启用卡片模式 | 1=是, 0=否 |
>
> 若无参数，默认为 `1 0 1 1 0 0`

---
## 安装
##### 此bot支持Docker部署和本地部署，建议Docker部署
### Docker部署
##### 使用Github Action自动构建Docker镜像
- [Docker镜像地址](https://hub.docker.com/r/tano26/nsybot/tags)
> - 部署时需本地创建 `db.sqlite3` 文件，并挂载至容器 `/app/data` 目录下  
> - 默认端口为 **12035**
> - 环境变量配置：
>   - `API_KEY`：翻译服务API密钥（DeepSeek/百度/阿里）
>   - `SECRET_KEY`：百度翻译专用密钥（使用DeepSeek时可不填）
>   - `REFRESH_TIME`：更新周期（单位：分钟，默认20）
>   - `RSSHUB_HOST`：RSSHub实例地址，默认 https://rsshub.app
>   - `RSSHUB_HOST_BACK`：备用RSSHub地址（可选）
> - 多平台订阅需在sqlite数据库 `Plantform` 表中手动添加  
>   ![平台配置示例](/docs/img.png "平台配置")  
>   - `name`：平台名
>   - `url`：RSSHub路由前缀
>   - `need_trans`：是否需要翻译（1=是, 0=否）
> - 翻译服务支持：百度机器翻译、阿里机器翻译、DeepSeek（默认）

### 本地部署
> 本bot基于NoneBot2框架开发，需先安装 [NoneBot CLI](https://nonebot.dev/docs/quick-start)  
> 1. 克隆本项目到本地
> 2. 在 `data/` 目录下创建 `db.sqlite3` 文件并写入平台数据
> 3. 配置环境变量（参考 `.env.example`）
>
> **卡片模式字体配置**（可选，启用卡片模式时需要）：
> - 下载 [Noto Sans CJK](https://github.com/notofonts/noto-cjk/releases) 字体
> - 支持的字体文件（任选其一放入 `data/fonts/` 目录）：
>   - `NotoSansCJKsc-Regular.otf` + `NotoSansCJKsc-Bold.otf`（推荐）
>   - `NotoSansCJK-Regular.ttc` + `NotoSansCJK-Bold.ttc`
>   - `NotoSansSC-VariableFont_wght.ttf`
> - Windows 系统可自动使用微软雅黑字体，无需额外配置

---
## 使用注意事项
- 订阅功能仅群主/群管理员/超级管理员可使用（超级管理员在 `.env` 文件中配置）
- bot默认最多发送10张图片
- 卡片模式需要安装字体支持（Docker镜像已内置）

---
## 感谢以下项目或服务

不分先后
* [CQU Lanunion](https://baike.baidu.com/item/%E9%87%8D%E5%BA%86%E5%A4%A7%E5%AD%A6%E8%93%9D%E7%9B%9F/18227014)
* [RSSHub](https://github.com/DIYgod/RSSHub)
* [Nonebot](https://github.com/nonebot/nonebot2)
* [百度机器翻译](https://cloud.baidu.com/doc/API/index.html)
* [Napcat](https://napneko.github.io/guide/napcat)
* [onebotv11](https://283375.github.io/onebot_v11_vitepress/)
