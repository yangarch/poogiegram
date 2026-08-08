"""인제스트 파이프라인 (§6.1).

드롭 폴더의 파일 하나를 받아 originals/ 에 배치하고 DB 행을 만든다.
실패해도 사용자 파일을 잃지 않는 것이 최우선이다.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from ..config import Settings
from ..models import Asset, IngestLog
from . import dates, metadata

log = logging.getLogger("poogiegram.ingest")


class FileProblem(Exception):
    """이 파일 자체의 문제. 다시 시도해도 같은 결과다 → failed/ 로 격리한다.

    깨진 파일, 지원하지 않는 형식, 읽을 수 없는 권한 등이 해당한다.
    **인프라 문제(DB 연결 실패, 스키마 없음, 디스크 가득)는 여기 해당하지 않는다** —
    그건 조건이 바뀌면 성공하므로 파일을 drop/ 에 남겨두고 재시도해야 한다.
    사용자 파일을 인프라 사정으로 격리하면 안 된다.
    """

_HASH_CHUNK = 1 << 20   # 1MB. 대용량 영상도 메모리에 올리지 않는다
UNDATED_DIR = "_undated"


@dataclass
class Result:
    event: str                    # ingested | duplicate | restored | failed
    asset_id: str | None = None
    detail: str = ""


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_HASH_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def target_path(taken_local: dt.datetime, date_source: str, name: str, digest: str) -> str:
    """originals/ 기준 상대경로를 만든다.

    날짜 경로 + 해시 접미사인 이유 (§4.1):
      - 순수 해시 경로(CAS)는 파일탐색기로 열었을 때 아무것도 알아볼 수 없다.
        앱이 죽어도 파일만으로 복구 가능해야 한다.
      - 날짜만 쓰면 파일명이 충돌한다. 해시 앞 8자로 해결.

    촬영일을 못 찾았으면 _undated/ 로 보낸다. 1980년을 오염시키지 않고,
    나중에 날짜가 확정되면 날짜 경로로 옮긴다 (§6.7).
    """
    stem, ext = os.path.splitext(name)
    stem = stem[:80] or "file"          # 지나치게 긴 이름 방지
    filename = f"{stem}__{digest[:8]}{ext.lower()}"

    if date_source == "unknown":
        return f"{UNDATED_DIR}/{filename}"
    return f"{taken_local:%Y/%m/%d}/{filename}"


def move_into_place(src: Path, dest: Path) -> None:
    """원자적으로 옮긴다.

    drop/ 과 originals/ 는 같은 파일시스템(/mnt/media)이라 rename 한 번이면 끝난다.
    도중에 죽어도 반쪽 파일이 남지 않는다. 다른 파일시스템이면 복사 후 삭제로
    떨어지는데, 그때는 대용량 파일에서 느려지고 중단 시 잔해가 남는다.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dest)
    except OSError:
        # 파일시스템이 다른 경우의 폴백. 복사가 끝난 뒤에만 원본을 지운다.
        shutil.copy2(src, dest)
        src.unlink()


def move_to_failed(src: Path, failed_dir: Path, reason: str) -> Path:
    """실패한 파일을 사유와 함께 옮긴다.

    drop/ 에 남겨두고 재시도하면 매 사이클마다 같은 실패를 반복하며 로그를 채운다.
    그렇다고 앱이 사용자 파일을 지우면 신뢰를 깬다. 사유를 옆에 적어 옮긴다 —
    SFTP 로 붙으면 사용자가 직접 읽고 고칠 수 있다 (§6.1).
    """
    failed_dir.mkdir(parents=True, exist_ok=True)
    dest = failed_dir / src.name
    n = 1
    while dest.exists():
        dest = failed_dir / f"{src.stem}({n}){src.suffix}"
        n += 1
    move_into_place(src, dest)
    dest.with_suffix(dest.suffix + ".error.txt").write_text(
        f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}\n{reason}\n", encoding="utf-8"
    )
    return dest


