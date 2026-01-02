from nonebot import logger

from .encrypt import encrypt, sha256

async def get_id(entry):
    unique_id_source = str(entry.guid)
    trueid = await encrypt(unique_id_source)
    logger.info(f"已获取id:{trueid}")
    return trueid