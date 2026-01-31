import asyncio
import json

from twikit import Client

AUTH_TOKEN = "db3d6525f4418cdc7f5183a494dca5d8a505fcd3"
CT0 = "d299c4f1cc0764db832b8f7b39335fd6206c24c41831519a746a7d2f6dc19ea6a1cf2b3883c8fb15cb66c47b17823b1f4a64485404dafdfd8668f4936923e332f26aa56c4713b4a3c3d1798f2f9ae08c"

TARGET_USER = "tongguniang"


async def main():
    client = Client("en-US")
    client.set_cookies({"auth_token": AUTH_TOKEN, "ct0": CT0})

    # 获取用户信息
    print("=" * 50)
    print("Step 1: 获取用户信息")
    print("=" * 50)
    user = await client.get_user_by_screen_name(TARGET_USER)
    print(f"用户名: {user.screen_name}")
    print(f"用户ID: {user.id}")
    print(f"关注数: {user.following_count}")

    # 第一页
    print("\n" + "=" * 50)
    print("Step 2: 获取第一页关注列表 (count=20)")
    print("=" * 50)

    following = await client.get_user_following(user.id, count=20)

    print(f"获取到 {len(following)} 个用户:")
    for i, u in enumerate(following, 1):
        print(f"  [{i}] {u.screen_name}")

    print(f"\nnext_cursor: {following.next_cursor}")
    print(f"previous_cursor: {following.previous_cursor if hasattr(following, 'previous_cursor') else 'N/A'}")

    # 尝试获取第二页
    if following.next_cursor:
        print("\n" + "=" * 50)
        print("Step 3: 获取第二页关注列表")
        print("=" * 50)

        try:
            more = await following.next()
            print(f"获取到 {len(more)} 个用户:")
            for i, u in enumerate(more, 1):
                print(f"  [{i}] {u.screen_name}")

            print(f"\nnext_cursor: {more.next_cursor}")

        except Exception as e:
            print(f"\n❌ 获取第二页失败!")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误信息: {e}")

            # 尝试打印更多调试信息
            if hasattr(e, '__dict__'):
                print(f"错误属性: {e.__dict__}")

            # 如果有 response 属性
            if hasattr(e, 'response'):
                print(f"响应状态: {e.response.status_code if hasattr(e.response, 'status_code') else 'N/A'}")
                print(f"响应内容: {e.response.text if hasattr(e.response, 'text') else 'N/A'}")
    else:
        print("\n没有更多分页数据")

    print("\n" + "=" * 50)
    print("测试完成")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
