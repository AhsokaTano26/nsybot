from nonebot_plugin_orm import Model
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship


class Detail(Model):
    __tablename__ = "Detail"

    id = Column(String(255), primary_key=True, nullable=True)  #id
    summary = Column(String(255), nullable=True)  # summary

class Subscribe(Model):
    __tablename__ = "Subscribe"
    id = Column(String(255), primary_key=True, nullable=True)
    username = Column(String(255), nullable=True)
    group = Column(String(255), nullable=True)