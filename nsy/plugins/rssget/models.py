from nonebot_plugin_orm import Model
from sqlalchemy import Column, String, Text, DateTime


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