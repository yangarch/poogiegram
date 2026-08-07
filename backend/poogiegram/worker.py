"""arq 워커 진입점.

    arq poogiegram.worker.WorkerSettings

M0 에서는 기동과 헬스체크만 확인한다. 인제스트 파이프라인은 M1 (§6.1).
"""

from __future__ import annotations

import logging

from arq.connections import RedisSettings

from .config import get_settings
from .storage import ensure_runtime_dirs, verify_storage

log = logging.getLogger("poogiegram.worker")


async def ping(ctx) -> str:
    """연결 확인용 더미 작업."""
    return "pong"


async def startup(ctx) -> None:
    settings = get_settings()
    # API 와 동일하게 마운트를 먼저 확인한다 (§4.6).
    # 워커가 빈 마운트 포인트에 파생물을 쓰기 시작하면 더 조용히 망가진다.
    verify_storage(settings)
    ensure_runtime_dirs(settings)
    ctx["settings"] = settings
    log.info(
        "워커 기동 — hwaccel=%s concurrency=%d max_height=%d",
        settings.transcode_hwaccel,
        settings.transcode_concurrency,
        settings.transcode_max_height,
    )


async def shutdown(ctx) -> None:
    log.info("워커 종료")


class WorkerSettings:
    functions = [ping]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # GPU 인코드 엔진이 하나뿐이라 무한정 늘려도 의미가 없다 (§6.3).
    max_jobs = get_settings().transcode_concurrency
