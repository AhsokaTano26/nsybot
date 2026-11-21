"""Production Gunicorn worker probe, synthetic SQLite + mocked remote services only.

Run as APP_MODULE=tests.container_memory_probe:app with the Docker limits and
environment documented in docs/performance.md. No production database or keys.
"""

import asyncio
import base64
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import platform
import time
from unittest.mock import patch

import httpx
import nonebot
from sqlalchemy import func, select, update
from datetime import datetime, timezone

from docker._main import app
from nsy import qq_utils
from nsy.plugins import rssget as rss
from nsy.plugins.rssget import functions, models
from nsy.plugins.rssget.ingest_queue import IngestQueueManager
from nsy.plugins.rssget.state_machines import WriteOutcome
from nonebot_plugin_orm import get_session

cache = importlib.import_module('nsy.plugins.rssget.update_text')
api = importlib.import_module('nsy.plugins.rssget.image_sync')

jobs = rss.scheduler.get_jobs()
assert next(j for j in jobs if j.func == rss.auto_update_func).trigger.interval.total_seconds() == 1200
# Trigger cycles ourselves without waiting 20 min or connecting to any service.
rss.scheduler.remove_all_jobs()

PHASE = 0
SENDS = 0
CGROUP = Path('/sys/fs/cgroup')
REPORT = {'python_sqlite': sqlite3.sqlite_version, 'python': sys.version.split()[0],
          'architecture': platform.machine(), 'interval_seconds': 1200, 'cases': []}


def sample(label, started=None):
    row = {'case': label, 'current_bytes': int((CGROUP / 'memory.current').read_text()),
           'peak_bytes': int((CGROUP / 'memory.peak').read_text())}
    stats = dict(line.split() for line in (CGROUP / 'memory.stat').read_text().splitlines())
    row.update(anon_bytes=int(stats['anon']), file_bytes=int(stats['file']))
    if started is not None:
        row['seconds'] = round(time.monotonic() - started, 4)
    REPORT['cases'].append(row)
    print('MEMORY_CASE ' + json.dumps(row), flush=True)


