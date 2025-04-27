from typing import Optional
from sqlalchemy import text
from nonebot_plugin_orm import async_scoped_session
from sqlalchemy import select
from .models import Detail  # 导入你的模型定义


class DetailManger:
    @classmethod
    async def get_all_student_id(cls, session: async_scoped_session) -> set:
        """获取数据库中所有 student_id"""
        result = await session.execute(select(Detail.id))
        return {row[0] for row in result}

    @classmethod
    async def get_Sign_by_student_id(cls, session: async_scoped_session, student_id: str) -> Optional[Detail]:
        """根据 student_id 获取单个信息"""
        return await session.get(Detail, student_id)

    @staticmethod
    async def is_database_empty(db_session):
        # 查询数据库，判断是否有数据
        result = await db_session.execute(text("SELECT 1 FROM Detail LIMIT 1"))
        return not result.fetchone()

    @classmethod
    async def create_signmsg(cls, session: async_scoped_session, **kwargs) -> Detail:
        """创建新的数据"""
        new_signmsg = Detail(**kwargs)
        session.add(new_signmsg)
        await session.commit()
        return new_signmsg

