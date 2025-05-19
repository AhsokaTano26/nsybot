from bs4 import BeautifulSoup
from nonebot import logger

from .encrypt import encrypt, sha256

async def get_id(entry):
    dic = {}
    clean_text = BeautifulSoup(entry.description, "html.parser").get_text("\n").strip()
    dic["title"] = entry.title
    dic["text"] = clean_text
    id = dic["title"] + "-" + dic["text"]
    trueid = await encrypt(id)
    logger.info(f"已获取id:{trueid}")
    return trueid