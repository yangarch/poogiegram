"""인제스트 상태·트리거 API (§6.1).

사용자가 500장을 던져 넣고 나면 아무 피드백이 없다. 처리 중인지 끝났는지 알 수 없으면
같은 파일을 또 올리거나 폴더를 뒤지게 된다. 그래서 상태를 상시 노출한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select

from .deps import current_user
from .ingest.scanner import scan, walk_drop_dir
from .models import Asset

# 인증은 라우터 단위로 건다. 엔드포인트마다 붙이면 새로 추가할 때 빠뜨린다.
router = APIRouter(prefix="/api/ingest", tags=["ingest"], dependencies=[Depends(current_user)])


@router.get("/status")
async def ingest_status(request: Request) -> dict:
    """대기 · 완료 · 실패 건수.

    출처가 제각각인 이유는 §5.2 에 있다 — 큐 상태를 DB 에 중복 저장하면
    둘이 어긋나고 어느 쪽이 진실인지 알 수 없어진다.
      대기: 드롭 폴더의 파일 수 (파일시스템)
      완료·실패: asset.derive_status (DB)
    """
    settings = request.app.state.settings
    redis = request.app.state.redis

    ready, waiting = await scan(settings, redis)

    async with request.app.state.sessionmaker() as session:
        rows = await session.execute(
            select(Asset.derive_status, func.count())
            .where(Asset.deleted_at.is_(None))
            .group_by(Asset.derive_status)
        )
        by_status = dict(rows.all())

    return {
        "drop": {
            "ready": len(ready),          # 안정성 검사를 통과해 처리 대기 중
            "waiting": len(waiting),      # 업로드 중이거나 방금 도착
        },
        "failed_files": len(walk_drop_dir(settings.failed_dir)),
        "assets": {
            "pending": by_status.get("pending", 0),
            "ready": by_status.get("ready", 0),
            "failed": by_status.get("failed", 0),
        },
    }


@router.post("/scan")
async def trigger_scan(request: Request) -> dict:
    """지금 처리 — 주기 스캔을 기다리지 않고 즉시 실행한다."""
    job = await request.app.state.arq.enqueue_job("scan_drop_folder")
    return {"queued": True, "job_id": job.job_id if job else None}
