"""태그 (§5.5).

사건 단위로 모아 보기 위한 것이다 — "2025년 결혼기념일", "푸기 3번째 생일".
태그는 드롭 폴더의 하위 폴더 이름에서 자동으로 붙는다 (§6.1). 손으로 하나씩
지정하는 UI만 있으면 아무도 쓰지 않기 때문이다.

**별도 라우터인 이유**: assets 라우터에 넣으면 경로가 `/api/assets/tags/...` 가 되어
`/api/assets/{asset_id}/...` 와 같은 모양이 된다. 등록 순서에 따라 한쪽이 가려지는데,
그 방식으로 이미 한 번 사고가 났다 (§3, main.py 의 SPA 폴백).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from .deps import current_user
from .models import Asset, AssetTag, Tag

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
