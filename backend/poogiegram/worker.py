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
            # M1-3 에서 여기서 인제스트 작업을 큐에 넣는다.
            log.info("  처리 대상: %s (%.1fMB)", c.path.name, c.size / 1e6)
        for c in waiting:
            log.debug("  대기(안정성 미충족): %s", c.path.name)
        return {"ready": len(ready), "waiting": len(waiting)}
    finally:
        await redis.delete(_SCAN_LOCK)


async def _scan_loop(ctx) -> None:
    """주기 스캔.

    inotify 를 쓰지 않고 주기 스캔을 기준으로 삼는다 — 수백 장을 한꺼번에 넣으면
    inotify 이벤트 큐가 넘쳐 일부를 조용히 놓치는데, 오류도 로그도 남지 않는다.
    스캔은 놓치는 것이 없고, 최대 한 사이클만 늦어질 뿐이다 (§6.1).
    """
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
    log.info("워커 종료")


class WorkerSettings:
    functions = [scan_drop_folder]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # GPU 인코드 엔진이 하나뿐이라 무한정 늘려도 의미가 없다 (§6.3).
    max_jobs = get_settings().transcode_concurrency
