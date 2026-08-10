"""일괄 편집 — 태그 부여·해제, 삭제·복원 (§5.3).

**"기능이 있다"가 아니라 "몇 초 만에 끝난다"가 기준이다.** 수동 태깅은 비용이
사진 한 장당 발생하고 효용은 나중에 온다. 다른 서비스에서 태그가 방치되는 것도
기능이 나빠서가 아니라 입력이 번거롭기 때문이다. 그래서 전부 일괄 API 다.

삭제는 소프트 삭제다. `asset.path` 는 바꾸지 않고 루트만 다르게 해석한다 —
`deleted_at` 이 있으면 `trash/`, 없으면 `originals/` (§5.3의 휴지통 경로 규약).
경로 문자열을 건드릴 일이 없고 복원도 역방향 이동 한 번이다.
"""

from __future__ import annotations

import datetime as dt
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete as sql_delete
from sqlalchemy import select

from .deps import current_user
from .ingest.pipeline import attach_tags
from .models import Asset, AssetTag, Tag

log = logging.getLogger("poogiegram.edit")

router = APIRouter(prefix="/api/edit", tags=["edit"], dependencies=[Depends(current_user)])

# 한 번에 다룰 수 있는 자산 수. 무제한으로 두면 실수로 전체를 지우는 요청이
# 그대로 통과한다.
BATCH_MAX = 500


class TagEdit(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=BATCH_MAX)
    add: list[str] = []          # 태그 이름 — 없으면 만든다
    remove: list[str] = []       # 태그 id


class AssetIds(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=BATCH_MAX)


async def _load(session, asset_ids: list[str], *, deleted: bool) -> list[Asset]:
    stmt = select(Asset).where(Asset.id.in_(asset_ids))
    stmt = stmt.where(Asset.deleted_at.is_not(None) if deleted else Asset.deleted_at.is_(None))
    rows = list((await session.scalars(stmt)).all())
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "대상 사진을 찾지 못했습니다")
    return rows


def _move(src: Path, dest: Path) -> None:
    """휴지통과 originals 사이를 오간다. 상대경로는 그대로 유지한다 (§5.3).

    파일이 이미 없어도 진행한다 — DB 상태를 못 바꾸는 것보다, 파일이 사라진
    자산을 삭제 표시라도 해두는 편이 낫다.
    """
    if not src.exists():
        log.warning("이동할 파일이 없습니다: %s", src)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))


@router.post("/tags")
async def edit_tags(body: TagEdit, request: Request) -> dict:
    """여러 장에 태그를 한 번에 부여·해제한다.

    한 번의 동작이 200장을 커버해야 실제로 쓰인다 (§5.3).
    """
    added = removed = 0
    async with request.app.state.sessionmaker() as session:
        async with session.begin():
            assets = await _load(session, body.asset_ids, deleted=False)

            names = [" ".join(n.split()) for n in body.add]
            names = [n for n in names if n]
            for asset in assets:
                if names:
                    # 이미 붙어 있는 태그는 건너뛴다. 안 그러면 PK 중복으로 터진다.
                    existing = set(
                        (await session.scalars(
                            select(Tag.name)
                            .join(AssetTag, AssetTag.tag_id == Tag.id)
                            .where(AssetTag.asset_id == asset.id)
                        )).all()
                    )
                    fresh = [n for n in names if n not in existing]
                    if fresh:
                        await attach_tags(session, asset, fresh)
                        added += len(fresh)

            if body.remove:
                result = await session.execute(
                    sql_delete(AssetTag).where(
                        AssetTag.asset_id.in_([a.id for a in assets]),
                        AssetTag.tag_id.in_(body.remove),
                    )
                )
                removed = result.rowcount or 0

    return {"assets": len(body.asset_ids), "added": added, "removed": removed}


@router.post("/delete")
async def soft_delete(body: AssetIds, request: Request) -> dict:
    """휴지통으로 보낸다. 원본은 지우지 않고 옮기기만 한다 (§5.3)."""
    settings = request.app.state.settings
    now = dt.datetime.now(dt.timezone.utc)

    async with request.app.state.sessionmaker() as session:
        async with session.begin():
            assets = await _load(session, body.asset_ids, deleted=False)

            # 라이브 포토 동반 클립도 함께 보낸다. 정지컷만 지우면 타임라인에
            # 안 보이는 MOV 가 디스크에 남는다 (§6.5 — 정지컷이 주(主)).
            motion_ids = [a.live_motion_id for a in assets if a.live_motion_id]
            if motion_ids:
                assets += list(
                    (await session.scalars(
                        select(Asset).where(
                            Asset.id.in_(motion_ids), Asset.deleted_at.is_(None)
                        )
                    )).all()
                )

            for asset in assets:
                _move(settings.originals_dir / asset.path, settings.trash_dir / asset.path)
                asset.deleted_at = now
                asset.updated_at = now

    log.info("휴지통으로 이동: %d건", len(assets))
    return {"deleted": len(assets)}


@router.post("/restore")
async def restore(body: AssetIds, request: Request) -> dict:
    """휴지통에서 되돌린다. 같은 상대경로로 원위치한다 (§5.3)."""
    settings = request.app.state.settings

    async with request.app.state.sessionmaker() as session:
        async with session.begin():
            assets = await _load(session, body.asset_ids, deleted=True)
            for asset in assets:
                _move(settings.trash_dir / asset.path, settings.originals_dir / asset.path)
                asset.deleted_at = None
                asset.updated_at = dt.datetime.now(dt.timezone.utc)

    return {"restored": len(assets)}
