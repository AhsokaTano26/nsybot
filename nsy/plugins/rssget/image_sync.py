"""只读图片增量接口：仅查询已缓存数据，不触发抓取或 QQ 推送。"""

import ast
import secrets
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Response
from nonebot import get_app, get_plugin_config
from nonebot_plugin_orm import get_session
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.engine import Row

from .config import Config
from .models import Content, ImageSync

config = get_plugin_config(Config)
router = APIRouter(prefix="/internal/v1", include_in_schema=False)


class ImageItem(BaseModel):
    seq: str
    id: str
    tweet_id: str | None
    author: str | None
    author_handle: str | None
    published_at: str | None
    published_at_raw: str | None
    link: str | None
    images: list[str]


class ImagePage(BaseModel):
    items: list[ImageItem]
    next_cursor: str
    has_more: bool


def require_sync_token(authorization: str | None = Header(default=None)) -> None:
    if not config.rss_image_sync_enabled:
        raise HTTPException(status_code=404, detail="Not Found")
    token = config.rss_image_sync_token
    if token is None or not token.get_secret_value().strip():
        raise HTTPException(status_code=503, detail="Image sync is not configured")
    scheme, _, credentials = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        credentials.encode(), token.get_secret_value().encode(),
    ):
        raise HTTPException(status_code=401, detail="Invalid bearer token", headers={"WWW-Authenticate": "Bearer"})


def image_item(seq: int, content: Content | Row) -> ImageItem:
    tweet_id = handle = published_at = None
    try:
        url = urlsplit(content.link or "")
        parts = url.path.strip("/").split("/")
        if url.hostname in {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}:
            if len(parts) >= 3 and parts[1] == "status" and parts[2].isascii() and parts[2].isdigit():
                handle, tweet_id = parts[0], parts[2]
    except ValueError:
        pass
    try:
        date = datetime.strptime(content.time, "%Y-%m-%d %H:%M")
        published_at = date.replace(tzinfo=ZoneInfo("Asia/Shanghai")).isoformat()
    except (TypeError, ValueError):
        pass
    images = ast.literal_eval(content.images)
    if not isinstance(images, list) or not all(isinstance(url, str) for url in images):
        raise ValueError("文章缓存的图片列表格式无效")
    return ImageItem(
        seq=str(seq), id=content.id, tweet_id=tweet_id, author=content.username,
        author_handle=handle, published_at=published_at, published_at_raw=content.time,
        link=content.link, images=list(dict.fromkeys(images)),
    )


@router.get("/images", response_model=ImagePage, dependencies=[Depends(require_sync_token)])
async def list_images(
    response: Response,
    cursor: str = Query(default="0", pattern=r"^(0|[1-9][0-9]{0,18})$"),
    limit: int = Query(default=100, ge=1, le=200),
) -> ImagePage:
    after = int(cursor)
    if after > 9223372036854775807:
        raise HTTPException(status_code=422, detail="Cursor is out of range")
    async with get_session() as session:
        rows = (await session.execute(
            select(ImageSync.seq, Content.id, Content.username, Content.time, Content.link, Content.images)
            .join(Content, Content.id == ImageSync.content_id)
            .where(ImageSync.seq > after).order_by(ImageSync.seq).limit(limit + 1)
        )).all()
    items = [image_item(row.seq, row) for row in rows[:limit]]
    response.headers["Cache-Control"] = "no-store"
    return ImagePage(items=items, next_cursor=items[-1].seq if items else cursor, has_more=len(rows) > limit)


def register_image_sync_api() -> None:
    app = get_app()
    if not isinstance(app, FastAPI):
        if config.rss_image_sync_enabled:
            raise RuntimeError("图片同步 API 需要 NoneBot FastAPI 驱动")
        return
    app.include_router(router)
