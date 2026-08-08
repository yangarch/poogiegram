"""arq 워커 진입점.

    arq poogiegram.worker.WorkerSettings

M1-2 현재: 드롭 폴더를 주기적으로 훑어 처리 가능한 파일을 찾아낸다.
실제 인제스트(해시·EXIF·배치)는 M1-3 에서 붙인다.
"""

from __future__ import annotations

import asyncio
import logging

from arq.connections import RedisSettings

from . import logs
from .config import get_settings
from .db import make_engine, make_sessionmaker
from .ingest.pipeline import ingest_one
from .ingest.scanner import scan
from .storage import ensure_runtime_dirs, verify_storage

log = logging.getLogger("poogiegram.worker")

# 주기 스캔과 수동 트리거가 겹쳐 같은 파일을 두 번 집는 것을 막는다.
_SCAN_LOCK = "ingest:scan:lock"


async def scan_drop_folder(ctx) -> dict:
    """드롭 폴더를 한 번 훑는다. 주기 루프와 수동 트리거가 같은 함수를 쓴다."""
    redis = ctx["redis"]
    settings = ctx["settings"]

    # 락은 짧게 잡는다. 스캔이 죽어도 다음 사이클이 막히지 않아야 한다.
    if not await redis.set(_SCAN_LOCK, "1", ex=120, nx=True):
        log.debug("스캔이 이미 진행 중이라 건너뜀")
        return {"skipped": True}

    try:
        ready, waiting = await scan(settings, redis)
        if ready or waiting:
            log.info("스캔: 처리가능 %d, 대기 %d", len(ready), len(waiting))
        for c in ready:
            await redis.enqueue_job("ingest_file", str(c.path))
        for c in waiting:
            log.debug("  대기(안정성 미충족): %s", c.path.name)
        return {"ready": len(ready), "waiting": len(waiting)}
    finally:
        await redis.delete(_SCAN_LOCK)


async def ingest_file(ctx, path_str: str) -> dict:
    """파일 하나를 인제스트한다 (§6.1).

    파일 단위 작업으로 두는 이유는 **실패 격리**다. 500장 중 한 장이 깨져 있어도
    나머지는 정상 처리되고, 깨진 것만 failed/ 로 간다.
    """
    from pathlib import Path

    path = Path(path_str)
    if not path.exists():
        # 이전 사이클에서 이미 처리됐다. 스캔과 큐 사이의 정상적인 경합이다.
        return {"skipped": "이미 처리됨"}

    result = await ingest_one(ctx["sessionmaker"], ctx["settings"], path)
    log.info("%s: %s %s", path.name, result.event, result.detail)
    return {"event": result.event, "asset_id": result.asset_id}


async def _wait_for_schema(ctx) -> None:
    """마이그레이션이 적용될 때까지 기다린다.

    신규 설치에서는 컨테이너가 먼저 뜨고 마이그레이션이 나중에 돈다. 그 사이에
    스캔이 돌면 인제스트가 "relation does not exist" 로 실패하는데, 그 상태로
    **drop/ 에 있던 파일이 전부 failed/ 로 격리된다.**
    """
    from sqlalchemy import text

    delay = 2
    while True:
        try:
            async with ctx["sessionmaker"]() as session:
                await session.scalar(text("SELECT version_num FROM alembic_version"))
            return
        except Exception:  # noqa: BLE001
            log.info("스키마 대기 중... (%d초 후 재시도)", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


async def _scan_loop(ctx) -> None:
    """주기 스캔.

    inotify 를 쓰지 않고 주기 스캔을 기준으로 삼는다 — 수백 장을 한꺼번에 넣으면
    inotify 이벤트 큐가 넘쳐 일부를 조용히 놓치는데, 오류도 로그도 남지 않는다.
    스캔은 놓치는 것이 없고, 최대 한 사이클만 늦어질 뿐이다 (§6.1).
    """
    await _wait_for_schema(ctx)
    interval = ctx["settings"].ingest_scan_interval_seconds
    log.info("주기 스캔 시작 — %d초 간격", interval)
    while True:
        try:
            await scan_drop_folder(ctx)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 한 번 실패해도 루프는 계속 돌아야 한다
            log.exception("스캔 실패")
        await asyncio.sleep(interval)


async def startup(ctx) -> None:
    logs.setup()
    settings = get_settings()
    # API 와 동일하게 마운트를 먼저 확인한다 (§4.6).
    # 워커가 빈 마운트 포인트에 파생물을 쓰기 시작하면 더 조용히 망가진다.
    verify_storage(settings)
    ensure_runtime_dirs(settings)
    ctx["settings"] = settings
    ctx["engine"] = make_engine(settings.database_url)
    ctx["sessionmaker"] = make_sessionmaker(ctx["engine"])
    ctx["scan_task"] = asyncio.create_task(_scan_loop(ctx))
    log.info(
        "워커 기동 — hwaccel=%s concurrency=%d max_height=%d",
        settings.transcode_hwaccel,
        settings.transcode_concurrency,
        settings.transcode_max_height,
    )


async def shutdown(ctx) -> None:
    task = ctx.get("scan_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if engine := ctx.get("engine"):
        await engine.dispose()
    log.info("워커 종료")


class WorkerSettings:
    functions = [scan_drop_folder, ingest_file]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # GPU 인코드 엔진이 하나뿐이라 무한정 늘려도 의미가 없다 (§6.3).
    max_jobs = get_settings().transcode_concurrency
