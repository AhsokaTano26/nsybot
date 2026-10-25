from datetime import datetime, timedelta
from typing import Optional
import hashlib
import json

from nonebot_plugin_orm import async_scoped_session
from sqlalchemy import delete, func, select, text

from .models import (Content, Detail, Groupconfig, Plantform,  # 导入你的模型定义
                     Subscribe, User)


class DetailManager:
    INIT_PREFIX = "rss-init:"
    SKIP_PREFIX = "rss-skip:"
    ROLLOUT_ID = "rss-init:rollout-v1"

    @staticmethod
    def _subscription_scope(user_id: str, group_id: str) -> str:
        key = json.dumps([str(user_id), str(group_id)], ensure_ascii=False)
        return hashlib.sha256(key.encode()).hexdigest()

    @classmethod
    def initialization_id(cls, user_id: str, group_id: str) -> str:
        return cls.INIT_PREFIX + cls._subscription_scope(user_id, group_id)

    @classmethod
    def skip_id(cls, user_id: str, group_id: str, article_id: str) -> str:
        return f"{cls.SKIP_PREFIX}{cls._subscription_scope(user_id, group_id)}:{article_id}"

    @classmethod
    async def last_successful_delivery_at(cls, session, group_id: str) -> datetime | None:
        """只统计该群真实送达的记录，不把初始化或静默记录作为成功推送。"""
        return await session.scalar(select(func.max(Detail.updated)).where(
            Detail.id.endswith(f"-{group_id}", autoescape=True),
            ~Detail.id.startswith(cls.INIT_PREFIX),
            ~Detail.id.startswith(cls.SKIP_PREFIX),
        ))

    @classmethod
    async def bootstrap_legacy_subscriptions(cls, session, pairs, silent_groups=None) -> None:
        """持久保存本次启动需静默的订阅，并一次性兼容已有订阅。"""
        silent_groups = silent_groups or set()
        rollout = await session.get(Detail, cls.ROLLOUT_ID)
        if rollout and not silent_groups:
            return
        legacy = None if rollout else await session.scalar(select(Detail.id).where(
            ~Detail.id.startswith(cls.INIT_PREFIX),
            ~Detail.id.startswith(cls.SKIP_PREFIX),
        ).limit(1))
        for user_id, group_id in pairs:
            silent = group_id in silent_groups
            if not silent and not legacy:
                continue
            key = cls.initialization_id(user_id, group_id)
            marker = await session.get(Detail, key)
            if marker:
                if silent:
                    marker.summary = "pending"
            else:
                state = "pending" if silent else "initialized"
                session.add(Detail(id=key, summary=state, updated=None))
        if not rollout:
            session.add(Detail(id=cls.ROLLOUT_ID, summary="rollout", updated=None))
        await session.commit()

    @classmethod
    async def initialize_subscription(cls, session, user_id, group_id, entries, push_limit=1):
        """每轮静默登记窗口外文章；待处理的启动基线始终覆盖全部文章。"""
        key = cls.initialization_id(user_id, group_id)
        marker = await session.get(Detail, key)
        if marker and marker.summary == "pending":
            seeds = entries
        else:
            seeds = entries[push_limit:] if push_limit else []
        ids = [record_id for _, article_id in seeds for record_id in (
            f"{article_id}-{group_id}", cls.skip_id(user_id, group_id, article_id),
        )]
        existing = await cls.get_existing_ids(session, ids)
        for entry, article_id in seeds:
            delivered_id = f"{article_id}-{group_id}"
            skipped_id = cls.skip_id(user_id, group_id, article_id)
            if delivered_id not in existing and skipped_id not in existing:
                session.add(Detail(id=skipped_id, summary=entry.get("title"), updated=None))
                existing.add(skipped_id)
        if marker:
            marker.summary = "initialized"
        else:
            session.add(Detail(id=key, summary="initialized", updated=None))
        # 标记和本轮静默记录原子提交；已送达记录及其时间戳保持不变。
        await session.commit()

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

    @classmethod
    async def count_recent(cls, session: async_scoped_session, hours: int = 24) -> int:
        """统计最近N小时内的记录数"""
        since = datetime.now() - timedelta(hours=hours)
        result = await session.execute(
            select(func.count()).where(Detail.updated >= since)
        )
        return result.scalar() or 0


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

    @classmethod
    async def delete_by_group(cls, session: async_scoped_session, group_id: str) -> int:
        """删除指定群组的所有订阅"""
        result = await session.execute(delete(Subscribe).where(Subscribe.group == group_id))
        await session.commit()
        return result.rowcount or 0


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
    async def get_all_platforms(cls, session: async_scoped_session) -> list[Plantform]:
        result = await session.execute(select(Plantform).order_by(Plantform.name))
        return list(result.scalars().all())

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
            referenced = select(User.User_ID).where(User.Plantform == id).exists()
            result = await session.execute(
                delete(Plantform).where(Plantform.name == id, ~referenced)
                .execution_options(synchronize_session=False)
            )
            if not result.rowcount:
                raise ValueError("该平台仍有用户引用，请先删除这些用户或修改其平台，不能直接删除。")
            await session.commit()
            return True
        return False

    @classmethod
    async def update_config(
        cls, session: async_scoped_session, name: str, url: str, need_trans: str,
    ) -> None:
        platform = await cls.get_Sign_by_student_id(session, name)
        if platform is None:
            raise ValueError(f"平台「{name}」不存在。")
        platform.url = url
        platform.need_trans = need_trans
        await session.commit()

    @classmethod
    async def create_signmsg(cls, session: async_scoped_session, **kwargs) -> Plantform:
        """创建新的数据"""
        new_signmsg = Plantform(**kwargs)
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
    @staticmethod
    def _validate_push_limit(value: object) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5:
            raise ValueError("推送数量必须是 0–5 的整数。")

    @classmethod
    async def get_all_group_id(cls, session: async_scoped_session) -> set:
        """获取数据库中所有 student_id"""
        result = await session.execute(select(Groupconfig.group_id))
        return {row[0] for row in result}

    @classmethod
    async def get_Sign_by_group_id(cls, session: async_scoped_session, student_id: str) -> Optional[Groupconfig]:
        """根据 student_id 获取单个信息"""
        return await session.get(Groupconfig, student_id)

    @classmethod
    async def get_all_configs(cls, session: async_scoped_session) -> dict[str, Groupconfig]:
        """获取所有群组配置"""
        result = await session.execute(select(Groupconfig))
        return {gc.group_id: gc for gc in result.scalars().all()}

    @staticmethod
    async def is_database_empty(db_session):
        # 查询数据库，判断是否有数据
        result = await db_session.execute(text("SELECT 1 FROM Group_config LIMIT 1"))
        return not result.fetchone()

    @classmethod
    async def create_signmsg(cls, session: async_scoped_session, **kwargs: object) -> Groupconfig:
        """创建新的数据"""
        if "push_limit" in kwargs:
            cls._validate_push_limit(kwargs["push_limit"])
        new_signmsg = Groupconfig(**kwargs)
        session.add(new_signmsg)
        await session.commit()
        return new_signmsg

    @classmethod
    async def delete_id(cls, session: async_scoped_session, id: str) -> bool:
        """删除数据"""
        lanmsg = await cls.get_Sign_by_group_id(session, id)
        if lanmsg:
            await session.delete(lanmsg)
            await session.commit()
            return True
        return False

    @classmethod
    async def update_config(cls, session: async_scoped_session, group_id: str, **kwargs) -> bool:
        """更新群组配置"""
        if "push_limit" in kwargs:
            cls._validate_push_limit(kwargs["push_limit"])
        config_obj = await cls.get_Sign_by_group_id(session, group_id)
        if config_obj:
            for key, value in kwargs.items():
                setattr(config_obj, key, value)
            await session.commit()
            return True
        return False
