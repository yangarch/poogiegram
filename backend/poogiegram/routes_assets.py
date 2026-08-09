"""자산 목록과 파일 서빙 (§3, §7.1).

**바이트는 Python 을 거치지 않는다.** 권한 검사만 여기서 하고 실제 전송은
`X-Accel-Redirect` 로 nginx 에 넘긴다. Python 이 4K 영상을 스트리밍하면 워커가
오래 점유되어 API 응답 전체가 밀린다.
"""

from __future__ import annotations

import base64
import datetime as dt
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from .deps import current_user
from .models import Asset, AssetTag

log = logging.getLogger("poogiegram.assets")

router = APIRouter(prefix="/api/assets", tags=["assets"], dependencies=[Depends(current_user)])

PAGE_SIZE_MAX = 500

# nginx 의 internal location 과 짝을 이룬다 (deploy/nginx/poogiegram.conf.example).
ACCEL_MEDIA = "/_media"
ACCEL_DERIVED = "/_derived"


def _encode_cursor(taken_at: dt.datetime, asset_id) -> str:
    return base64.urlsafe_b64encode(f"{taken_at.isoformat()}|{asset_id}".encode()).decode()


def _decode_cursor(raw: str) -> tuple[dt.datetime, str]:
    try:
        taken, asset_id = base64.urlsafe_b64decode(raw.encode()).decode().split("|", 1)
        return dt.datetime.fromisoformat(taken), asset_id
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "커서 형식이 올바르지 않습니다") from exc


def _serialize(a: Asset) -> dict:
    return {
        "id": str(a.id),
        "kind": a.kind,
        # 그리드는 이미지가 로드되기 전에 자리를 잡아야 한다 — 비율이 먼저 필요하다 (§7.1).
        # 이 값은 EXIF 회전이 반영된 '화면에 보이는' 크기다.
        "width": a.width,
        "height": a.height,
        "taken_local": a.taken_local.isoformat(),
        "taken_at": a.taken_at.isoformat(),
        "duration_ms": a.duration_ms,
        "is_favorite": a.is_favorite,
        "has_motion": a.live_motion_id is not None,   # 라이브 포토
        "date_source": a.date_source,
        # 파생물이 아직 없으면 화면에 아무것도 못 띄운다. UI 가 자리표시자를 보여야 한다.
        "ready": a.derive_status == "ready",
    }


@router.get("")
async def list_assets(
    request: Request,
    limit: int = Query(100, ge=1, le=PAGE_SIZE_MAX),
    cursor: str | None = None,
    favorites: bool = False,
    tag_id: str | None = None,
) -> dict:
    """타임라인. 커서 기반이라 스크롤 중 새 자산이 들어와도 밀리지 않는다.

    정렬은 `taken_at`(절대 시각)으로 한다. 여행 사진처럼 타임존이 섞여도 실제
    시간 순서가 유지된다. 화면의 날짜 헤더는 `taken_local` 로 그린다 (§5).
    """
    stmt = (
        select(Asset)
        .where(
            Asset.deleted_at.is_(None),
            # 라이브 포토의 동반 MOV 를 목록에서 제외한다. 빠뜨리면 같은 장면이
            # 사진 1장 + 영상 1개로 두 번 뜬다 (§6.5).
            Asset.is_live_motion.is_(False),
        )
        .order_by(Asset.taken_at.desc(), Asset.id.desc())
        .limit(limit + 1)
    )
    if favorites:
        stmt = stmt.where(Asset.is_favorite.is_(True))
    if tag_id:
        # 태그로 거른다 (§5.5). EXISTS 를 쓰는 이유는 조인이 행을 부풀리지 않게
        # 하기 위해서다 — 커서 페이지네이션은 행 수가 정확해야 한다.
        stmt = stmt.where(
            select(AssetTag.asset_id)
            .where(AssetTag.asset_id == Asset.id, AssetTag.tag_id == tag_id)
            .exists()
        )
    if cursor:
        taken_at, asset_id = _decode_cursor(cursor)
        stmt = stmt.where(
            (Asset.taken_at < taken_at)
            | ((Asset.taken_at == taken_at) & (Asset.id < asset_id))
        )

    async with request.app.state.sessionmaker() as session:
        rows = (await session.scalars(stmt)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [_serialize(a) for a in rows],
        "next_cursor": _encode_cursor(rows[-1].taken_at, rows[-1].id) if has_more and rows else None,
    }


