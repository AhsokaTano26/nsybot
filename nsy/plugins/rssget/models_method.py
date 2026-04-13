from typing import Optional

from nonebot_plugin_orm import async_scoped_session
from sqlalchemy import select, text

from .models import (Content, Detail, Groupconfig, Plantform,  # 导入你的模型定义
                     Subscribe, User)


class DetailManager:
    @classmethod
    async def get_all_student_id(cls, session: async_scoped_session) -> set:
        """获取数据库中所有 student_id"""
        result = await session.execute(select(Detail.id))
        return {row[0] for row in result}

    @classmethod
    async def get_Sign_by_student_id(cls, session: async_scoped_session, student_id: str) -> Optional[Detail]:
        """根据 student_id 获取单个信息"""
        return await session.get(Detail, student_id)

    @classmethod
    async def get_existing_ids(cls, session: async_scoped_session, ids: list[str]) -> set[str]:
        """批量检查已存在id"""
        if not ids:
            return set()
        result = await session.execute(select(Detail.id).where(Detail.id.in_(ids)))
        return {row[0] for row in result}

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


class SubscribeManager:
    @classmethod
    async def get_all_student_id(cls, session: async_scoped_session) -> set:
        """获取数据库中所有 student_id"""
        result = await session.execute(select(Subscribe.id))
        return {row[0] for row in result}

    @classmethod
    async def get_all_subscriptions(cls, session: async_scoped_session) -> list[Subscribe]:
        """获取所有订阅记录"""
        result = await session.execute(select(Subscribe))
        return list(result.scalars().all())

    @classmethod
    async def get_subscriptions_by_group(cls, session: async_scoped_session, group_id: str) -> list[Subscribe]:
        """根据群组ID获取所有订阅"""
        result = await session.execute(select(Subscribe).where(Subscribe.group == group_id))
        return list(result.scalars().all())

    @classmethod
    async def get_subscriptions_by_username(cls, session: async_scoped_session, username: str) -> list[Subscribe]:
        """根据用户名获取所有订阅"""
        result = await session.execute(select(Subscribe).where(Subscribe.username == username))
        return list(result.scalars().all())

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


class UserManager:
    @classmethod
    async def get_all_student_id(cls, session: async_scoped_session) -> set:
        """获取数据库中所有 student_id"""
        result = await session.execute(select(User.User_ID))
        return {row[0] for row in result}

    @classmethod
    async def get_all_users(cls, session: async_scoped_session) -> list[User]:
        """获取所有用户记录"""
        result = await session.execute(select(User))
        return list(result.scalars().all())

    @classmethod
    async def get_users_by_ids(cls, session: async_scoped_session, user_ids: list[str]) -> dict[str, User]:
        """根据用户ID列表批量获取用户，返回 {user_id: User} 字典"""
        if not user_ids:
            return {}
        result = await session.execute(select(User).where(User.User_ID.in_(user_ids)))
        return {user.User_ID: user for user in result.scalars().all()}

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

class PlantformManager:
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

class ContentManager:
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

class GroupconfigManager:
    @classmethod
    async def get_all_group_id(cls, session: async_scoped_session) -> set:
        """获取数据库中所有 student_id"""
        result = await session.execute(select(Groupconfig.group_id))
        return {row[0] for row in result}

    @classmethod
    async def get_Sign_by_group_id(cls, session: async_scoped_session, student_id: int) -> Optional[Groupconfig]:
        """根据 student_id 获取单个信息"""
        return await session.get(Groupconfig, student_id)

    @classmethod
    async def get_all_configs(cls, session: async_scoped_session) -> dict[int, Groupconfig]:
        """获取所有群组配置"""
        result = await session.execute(select(Groupconfig))
        return {gc.group_id: gc for gc in result.scalars().all()}

    @staticmethod
    async def is_database_empty(db_session):
        # 查询数据库，判断是否有数据
        result = await db_session.execute(text("SELECT 1 FROM Content LIMIT 1"))
        return not result.fetchone()

    @classmethod
    async def create_signmsg(cls, session: async_scoped_session, **kwargs: object) -> Groupconfig:
        """创建新的数据"""
        new_signmsg = Groupconfig(**kwargs)
        session.add(new_signmsg)
        await session.commit()
        return new_signmsg

    @classmethod
    async def delete_id(cls, session: async_scoped_session, id: int) -> bool:
        """删除数据"""
        lanmsg = await cls.get_Sign_by_group_id(session, id)
        if lanmsg:
            await session.delete(lanmsg)
            await session.commit()
            return True
        return False