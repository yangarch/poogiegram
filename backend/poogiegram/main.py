from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from pathlib import Path

import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import logs
from .config import get_settings
from .db import make_engine, make_sessionmaker
from .routes_assets import router as assets_router
from .routes_auth import router as auth_router
from .routes_ingest import router as ingest_router
from .routes_tags import router as tags_router
from .routes_edit import router as edit_router
from .routes_upload import router as upload_router
from .storage import StorageNotReady, ensure_runtime_dirs, verify_storage

log = logging.getLogger("poogiegram")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logs.setup()
    settings = get_settings()

    # 마운트 확인이 먼저다 (§4.6). 실패하면 기동을 거부한다 —
    # 빈 마운트 포인트에 원본을 쓰기 시작하는 것보다 안 뜨는 편이 낫다.
    verify_storage(settings)
    ensure_runtime_dirs(settings)

    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    # 워커에 작업을 넣기 위한 arq 풀. 수동 스캔 트리거에 쓴다 (§6.1).
    app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))

    log.info("poogiegram 기동 — media=%s derived=%s", settings.media_root, settings.derived_root)
    if not settings.x_accel:
        log.warning(
            "X_ACCEL 이 꺼져 있습니다 — 앱이 파일을 직접 전송합니다. 개발 전용 설정입니다 (§3)."
        )
    yield

    await app.state.arq.aclose()
    await app.state.redis.aclose()
    await app.state.engine.dispose()


def default_static_dir() -> Path:
    """프런트엔드 빌드 산출물 위치. Dockerfile 이 web/dist 를 여기로 복사한다."""
    return Path(os.environ.get("STATIC_DIR") or Path(__file__).resolve().parent.parent / "static")


def create_app(static_dir: Path | None = None) -> FastAPI:
    """앱을 조립한다.

    팩토리로 둔 이유는 **라우트 등록 순서가 정확성을 좌우하기 때문이다.**
    FastAPI 는 등록 순서대로 매칭하므로 SPA catch-all 이 먼저 등록되면 그 뒤의
    라우트가 전부 삼켜진다. 실제로 /healthz 가 index.html 을 돌려주어 컨테이너가
    unhealthy 로 떨어진 적이 있다.

    모듈 최상위에 늘어놓으면 그 순서가 파일 편집으로 쉽게 깨지고, 테스트가
    확인하려면 모듈을 reload 해야 한다. 함수 안에 모아두면 순서가 한눈에 보이고
    테스트도 인자만 바꿔 앱을 새로 만들면 된다.
    """
    app = FastAPI(title="poogiegram", lifespan=lifespan)

    app.include_router(auth_router)
    app.include_router(assets_router)
    app.include_router(ingest_router)
    app.include_router(tags_router)
    app.include_router(upload_router)
    app.include_router(edit_router)

    app.add_api_route("/healthz", healthz, methods=["GET"])
    app.add_api_route("/readyz", readyz, methods=["GET"])

    # 반드시 마지막이다 — 위 라우트를 모두 등록한 뒤에 붙인다.
    _mount_spa(app, static_dir if static_dir is not None else default_static_dir())

    return app


async def healthz():
    """라이브니스 — 프로세스가 살아 있는지만 본다. 의존성을 확인하지 않는다."""
    return {"status": "ok"}


async def readyz(request: Request):
    """레디니스 — 스토리지·DB·Redis 가 모두 정상이어야 트래픽을 받을 수 있다."""
    checks: dict[str, str] = {}
    healthy = True

    app = request.app
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

    if not app.state.settings.x_accel:
        checks["x_accel"] = "비활성 — 앱이 파일을 직접 전송합니다 (개발 전용)"

    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "unavailable", "checks": checks},
    )


def _mount_spa(app: FastAPI, static: Path) -> None:
    """SPA 폴백을 붙인다. **호출 시점이 곧 우선순위다** — create_app 의 맨 끝에서 부른다.

    빌드 산출물이 있을 때만 붙인다. 개발 중에는 Vite 개발 서버가 담당하므로
    없어도 API 는 정상 동작해야 한다.
    """
    if not static.is_dir():
        log.warning("static/ 이 없습니다 — API 전용으로 동작합니다 (개발 모드)")
        return

    app.mount("/assets", StaticFiles(directory=static / "assets"), name="spa-assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        """클라이언트 라우팅을 위해 알 수 없는 경로도 index.html 로 돌려준다."""
        # 없는 API 를 부르면 index.html 이 200 으로 돌아가 디버깅이 헷갈린다.
        if path.startswith("api/") or path in ("healthz", "readyz"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "없는 경로입니다")
        candidate = (static / path).resolve()
        # 경로 탈출 방지 — ../ 로 static 밖 파일을 읽지 못하게 한다
        if path and candidate.is_file() and candidate.is_relative_to(static):
            return FileResponse(candidate)
        return FileResponse(static / "index.html")


app = create_app()
