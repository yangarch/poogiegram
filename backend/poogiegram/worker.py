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
from .ingest.derive import DeriveError, generate
from .ingest.pipeline import ingest_one
from .ingest.scanner import scan
from .storage import ensure_runtime_dirs, verify_storage

log = logging.getLogger("poogiegram.worker")

# 주기 스캔과 수동 트리거가 겹쳐 같은 파일을 두 번 집는 것을 막는다.
_SCAN_LOCK = "ingest:scan:lock"


async def _requeue_pending_derives(ctx) -> int:
    """파생물이 아직 없는 자산을 다시 큐에 넣는다.

    파생물 작업은 인제스트 시점에 한 번 큐잉되는데, 그 사이 워커가 죽거나 작업이
    유실되면 자산이 pending 인 채로 영원히 남는다. HEIC 는 파생물이 없으면
    **화면에 아무것도 안 보이므로** 조용히 방치되면 안 된다.

    job_id 를 자산 ID 로 고정해 중복 큐잉을 막는다.
    """
    from sqlalchemy import select

    from .models import Asset

    async with ctx["sessionmaker"]() as session:
        stale = (
            await session.scalars(
                select(Asset.id)
                .where(Asset.derive_status == "pending", Asset.deleted_at.is_(None))
                .limit(500)
            )
        ).all()

    for asset_id in stale:
        await ctx["redis"].enqueue_job("derive_asset", str(asset_id), _job_id=f"derive:{asset_id}")
    if stale:
        log.info("파생물 재큐잉: %d건", len(stale))
    return len(stale)


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
        requeued = await _requeue_pending_derives(ctx)
        return {"ready": len(ready), "waiting": len(waiting), "requeued": requeued}
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

    # 파생물은 별도 작업으로 분리한다. 인제스트(빠름)와 디코딩(느림)을 한 작업에
    # 묶으면 큐가 디코딩에 막혀 새 파일이 DB 에 늦게 나타난다.
    if result.event in ("ingested", "restored") and result.asset_id:
        await ctx["redis"].enqueue_job(
            "derive_asset", result.asset_id, _job_id=f"derive:{result.asset_id}"
        )
    return {"event": result.event, "asset_id": result.asset_id}


async def derive_asset(ctx, asset_id: str) -> dict:
    """자산 하나의 파생물을 만든다 (§6.2).

    HEIC 는 이 작업이 끝나야 크롬에서 보인다. 실패해도 원본은 그대로 두고
    derive_status 만 failed 로 남긴다 — UI 가 "원본은 있는데 표시 못 함"을
    구분해 보여줄 수 있어야 한다 (§5).
    """
    from sqlalchemy import select

    from .models import Asset

    settings = ctx["settings"]
    async with ctx["sessionmaker"]() as session:
        async with session.begin():
            asset = await session.scalar(select(Asset).where(Asset.id == asset_id))
            if asset is None or asset.deleted_at is not None:
                return {"skipped": "없거나 삭제됨"}

            src = settings.originals_dir / asset.path
            if not src.exists():
                asset.derive_status = "failed"
                return {"error": f"원본 없음: {asset.path}"}

            try:
                result = generate(
                    src,
                    asset.sha256,
                    asset.kind,
                    settings.derived_root,
                    needs_display=asset.needs_display_copy,
                    rotation=asset.rotation or 0,
                )
            except DeriveError as exc:
                # 이 파일 자체의 문제. 다시 시도해도 같은 결과다.
                asset.derive_status = "failed"
                log.warning("파생물 생성 실패: %s — %s", asset.original_filename, exc)
                return {"error": str(exc)}
            except OSError as exc:
                # 권한·디스크 등 환경 문제. 조건이 바뀌면 성공하므로 pending 으로 두어
                # 다음 스캔이 다시 집어가게 한다. failed 로 못박으면 권한을 고쳐도
                # 영원히 복구되지 않는다.
                log.error(
                    "파생물 생성 중단(환경 문제, 재시도 예정): %s — %s\n"
                    "  derived 디렉터리 권한을 확인하세요: ls -ld %s",
                    asset.original_filename, exc, settings.derived_root,
                )
                raise

            asset.derive_status = "ready"
            log.info("파생물 완료: %s", asset.original_filename)
            return {"thumb": result.thumb, "display": result.display}


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
    functions = [scan_drop_folder, ingest_file, derive_asset]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # GPU 인코드 엔진이 하나뿐이라 무한정 늘려도 의미가 없다 (§6.3).
    max_jobs = get_settings().worker_concurrency
