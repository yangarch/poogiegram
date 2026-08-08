from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import get_settings
from .db import make_engine, make_sessionmaker
from .storage import StorageNotReady, ensure_runtime_dirs, verify_storage

log = logging.getLogger("poogiegram")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # 마운트 확인이 먼저다 (§4.6). 실패하면 기동을 거부한다 —
    # 빈 마운트 포인트에 원본을 쓰기 시작하는 것보다 안 뜨는 편이 낫다.
    verify_storage(settings)
    ensure_runtime_dirs(settings)

    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    log.info("poogiegram 기동 — media=%s derived=%s", settings.media_root, settings.derived_root)
    yield

    await app.state.redis.aclose()
    await app.state.engine.dispose()


app = FastAPI(title="poogiegram", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    """라이브니스 — 프로세스가 살아 있는지만 본다. 의존성을 확인하지 않는다."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    """레디니스 — 스토리지·DB·Redis 가 모두 정상이어야 트래픽을 받을 수 있다."""
    checks: dict[str, str] = {}
    healthy = True

    try:
        verify_storage(app.state.settings)
        checks["storage"] = "ok"
    except StorageNotReady as exc:
        checks["storage"] = str(exc).splitlines()[0]
        healthy = False

    try:
        async with app.state.sessionmaker() as session:
            # 연결만이 아니라 마이그레이션이 적용됐는지도 본다.
            # 스키마가 없으면 "DB 는 살아있는데 앱은 아무것도 못 하는" 상태가 되는데,
            # SELECT 1 만으로는 그걸 구분할 수 없다.
            rev = await session.scalar(text("SELECT version_num FROM alembic_version"))
        checks["database"] = f"ok (migration {rev})"
    except Exception as exc:  # noqa: BLE001 — 원인을 그대로 보여주는 편이 진단에 낫다
        checks["database"] = f"{type(exc).__name__}: {exc}"
        healthy = False

    try:
        await app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"{type(exc).__name__}: {exc}"
        healthy = False

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "unavailable", "checks": checks},
    )
