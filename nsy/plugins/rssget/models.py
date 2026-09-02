from nonebot_plugin_orm import Model
from sqlalchemy import Column, String, Text, DateTime, BOOLEAN


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

class Groupconfig(Model):
    __tablename__ = "Group_config"
    # QQ 官方接口使用 group_openid（非数字 QQ 群号）。
    group_id = Column(String(255), primary_key=True, nullable=False)
    if_need_trans = Column(BOOLEAN, nullable=False)
    if_need_self_trans = Column(BOOLEAN, nullable=False)
    if_need_translate = Column(BOOLEAN, nullable=False)
    if_need_photo_num_mention = Column(BOOLEAN, nullable=False)
    # 旧版 OneBot 合并转发的遗留列；为兼容现有数据库保留，不再参与配置或发送逻辑。
    if_need_merged_message = Column(BOOLEAN, nullable=False)
