"""태그 (§5.5).

사건 단위로 모아 보기 위한 것이다 — "2025년 결혼기념일", "푸기 3번째 생일".
태그는 드롭 폴더의 하위 폴더 이름에서 자동으로 붙는다 (§6.1). 손으로 하나씩
지정하는 UI만 있으면 아무도 쓰지 않기 때문이다.

**별도 라우터인 이유**: assets 라우터에 넣으면 경로가 `/api/assets/tags/...` 가 되어
`/api/assets/{asset_id}/...` 와 같은 모양이 된다. 등록 순서에 따라 한쪽이 가려지는데,
그 방식으로 이미 한 번 사고가 났다 (§3, main.py 의 SPA 폴백).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select, update

from .deps import current_user
from .ingest.pipeline import TAG_NAME_MAX
from .models import Asset, AssetTag, Tag

log = logging.getLogger("poogiegram.tags")

router = APIRouter(prefix="/api/tags", tags=["tags"], dependencies=[Depends(current_user)])

LIST_MAX = 500


@router.get("")
async def list_tags(
    request: Request,
    q: str | None = None,
    limit: int = Query(LIST_MAX, ge=1, le=LIST_MAX),
) -> dict:
    """태그 목록. **사진이 많은 순**으로 준다.

    자주 쓰는 태그가 위로 올라와야 헤더에서 바로 고를 수 있다. 이름순으로 주면
    태그가 수백 개일 때 매번 검색해야 한다.

    개수를 함께 주는 이유는 빈 태그가 쌓이는 것을 눈으로 확인하기 위해서다.
    삭제된 자산과 라이브 포토 동반 클립은 세지 않는다 — 목록에 안 보이는 것을
    세면 헤더의 개수와 실제로 열리는 사진 수가 어긋난다.
    """
    counted = (
        select(AssetTag.tag_id, func.count().label("n"))
        .join(Asset, Asset.id == AssetTag.asset_id)
        .where(Asset.deleted_at.is_(None), Asset.is_live_motion.is_(False))
        .group_by(AssetTag.tag_id)
        .subquery()
    )
    stmt = (
        select(Tag.id, Tag.name, func.coalesce(counted.c.n, 0).label("count"))
        .outerjoin(counted, counted.c.tag_id == Tag.id)
        .order_by(func.coalesce(counted.c.n, 0).desc(), Tag.name)
        .limit(limit)
    )
    if q:
        stmt = stmt.where(Tag.name.ilike(f"%{q}%"))

    async with request.app.state.sessionmaker() as session:
        rows = (await session.execute(stmt)).all()

    return {"items": [{"id": str(r.id), "name": r.name, "count": r.count} for r in rows]}


class TagRename(BaseModel):
    name: str = Field(min_length=1, max_length=TAG_NAME_MAX)


@router.patch("/{tag_id}")
async def rename_tag(tag_id: str, body: TagRename, request: Request) -> dict:
    """이름을 바꾼다. **이미 있는 이름으로 바꾸면 병합된다** (§5.3).

    오타로 표기가 흔들리는 것은 막을 수 없다 — `푸기생일`과 `푸기 생일`이 따로
    생긴다. 되돌릴 수 있어야 하므로 이름 변경과 병합을 한 동작으로 둔다.
    "합치기"를 따로 만들면 사용자가 두 기능의 차이를 먼저 이해해야 한다.
    """
    name = " ".join(body.name.split())
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "이름이 비어 있습니다")

    async with request.app.state.sessionmaker() as session:
        async with session.begin():
            tag = await session.get(Tag, tag_id)
            if tag is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "태그를 찾지 못했습니다")
            if tag.name == name:
                return {"id": str(tag.id), "name": name, "merged": False}

            target = await session.scalar(select(Tag).where(Tag.name == name))
            if target is None:
                tag.name = name
                return {"id": str(tag.id), "name": name, "merged": False}

            # 병합. 양쪽에 다 붙어 있던 자산은 PK 가 겹치므로 먼저 걸러낸다.
            both = select(AssetTag.asset_id).where(AssetTag.tag_id == target.id)
            await session.execute(
                update(AssetTag)
                .where(AssetTag.tag_id == tag.id, AssetTag.asset_id.not_in(both))
                .values(tag_id=target.id)
            )
            await session.execute(sql_delete(AssetTag).where(AssetTag.tag_id == tag.id))
            await session.delete(tag)
            log.info("태그 병합: %s → %s", tag.name, name)
            return {"id": str(target.id), "name": name, "merged": True}


@router.delete("/{tag_id}")
async def delete_tag(tag_id: str, request: Request) -> dict:
    """태그만 지운다. **사진은 그대로다** — asset_tag 만 정리된다."""
    async with request.app.state.sessionmaker() as session:
        async with session.begin():
            tag = await session.get(Tag, tag_id)
            if tag is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "태그를 찾지 못했습니다")
            await session.execute(sql_delete(AssetTag).where(AssetTag.tag_id == tag.id))
            await session.delete(tag)
    return {"ok": True}
