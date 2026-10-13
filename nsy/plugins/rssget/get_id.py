from nonebot import logger
import json

from .encrypt import encrypt, sha256

async def get_id(entry):
    if not isinstance(entry, dict):
        raise ValueError("RSS 条目不是有效对象")
    unique_id_source = entry.get("guid") or entry.get("id") or entry.get("link")
    if not unique_id_source:
        values = [entry.get(key) for key in ("title", "description", "summary", "published", "updated")]
        if not any(values):
            raise ValueError("RSS 条目缺少可识别的内容")
        unique_id_source = json.dumps(values, ensure_ascii=False, default=str)
    unique_id_source = str(unique_id_source)
    trueid = await encrypt(unique_id_source)
    logger.info(f"已获取id:{trueid}")
    return trueid