async def _get_asset(request: Request, asset_id: str) -> Asset:
    async with request.app.state.sessionmaker() as session:
        asset = await session.scalar(
            select(Asset).where(Asset.id == asset_id, Asset.deleted_at.is_(None))
        )
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "찾을 수 없습니다")
    return asset


def _derived_rel(asset: Asset, filename: str) -> str:
    s = asset.sha256
    return f"{s[:2]}/{s[2:4]}/{s}/{filename}"


def _serve(request: Request, internal_path: str, disk_path, *, download_as: str | None = None):
    """권한 검사가 끝난 파일을 응답한다.

    운영에서는 헤더만 돌려주고 nginx 가 전송한다. X_ACCEL 을 끄면 개발 편의를 위해
    직접 전송하는데, **운영에서 이 경로를 타면 안 된다** — 대용량 파일 하나가
    워커를 오래 점유해 API 전체를 느리게 만든다.
    """
    headers = {"Cache-Control": "private, max-age=31536000, immutable"}
    if download_as:
        headers["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{quote(download_as)}"
        )

    if not request.app.state.settings.x_accel:
        if not disk_path.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "파일이 없습니다")
        return FileResponse(disk_path, headers=headers)

    # 경로에 한글·공백이 들어갈 수 있다. nginx 는 이 값을 URL 로 해석하므로
    # 인코딩하지 않으면 파일을 찾지 못한다.
    headers["X-Accel-Redirect"] = quote(internal_path)
    return Response(status_code=200, headers=headers)


@router.get("/{asset_id}/thumb")
async def get_thumb(asset_id: str, request: Request):
    asset = await _get_asset(request, asset_id)
    rel = _derived_rel(asset, "thumb_320.webp")
    return _serve(request, f"{ACCEL_DERIVED}/{rel}", request.app.state.settings.derived_root / rel)


@router.get("/{asset_id}/preview")
async def get_preview(asset_id: str, request: Request):
    asset = await _get_asset(request, asset_id)
    rel = _derived_rel(asset, "preview_1600.webp")
    return _serve(request, f"{ACCEL_DERIVED}/{rel}", request.app.state.settings.derived_root / rel)


@router.get("/{asset_id}/display")
async def get_display(asset_id: str, request: Request):
    """전체 화면용. HEIC 처럼 브라우저가 못 여는 형식만 대체본을 쓴다 (§6.2)."""
    asset = await _get_asset(request, asset_id)
    settings = request.app.state.settings
    if asset.needs_display_copy:
        rel = _derived_rel(asset, "display.jpg")
        return _serve(request, f"{ACCEL_DERIVED}/{rel}", settings.derived_root / rel)
    return _serve(
        request,
        f"{ACCEL_MEDIA}/originals/{asset.path}",
        settings.originals_dir / asset.path,
    )


@router.get("/{asset_id}/original")
async def get_original(asset_id: str, request: Request):
    """원본 내려받기. 회전은 파생물에만 적용하므로 원본은 촬영 그대로다 (§5.3)."""
    asset = await _get_asset(request, asset_id)
    return _serve(
        request,
        f"{ACCEL_MEDIA}/originals/{asset.path}",
        request.app.state.settings.originals_dir / asset.path,
        download_as=asset.original_filename,
    )


@router.get("/{asset_id}/motion")
async def get_motion(asset_id: str, request: Request):
    """라이브 포토의 동반 클립. 정지컷 ID 로 요청한다."""
    asset = await _get_asset(request, asset_id)
    if asset.live_motion_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "동반 클립이 없습니다")
    motion = await _get_asset(request, str(asset.live_motion_id))
    return _serve(
        request,
        f"{ACCEL_MEDIA}/originals/{motion.path}",
        request.app.state.settings.originals_dir / motion.path,
    )
