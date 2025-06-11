from typing import Optional
from sqlalchemy import text
from nonebot_plugin_orm import async_scoped_session
from sqlalchemy import select
from .models import Detail , Subscribe, User, Content, Plantform # 导入你的模型定义


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


class SubscribeManger:
    @classmethod
    async def get_all_student_id(cls, session: async_scoped_session) -> set:
        """获取数据库中所有 student_id"""
        result = await session.execute(select(Subscribe.id))
        return {row[0] for row in result}

    @classmethod
    async def get_Sign_by_student_id(cls, session: async_scoped_session, student_id: str) -> Optional[Subscribe]:
        """根据 student_id 获取单个信息"""
        return await session.get(Subscribe, student_id)

    @staticmethod
    async def is_database_empty(db_session):
        # 查询数据库，判断是否有数据
        result = await db_session.execute(text("SELECT 1 FROM Subscribe LIMIT 1"))
        return not result.fetchone()

    @classmethod
    async def create_signmsg(cls, session: async_scoped_session, **kwargs) -> Subscribe:
        """创建新的数据"""
        new_signmsg = Subscribe(**kwargs)
        session.add(new_signmsg)
        await session.commit()
        return new_signmsg

    @classmethod
    async def delete_id(cls, session: async_scoped_session, id: str) -> bool:
        """删除数据"""
        lanmsg = await cls.get_Sign_by_student_id(session, id)
        if lanmsg:
            await session.delete(lanmsg)
            await session.commit()
            return True
        return False


class UserManger:
    @classmethod
    async def get_all_student_id(cls, session: async_scoped_session) -> set:
        """获取数据库中所有 student_id"""
        result = await session.execute(select(User.User_ID))
        return {row[0] for row in result}

    @classmethod
    async def get_Sign_by_student_id(cls, session: async_scoped_session, student_id: str) -> Optional[User]:
        """根据 student_id 获取单个信息"""
        return await session.get(User, student_id)

    @staticmethod
    async def is_database_empty(db_session):
        # 查询数据库，判断是否有数据
        result = await db_session.execute(text("SELECT 1 FROM User LIMIT 1"))
        return not result.fetchone()

    @classmethod
    async def delete_id(cls, session: async_scoped_session, id: str) -> bool:
        """删除数据"""
        lanmsg = await cls.get_Sign_by_student_id(session, id)
        if lanmsg:
            await session.delete(lanmsg)
            await session.commit()
            return True
        return False

    @classmethod
    async def create_signmsg(cls, session: async_scoped_session, **kwargs) -> User:
        """创建新的数据"""
        new_signmsg = User(**kwargs)
        session.add(new_signmsg)
        await session.commit()
        return new_signmsg

class PlantformManger:
    @classmethod
    async def get_all_student_id(cls, session: async_scoped_session) -> set:
        """获取数据库中所有 student_id"""
        result = await session.execute(select(Plantform.name))
        return {row[0] for row in result}

    @classmethod
    async def get_Sign_by_student_id(cls, session: async_scoped_session, student_id: str) -> Optional[Plantform]:
        """根据 student_id 获取单个信息"""
        return await session.get(Plantform, student_id)

    @staticmethod
    async def is_database_empty(db_session):
        # 查询数据库，判断是否有数据
        result = await db_session.execute(text("SELECT 1 FROM Plantform LIMIT 1"))
        return not result.fetchone()

    @classmethod
    async def delete_id(cls, session: async_scoped_session, id: str) -> bool:
        """删除数据"""
        lanmsg = await cls.get_Sign_by_student_id(session, id)
        if lanmsg:
            await session.delete(lanmsg)
            await session.commit()
            return True
        return False

    @classmethod
    async def create_signmsg(cls, session: async_scoped_session, **kwargs) -> User:
        """创建新的数据"""
        new_signmsg = User(**kwargs)
        session.add(new_signmsg)
        await session.commit()
        return new_signmsg

class ContentManger:
    @classmethod
    async def get_all_student_id(cls, session: async_scoped_session) -> set:
        """获取数据库中所有 student_id"""
        result = await session.execute(select(Content.id))
        return {row[0] for row in result}

    @classmethod
    async def get_Sign_by_student_id(cls, session: async_scoped_session, student_id: str) -> Optional[Content]:
        """根据 student_id 获取单个信息"""
        return await session.get(Content, student_id)

    @staticmethod
    async def is_database_empty(db_session):
        # 查询数据库，判断是否有数据
        result = await db_session.execute(text("SELECT 1 FROM Content LIMIT 1"))
        return not result.fetchone()

    @classmethod
    async def create_signmsg(cls, session: async_scoped_session, **kwargs) -> Content:
        """创建新的数据"""
        new_signmsg = Content(**kwargs)
        session.add(new_signmsg)
        await session.commit()
        return new_signmsg