async def _pair_live_photo(session, asset: Asset) -> None:
    """라이브 포토 정지컷과 동반 MOV 를 연결한다 (§6.5).

    드롭 폴더에서는 둘의 도착 순서가 정해져 있지 않다. 어느 쪽이 먼저 오든
    맞물리도록 양방향으로 찾는다.

    주의: 사진앱에서 내보낸 JPEG 도 **같은 그룹 UUID 를 갖는다**(실측 확인).
    그래서 "같은 ID 면 전부 한 묶음"이 아니라 **영상 하나를 정지컷에 붙이는 것**으로
    범위를 좁힌다.
    """
    if not asset.content_id:
        return

    # 애플은 라이브 포토에만 ContentIdentifier 를 쓴다. 영상에 이 값이 있다는 것 자체가
    # 동반 클립이라는 뜻이므로, **짝을 찾기 전에** 숨김 처리한다.
    # 드롭 폴더에서는 MOV 가 정지컷보다 먼저 도착하는 일이 흔한데, 이 처리가 뒤에 있으면
    # 그 사이 3초짜리 영상이 타임라인에 그대로 노출된다.
    if asset.kind == "video":
        asset.is_live_motion = True

    stmt = select(Asset).where(
        Asset.content_id == asset.content_id,
        Asset.id != asset.id,
        Asset.deleted_at.is_(None),
    )
    others = (await session.scalars(stmt)).all()
    if not others:
        return

    if asset.kind == "video":
        for still in (o for o in others if o.kind == "image"):
            if still.live_motion_id is None:
                still.live_motion_id = asset.id
                log.info("라이브 포토 연결: %s ← %s", still.original_filename, asset.original_filename)
    else:
        # 정지컷이 나중에 온 경우. 이미 들어와 있는 MOV 를 찾는다.
        for motion in (o for o in others if o.kind == "video"):
            motion.is_live_motion = True
            asset.live_motion_id = motion.id
            log.info("라이브 포토 연결: %s ← %s", asset.original_filename, motion.original_filename)
            break


async def repair_pairings(session) -> int:
    """짝을 못 찾은 라이브 포토를 다시 묶는다 (§6.5).

    인제스트 시점의 페어링만으로는 부족하다. 파일마다 별도 트랜잭션에서 처리되므로
    **동시에 들어온 정지컷과 영상이 서로를 보지 못한다** — 각자 커밋 전이기 때문이다.
    실제로 HEIC·JPEG·MOV 를 한꺼번에 넣었을 때 JPEG 만 누락되는 것을 확인했다.

    도착 순서가 정해져 있지 않은 드롭 폴더에서는 나중에 짝이 오는 경우도 있어,
    어느 쪽이든 주기적으로 훑어 맞물리게 하는 편이 확실하다. 멱등이라 몇 번 돌려도 된다.
    """
    # 1) content_id 가 있는 영상은 그 자체로 라이브 포토 동반 클립이다
    unmarked = (
        await session.scalars(
            select(Asset).where(
                Asset.kind == "video",
                Asset.content_id.is_not(None),
                Asset.is_live_motion.is_(False),
                Asset.deleted_at.is_(None),
            )
        )
    ).all()
    for motion in unmarked:
        motion.is_live_motion = True

    # 2) 짝이 있는데 연결되지 않은 정지컷을 잇는다
    motions = {
        m.content_id: m
        for m in (
            await session.scalars(
                select(Asset).where(
                    Asset.kind == "video",
                    Asset.content_id.is_not(None),
                    Asset.deleted_at.is_(None),
                )
            )
        ).all()
    }
    if not motions:
        return len(unmarked)

    orphans = (
        await session.scalars(
            select(Asset).where(
                Asset.kind == "image",
                Asset.content_id.in_(list(motions)),
                Asset.live_motion_id.is_(None),
                Asset.deleted_at.is_(None),
            )
        )
    ).all()
    for still in orphans:
        still.live_motion_id = motions[still.content_id].id
        log.info("라이브 포토 뒤늦은 연결: %s", still.original_filename)

    return len(unmarked) + len(orphans)


