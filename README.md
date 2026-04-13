<h1><div style="text-align: center;">文章转发bot</div></h1>
<h4>这是一个以Python编写的QQ机器人插件，用于订阅RSS并实时以QQ消息推送</h4>

---
## 功能介绍
- 支持RSS订阅
- 支持QQ群消息推送
- 支持自定义推送内容
- 订阅内容翻译（默认百度翻译，需要写入自己的 ***API_KEY*** 和 ***SECRET_KEY*** ）
- 对文章进行本地化储存，以减少对于Rsshub的访问次数，同时减少对百度翻译API的调用次数
- 支持多平台订阅
- 默认对自我转发内容不进行推送，对于引用内容进行删除
- 使用Websocket推送
---
## 使用指南
- 考虑到有可能会订阅违规内容，因此本bot在订阅时会对订阅用户进行检查，允许访问列表储存在本地sqlite数据库中管理者可通过增加用户/删除用户/用户列表功能对可访问用户进行增加/删除/查看操作
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

-V3.0更新
> 命令：
> 群组配置 {a} {b} {c} {d} {e}  
> 命令示例：  
> 群组配置 1 1 1 1 0
> 命令参数说明：  
> a: 是否需要转发的推文，1为需要，0为不需要  
> b: 是否需要自我转发的推文，1为需要，0为不需要  
> c: 是否需要翻译，1为需要，0为不需要  
> d：是否需要提示图片个数，1为需要，0为不需要  
> e：是否需要合并转发方式发送推文，1为需要，0为不需要  
> 若无参数，则默认为 1 0 1 1 0
---
## 安装
##### 此bot支持Docker部署和本地部署，建议Docker部署
### Docker部署
##### 使用Github的Action自动构建Docker镜像
- [Docker镜像地址](https://hub.docker.com/r/tano26/nsybot/tags)
0. 确保你的系统已安装docker与docker-compose
1. 点击[此处](https://raw.githubusercontent.com/AhsokaTano26/nsybot/refs/heads/main/docker-compose.yml)下载docker-compose.yml
2. 本地创建db.sqlite3文件，并放置在容器 ***app/data*** 的**外部映射目录下** ，默认为 docker-compose.yml 同级的/data目录
3. 下载并复制`.env.example`为`.env.prod`, 放置在docker-compose.yml 同级的目录，使用任意编辑器修改为你的实际配置。
4. `docker-compose up -d`启动容器
##### 注意
>   - 默认端口为12035
>   - 请于Docker容器的环境变量中给出 ***API_KEY*** 和 ***SECRET_KEY*** 为百度翻译API_KEY和SECRET_KEY  
>   - 请于Docker容器的环境变量中给出 ***REFRESH_TIME*** 作为更新周期（单位为分钟）
>   - 请于Docker容器的环境变量中给出 ***RSSHUB_HOST*** 作为RSSHub 实例地址 默认为 https://rsshub.app
>   - 目前bot支持多平台订阅（例如：twitter、bilibili等），但需要在sqlite数据库Plantform表中手动添加  
>   - 例：  
>   ![这是图片](/docs/img.png "Magic Gardens")  
> 其中 ***name*** 为平台名，***url*** 为Rsshub路由文档所给出的前缀地址，***need_trans*** 为是否需要翻译，1为需要，0为不需要
>   - 提供百度机器翻译、阿里机器翻译、Deepseek翻译类，可自行调用，默认为Deepseek翻译
### 本地部署
>本bot基于nonebot2框架开发，需要本地安装[Nonebot CLI](https://nonebot.dev/docs/quick-start)，请按如下步骤部署：
1. 将本项目克隆到本地，在项目根目录下 ***data*** 文件夹下创建 ***db.sqlite3*** 文件，并提前写入平台数据  
2. 复制`.env.exmaple`为`.env.prod`，填入你的配置项。更多配置项可参考`nsy\plugins\rssget\config.py`
3. 创建`.env`文件，写入`ENVIRONMENT=prod`
4. `nb run`命令启动

### 开发
>本bot基于nonebot2框架开发，需要本地安装[Nonebot CLI](https://nonebot.dev/docs/quick-start)，请按如下步骤部署：
1. 将本项目克隆到本地，在项目根目录下 ***data*** 文件夹下创建 ***db.sqlite3*** 文件，并提前写入平台数据。  
2. 复制`.env.exmaple`为`.env.dev`，填入你的配置项。更多配置项可参考`nsy\plugins\rssget\config.py`
3. 创建`.env`文件，写入`ENVIRONMENT=dev`
4. `nb run`命令启动

---
# 使用注意事项
- 本bot的订阅功能仅群主/群管理员/超级管理员（在 ***.env.prod | . env.dev*** 文件中给出）可使用
- bot默认最多发送10张图片
---
# 感谢以下项目或服务

不分先后
* [CQU Lanunion](https://baike.baidu.com/item/%E9%87%8D%E5%BA%86%E5%A4%A7%E5%AD%A6%E8%93%9D%E7%9B%9F/18227014)
* [RSSHub](https://github.com/DIYgod/RSSHub)
* [Nonebot](https://github.com/nonebot/nonebot2)
* [百度机器翻译](https://cloud.baidu.com/doc/API/index.html)
* [Napcat](https://napneko.github.io/guide/napcat)
* [onebotv11](https://283375.github.io/onebot_v11_vitepress/)
