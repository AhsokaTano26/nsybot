"""
X (Twitter) Following List Import Module

用于获取用户的 X 关注列表，并与数据库中的可订阅用户取交集
"""

from typing import Optional

from loguru import logger

try:
    from twikit import Client
    TWIKIT_AVAILABLE = True
except ImportError:
    TWIKIT_AVAILABLE = False
    logger.warning("twikit not installed, following import feature disabled")


class FollowingFetcher:
    """获取 X 关注列表"""

    def __init__(self, auth_token: str, ct0: str):
        """
        初始化 FollowingFetcher

        Args:
            auth_token: X 的 auth_token cookie
            ct0: X 的 ct0 cookie
        """
        if not TWIKIT_AVAILABLE:
            raise RuntimeError("twikit library not installed")

        self.client = Client("en-US")
        self.client.set_cookies({"auth_token": auth_token, "ct0": ct0})

    async def get_following_list(
        self,
        screen_name: str,
        max_count: Optional[int] = None
    ) -> tuple[list[str], int]:
        """
        获取指定用户的关注列表

        Args:
            screen_name: X 用户名 (不带@)
            max_count: 最大获取数量，None 表示获取全部

        Returns:
            tuple: (关注的用户名列表, 总关注数)
        """
        import asyncio

        user = await self.client.get_user_by_screen_name(screen_name)
        total_following = user.following_count
        logger.info(f"User {screen_name} has {total_following} following")

        following_names = []

        # 获取第一批关注 (每次100个，提高效率)
        following = await self.client.get_user_following(user.id, count=100)
        for u in following:
            following_names.append(u.screen_name.lower())
            if max_count and len(following_names) >= max_count:
                return following_names, total_following

        # 继续获取更多，自适应延迟 - （可能有用，傻逼twitter）
        page = 1
        delay = 0.15  # 初始延迟 150ms
        min_delay = 0.1  # 最小延迟 100ms
        max_delay = 2.0  # 最大延迟 2s
        consecutive_success = 0

        while following.next_cursor:
            if max_count and len(following_names) >= max_count:
                break

            await asyncio.sleep(delay)

            try:
                following = await following.next()
                page += 1
                for u in following:
                    following_names.append(u.screen_name.lower())
                    if max_count and len(following_names) >= max_count:
                        break

                # 成功后逐步减少延迟
                consecutive_success += 1
                if consecutive_success >= 3:
                    delay = max(min_delay, delay * 0.8)
                    consecutive_success = 0

                logger.debug(f"Page {page}: {len(following_names)} users (delay={delay:.2f}s)")

            except Exception as e:
                # 失败时增加延迟并重试一次
                consecutive_success = 0
                delay = min(max_delay, delay * 2)
                logger.warning(f"Page {page} failed, retrying with delay={delay:.2f}s: {e}")

                await asyncio.sleep(delay)
                try:
                    following = await following.next()
                    page += 1
                    for u in following:
                        following_names.append(u.screen_name.lower())
                except Exception as retry_e:
                    logger.warning(f"Retry failed at page {page}: {retry_e}")
                    logger.info(f"Returning {len(following_names)} users fetched so far")
                    break

        logger.success(f"Fetched {len(following_names)} following for {screen_name}")
        return following_names, total_following


async def fetch_and_match(
    auth_token: str,
    ct0: str,
    screen_name: str,
    available_users: set[str],
    max_fetch: Optional[int] = None
) -> tuple[list[str], int, int]:
    """
    获取关注列表并与可用用户匹配

    Args:
        auth_token: X auth_token
        ct0: X ct0 cookie
        screen_name: 要查询的 X 用户名
        available_users: 数据库中可订阅的用户ID集合 (小写)
        max_fetch: 最大获取数量

    Returns:
        tuple: (匹配的用户ID列表, 获取的关注总数, 用户的关注总数)
    """
    fetcher = FollowingFetcher(auth_token, ct0)
    following_list, total_count = await fetcher.get_following_list(screen_name, max_fetch)

    # 转换为小写进行匹配
    available_lower = {u.lower() for u in available_users}

    # 取交集
    matched = [u for u in following_list if u in available_lower]

    # 返回原始大小写的用户ID
    available_map = {u.lower(): u for u in available_users}
    matched_original = [available_map[m] for m in matched]

    logger.info(f"Matched {len(matched_original)} users from {len(following_list)} following")

    return matched_original, len(following_list), total_count
