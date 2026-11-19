from nonebot_plugin_orm import Model
from sqlalchemy import Column, String, Text, DateTime, BOOLEAN, CheckConstraint, ForeignKey, Integer


class Detail(Model):
    __tablename__ = "Detail"
    id = Column(String(255), primary_key=True, nullable=True)  #id
    summary = Column(String(255), nullable=True)  # summary
    updated = Column(DateTime, nullable=True)

class Subscribe(Model):
    __tablename__ = "Subscribe"
    id = Column(String(255), primary_key=True, nullable=True)
    username = Column(String(255), nullable=True)
    group = Column(String(255), nullable=True)

class User(Model):
    __tablename__ = "User"
    User_ID = Column(String(255), primary_key=True, nullable=True)  #id
    User_Name = Column(String(255), nullable=True)  # summary
    Plantform = Column(String(255), nullable=True) #平台

class Plantform(Model):
    __tablename__ = "Plantform"
    name = Column(String(255), primary_key=True, nullable=True)
    url = Column(String(255), nullable=True)
    need_trans = Column(String(255), nullable=True)

class Content(Model):
    __tablename__ = "Content"
    id = Column(String(255), primary_key=True, nullable=True)
    username = Column(String(255), nullable=True)
    title = Column(String(255), nullable=True)
    time = Column(String(255), nullable=True)
    link = Column(String(255), nullable=True)
    text = Column(Text, nullable=True)
    trans_text = Column(String(255), nullable=True)
    image_num = Column(String(255), nullable=True)
    images = Column(Text, nullable=True)


class ImageSync(Model):
    """图片文章首次入库的顺序，与发布时间及 QQ 推送记录无关。"""

    __tablename__ = "rss_image_sync"
    __table_args__ = {"sqlite_autoincrement": True}
    seq = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(String(255), ForeignKey("Content.id"), nullable=False, unique=True)


class RSSFeedCache(Model):
    """各账号最近一次有效 RSS 窗口，保留条目顺序供独立推送读取。"""

    __tablename__ = "rss_feed_cache"
    account_id = Column(String(255), primary_key=True, nullable=False)
    entries = Column(Text, nullable=False)
    digest = Column(String(64), nullable=False)
    collected_at = Column(DateTime, nullable=False)


class RSSSourceStatus(Model):
    __tablename__ = "rss_source_status"
    source = Column(String(32), primary_key=True, nullable=False)
    available = Column(BOOLEAN, nullable=False)
    observed_at = Column(DateTime, nullable=False)
    retry_at = Column(DateTime, nullable=True)


class RSSSourceNotice(Model):
    __tablename__ = "rss_source_notice"
    __table_args__ = {"sqlite_autoincrement": True}
    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(32), nullable=False)
    available = Column(BOOLEAN, nullable=False)
    observed_at = Column(DateTime, nullable=False)


class RSSIngestQueue(Model):
    """先持久化原始条目，入库成功后与文章、图片索引原子确认。"""

    __tablename__ = "rss_ingest_queue"
    id = Column(String(255), primary_key=True, nullable=False)
    username = Column(String(255), nullable=True)
    entry = Column(Text, nullable=False)
    version = Column(String(64), nullable=False)
    attempts = Column(Integer, nullable=False)
    next_retry_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False)
    last_error = Column(String(64), nullable=True)


class Groupconfig(Model):
    __tablename__ = "Group_config"
    __table_args__ = (
        CheckConstraint("push_limit IN (0, 1, 2, 3, 4, 5)", name="push_limit_range"),
    )
    # QQ 官方接口使用 group_openid（非数字 QQ 群号）。
    group_id = Column(String(255), primary_key=True, nullable=False)
    if_need_trans = Column(BOOLEAN, nullable=False)
    if_need_self_trans = Column(BOOLEAN, nullable=False)
    if_need_translate = Column(BOOLEAN, nullable=False)
    # 图片数量提示已停用；保留旧列以兼容已有数据库。
    if_need_photo_num_mention = Column(BOOLEAN, nullable=False)
    # 旧版 OneBot 合并转发的遗留列；为兼容现有数据库保留，不再参与配置或发送逻辑。
    if_need_merged_message = Column(BOOLEAN, nullable=False)
    # 每账号每轮保留 RSS 最新 N 篇；0 表示不限制数量。
    push_limit = Column(Integer, nullable=False, default=1, server_default="1")


class BotGroup(Model):
    """机器人当前所在群；历史补录不代表已确认真实入群时间。"""

    __tablename__ = "bot_group"
    group_openid = Column(String(255), primary_key=True, nullable=False)
    joined_at = Column(DateTime, nullable=True)
    recorded_at = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)
    source = Column(String(16), nullable=False)