def xml(account, posts=20, body_bytes=8192, dense=False):
    unit = '<p><a href="https://fixture.invalid">source</a><b>text</b></p>' if dense else 'source text '
    body = '<p>' + unit * (body_bytes // len(unit)) + '</p>'
    body += '<img src="https://fixture.invalid/image.png">'
    items = ''.join(
        f'<item><guid>{account}-{PHASE}-{i}</guid><title>Fixture</title>'
        f'<link>https://x.com/{account}/status/{PHASE * 100000 + i + 1}</link>'
        '<pubDate>Tue, 13 Oct 2026 12:00:00 GMT</pubDate>'
        f'<description><![CDATA[{body}]]></description></item>' for i in range(posts))
    return f'<rss version="2.0"><channel><title>{account}</title>{items}</channel></rss>'.encode()


class ImageStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        for _ in range(160):
            yield b'x' * 65536
            await asyncio.sleep(0)


def remote(request):
    if request.url.path.endswith('image.png'):
        return httpx.Response(200, headers={'Content-Type': 'image/png'}, stream=ImageStream())
    return httpx.Response(200, content=xml(request.url.path.rsplit('/', 1)[-1]))


class Bot:
    self_id = 'memory-fixture'

    async def send_to_group(self, *, message, **kwargs):
        global SENDS
        SENDS += 1
        if message.type == 'file_image':
            # Same base64/string pressure as official QQ file upload; no network.
            encoded = base64.b64encode(message.data['content']).decode()
            await asyncio.sleep(.001)
            assert len(encoded) > 0
        return {'id': str(SENDS)}


async def count(model):
    async with get_session() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def probe():
    global PHASE
    try:
        sample('startup_after_migrations')
        async with get_session() as session, session.begin():
            session.add(models.Plantform(name='Twitter', url='twitter/user/', need_trans='0'))
            for index in range(20):
                uid = f'fixture{index}'
                session.add(models.User(User_ID=uid, User_Name=uid, Plantform='Twitter'))
                for group in ('g1', 'g2'):
                    session.add(models.Subscribe(id=f'{uid}-{group}', username=uid, group=group))
            for group in ('g1', 'g2'):
                session.add(models.Groupconfig(group_id=group, if_need_trans=True, if_need_self_trans=True,
                    if_need_translate=False, if_need_photo_num_mention=False, if_need_merged_message=False, push_limit=1))
        bot = Bot()
        cfg = functions.config.model_copy(update={'rsshub_host': 'https://fixture.invalid', 'rsshub_host_back': []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
            with patch.object(functions, 'config', cfg), patch.object(rss, 'config', cfg), patch.object(
                functions.NetworkManager, 'get_client', return_value=client,
            ), patch.object(functions, 'get_bot', return_value=bot), patch.object(rss, 'get_bot', return_value=bot), patch.object(
                qq_utils, 'active_message_limiter', qq_utils.ActiveMessageLimiter(0, 0),
            ), patch.object(functions.random, 'uniform', return_value=0):
                for phase in range(3):
                    PHASE = min(phase, 1)
                    started = time.monotonic()
                    await rss.collect_articles()
                    await rss.push_cached_articles()
                    # Bounded batches can defer work to the durable retry tick.
                    for _ in range(10):
                        if not await count(models.RSSIngestQueue):
                            break
                        await cache.retry_pending_entries()
                    sample(f'cycle_{phase}_collect_and_push', started)
                assert await count(models.Content) == 800
                assert await count(models.ImageSync) == 800
                assert await count(models.RSSIngestQueue) == 0

                async def pages():
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://internal') as api_client:
                        for _ in range(5):
                            result = await api_client.get('/internal/v1/images?limit=200', headers={'Authorization': 'Bearer memory-test-token'})
                            assert result.status_code == 200, result.text
                            assert len(result.json()['items']) == 200

                # Import and construct optional clients, without external I/O.
                from nsy.plugins.rssget.following_import import FollowingFetcher
                from nsy.plugins.rssget.translation import Ali, AsyncOpenAI
                follower = FollowingFetcher('fixture-auth', 'fixture-csrf')
                ali = Ali.create_client()
                openai_client = AsyncOpenAI(api_key='memory-test-key')
                sample('optional_sdks_first_use')

                started = time.monotonic()
                await asyncio.gather(pages(), pages(), *(functions.rss_get().send_qq_image('https://fixture.invalid/image.png', 'g1') for _ in range(3)))
                await openai_client.close()
                await follower.client.http.aclose()
                sample('concurrent_api_and_10MiB_images', started)

                # A near-budget dense feed, and explicitly rejected oversized data.
                from nsy.plugins.rssget.format_json import Format
                import feedparser
                heavy = xml('heavy', posts=20, body_bytes=120 * 1024, dense=True)
                parsed = feedparser.parse(heavy)
                await asyncio.gather(pages(), *(Format().extract_content(entry, 0) for entry in parsed.entries))
                sample('dense_2_5MiB_feed')
                del heavy, parsed

                # Force a durable database failure and recover 100 queued entries.
                entries = [({'summary': '<p>' + 'work ' * 3200 + '</p>', 'id': f'retry{i}'}, f'retry{i}') for i in range(100)]
                async with get_session() as session, session.begin():
                    await IngestQueueManager.stage(session, entries, 'fixture')
                del entries
                async def failed_write(*args, **kwargs):
                    return WriteOutcome.RETRY_PENDING
                with patch.object(cache, 'write_content', failed_write):
                    await cache.retry_pending_entries()
                assert await count(models.RSSIngestQueue) == 100
                async with get_session() as session, session.begin():
                    await session.execute(update(models.RSSIngestQueue).values(next_retry_at=datetime(2026, 1, 1)))
                for _ in range(10):
                    await cache.retry_pending_entries()
                    if not await count(models.RSSIngestQueue):
                        break
                assert await count(models.RSSIngestQueue) == 0
                sample('100_failed_entries_recovered')

                started = time.monotonic()
                for _ in range(10):
                    await rss.collect_articles()
                    await rss.push_cached_articles()
                sample('10_unchanged_cycles', started)
                started = time.monotonic()
                await asyncio.gather(pages(), pages(), *(functions.rss_get().send_qq_image('https://fixture.invalid/image.png', 'g1') for _ in range(3)))
                sample('post_warm_api_and_10MiB_images', started)
                entry = {'summary': 'x' * (300 * 1024), 'link': 'https://x.com/fixture/status/9999999'}
                async with get_session() as session, session.begin():
                    await IngestQueueManager.stage(session, [(entry, 'oversized')], 'fixture')
                await cache.retry_pending_entries()
                async with get_session() as session:
                    queued = await session.get(models.RSSIngestQueue, 'oversized')
                    assert queued is not None and queued.last_error == 'EntryTooLarge'
                sample('oversized_entry_retained')
        REPORT.update(ok=True, sends=SENDS, content=await count(models.Content), indexed=await count(models.ImageSync))
    except BaseException as exc:
        import traceback
        traceback.print_exc()
        REPORT.update(ok=False, error=repr(exc))
    REPORT['events'] = (CGROUP / 'memory.events').read_text()
    REPORT['limit_bytes'] = int((CGROUP / 'memory.max').read_text())
    REPORT['peak_bytes'] = int((CGROUP / 'memory.peak').read_text())
    REPORT['image_tag'] = 'nsybot-memory-300m:local'
    Path('/tmp/memory-report.json').write_text(json.dumps(REPORT, ensure_ascii=False, indent=2))
    print('MEMORY_REPORT ' + json.dumps(REPORT), flush=True)


@nonebot.get_driver().on_startup
async def start_probe():
    asyncio.create_task(probe())
