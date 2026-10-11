"""RSS 平台管理命令的参数校验与数据库操作。"""

from urllib.parse import urlsplit

from .models_method import PlantformManager


PLATFORM_USAGES = {
    "增加平台": "增加平台 <平台名> <RSSHub路由前缀> <翻译0/1>",
    "修改平台": "修改平台 <平台名> <RSSHub路由前缀> <翻译0/1>",
    "删除平台": "删除平台 <平台名>",
    "平台列表": "平台列表",
}


async def execute_platform_command(session, command: str, text: str) -> str:
    args = text.split()
    expected = {"增加平台": 3, "修改平台": 3, "删除平台": 1, "平台列表": 0}
    if command not in expected:
        raise ValueError("未知平台管理命令。")
    if len(args) != expected[command]:
        raise ValueError(f"用法：{PLATFORM_USAGES[command]}")

    if command == "平台列表":
        platforms = await PlantformManager.get_all_platforms(session)
        return "\n\n".join(
            f"- 平台：`{platform.name}`\n"
            f"  路由前缀：`{platform.url}`\n"
            f"  翻译：{'开' if platform.need_trans == '1' else '关'}"
            for platform in platforms
        ) or "暂无平台。请使用「增加平台 <平台名> <RSSHub路由前缀> <翻译0/1>」。"

    name = args[0]
    if len(name) > 255:
        raise ValueError("平台名最长 255 个字符。")
    if command in ("增加平台", "修改平台"):
        url, need_trans = args[1:]
        if need_trans not in ("0", "1"):
            raise ValueError("翻译参数只能填写 0（关）或 1（开）。")
        if (
            len(url) > 255 or not url.startswith("/")
            or urlsplit(url).netloc or "#" in url or "\\" in url
        ):
            raise ValueError(
                "路由前缀须以 / 开头，最长 255 个字符，不含域名、片段或反斜杠；"
                "例如 /twitter/user/。实际地址由 RSSHUB_HOST + 路由前缀 + 用户ID 拼接。"
            )

    platform = await PlantformManager.get_Sign_by_student_id(session, name)
    if command == "增加平台":
        if platform is not None:
            raise ValueError(f"平台「{name}」已存在，请使用「修改平台」。")
        await PlantformManager.create_signmsg(session, name=name, url=url, need_trans=need_trans)
        return f"已增加平台「{name}」。\n路由前缀：`{url}`\n翻译：{'开' if need_trans == '1' else '关'}"

    if platform is None:
        raise ValueError(f"平台「{name}」不存在，请先使用「增加平台」。")
    if command == "修改平台":
        await PlantformManager.update_config(session, name, url, need_trans)
        return f"已修改平台「{name}」。\n路由前缀：`{url}`\n翻译：{'开' if need_trans == '1' else '关'}"

    await PlantformManager.delete_id(session, name)
    return f"已删除平台「{name}」。"