async def ingest_file(session, settings: Settings, src: Path) -> Result:
    """파일 하나를 인제스트한다. 예외를 던지지 않고 Result 로 돌려준다."""
    name = src.name

    try:
        digest = sha256_of(src)
    except OSError as exc:
        raise FileProblem(f"읽을 수 없음: {exc}") from exc

    # ── 중복 판정 (§5.2) ───────────────────────────────────────────
    existing = await session.scalar(select(Asset).where(Asset.sha256 == digest))
    if existing is not None:
        if existing.deleted_at is None:
            src.unlink()
            return Result("duplicate", str(existing.id), "이미 존재")

        # 소프트 삭제된 자산의 재업로드 → 새 행을 만들지 않고 되살린다.
        # 새로 만들면 같은 사진이 둘이 된다.
        trash_file = settings.trash_dir / existing.path
        target = settings.originals_dir / existing.path
        if trash_file.exists():
            move_into_place(trash_file, target)
            src.unlink()
        else:
            move_into_place(src, target)
        existing.deleted_at = None
        existing.updated_at = dt.datetime.now(dt.timezone.utc)
        return Result("restored", str(existing.id), "휴지통에서 복원")

    # ── 메타데이터 ────────────────────────────────────────────────
    try:
        meta = metadata.extract(src)
    except metadata.MetadataError as exc:
        raise FileProblem(str(exc)) from exc

    local, offset, source = dates.resolve(meta.tags, src, meta.kind)
    rel = target_path(local, source, name, digest)

    asset = Asset(
        sha256=digest,
        path=rel,
        original_filename=name,
        kind=meta.kind,
        mime=meta.mime,
        bytes=src.stat().st_size,
        width=meta.width,
        height=meta.height,
        duration_ms=meta.duration_ms,
        taken_local=local,
        taken_at=dates.to_utc(local, offset),
        tz_offset=offset,
        date_source=source,
        lat=meta.lat,
        lon=meta.lon,
        camera=meta.camera,
        exif=meta.raw,
        codec=meta.codec,
        content_id=meta.content_id,
        is_screenshot=meta.is_screenshot,
        # HEIC 는 크롬·파이어폭스에서 표시되지 않아 display.jpg 가 필수다 (§6.2)
        needs_display_copy=(meta.mime == "image/heic"),
        derive_status="pending",
        video_status=("needs_transcode" if meta.kind == "video" else None),
    )

    # DB 행을 먼저 만들어 sha256 경합을 DB 제약으로 처리한다.
    session.add(asset)
    await session.flush()

    move_into_place(src, settings.originals_dir / rel)
    await _pair_live_photo(session, asset)

    return Result("ingested", str(asset.id), rel)


async def ingest_one(sessionmaker, settings: Settings, src: Path) -> Result:
    """트랜잭션 경계와 실패 처리를 감싼다.

    **파일 문제와 인프라 문제를 구분한다.** 전자는 격리하고, 후자는 예외를 그대로
    올려보내 파일을 drop/ 에 남긴다 — arq 가 재시도하고 다음 스캔에서도 다시 잡힌다.
    이 구분이 없으면 DB 가 잠깐 내려간 사이에 사용자 파일이 전부 격리된다.
    """
    try:
        async with sessionmaker() as session:
            async with session.begin():
                result = await ingest_file(session, settings, src)
                session.add(
                    IngestLog(
                        asset_id=result.asset_id,
                        source_filename=src.name,
                        event=result.event,
                    )
                )
        return result
    except FileProblem as exc:
        detail = str(exc)
        log.warning("파일 문제로 격리: %s — %s", src.name, detail)
    except Exception:
        # 인프라 문제로 본다. 파일은 그대로 두고 예외를 올려 재시도하게 한다.
        log.exception("인제스트 중단(재시도 예정): %s", src.name)
        raise

    if src.exists():
        move_to_failed(src, settings.failed_dir, detail)
    try:
        async with sessionmaker() as session:
            async with session.begin():
                session.add(
                    IngestLog(source_filename=src.name, event="failed", error=detail[:2000])
                )
    except Exception:  # noqa: BLE001 — 격리는 이미 끝났다. 기록 실패로 죽이지 않는다
        log.exception("실패 기록을 남기지 못함: %s", src.name)
    return Result("failed", detail=detail)
