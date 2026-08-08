"""데이터 모델 (PROJECT.md §5).

설계 근거는 PROJECT.md 에 있다. 여기 주석은 코드를 읽을 때 헷갈리기 쉬운 것만 적는다.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from . import enums
from .db import Base

_UUID_PK = text("gen_random_uuid()")   # PG13+ 내장. pgcrypto 확장 불필요


def _chk(col: str, values: tuple) -> str:
    return f"{col} IN ({enums.sql_in(values)})"


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=_UUID_PK)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(16), default="member", server_default=text("'member'"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (CheckConstraint(_chk("role", enums.USER_ROLE), name="ck_user_role"),)


class Asset(Base):
    """물리 파일 1개 = asset 1행. sha256 으로 유일하다."""

    __tablename__ = "asset"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=_UUID_PK)

    sha256: Mapped[str] = mapped_column(String(64))
    # originals/ 기준 상대경로. 소프트 삭제 시에도 바꾸지 않고 루트만 다르게 해석한다 (§5.3).
    path: Mapped[str] = mapped_column(Text)
    # 사용자가 검색창에 치는 이름. path 에는 해시 접미사가 붙어 있어 쓸 수 없다.
    original_filename: Mapped[str] = mapped_column(Text)

    kind: Mapped[str] = mapped_column(String(8))
    mime: Mapped[str | None] = mapped_column(String(100))
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    # ── 시각 (§5, §6.7) ─────────────────────────────────────────────
    # taken_local: 현지 벽시계 시각. 날짜 그룹핑·"과거의 오늘"의 기준.
    # taken_at:    절대 시각. 서로 다른 타임존 사진의 선후 판정은 이쪽으로만 가능.
    taken_local: Mapped[dt.datetime] = mapped_column(DateTime(timezone=False))
    taken_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    tz_offset: Mapped[int | None] = mapped_column(Integer)  # 분 단위

    # 현지 기준 월일(0807). timestamp(tz 없음)에 대한 EXTRACT 는 IMMUTABLE 이라
    # 생성 컬럼으로 만들 수 있다. timestamptz 였다면 STABLE 이라 불가능하다.
    taken_md: Mapped[int] = mapped_column(
        SmallInteger,
        Computed(
            "EXTRACT(MONTH FROM taken_local)::int * 100 "
            "+ EXTRACT(DAY FROM taken_local)::int",
            persisted=True,
        ),
    )
    date_source: Mapped[str] = mapped_column(String(16))

    # ── 위치 ────────────────────────────────────────────────────────
    # point 대신 분리한다 — point(x, y)는 (경도, 위도) 순서라 뒤집어 넣는 실수가 잦다.
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    place: Mapped[str | None] = mapped_column(Text)

    camera: Mapped[str | None] = mapped_column(Text)
    exif: Mapped[dict | None] = mapped_column(JSONB)

    # ── 포맷·파생물 ─────────────────────────────────────────────────
    codec: Mapped[str | None] = mapped_column(String(16))
    is_hdr: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    needs_display_copy: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    derive_status: Mapped[str] = mapped_column(String(16), default="pending", server_default=text("'pending'"))
    # 마지막 실패 사유. 없으면 실패할 때마다 컨테이너 로그를 뒤져야 하는데,
    # 로그는 재시작하면 잘리고 시간이 지나면 사라진다. 성공하면 비운다.
    derive_error: Mapped[str | None] = mapped_column(Text)
    video_status: Mapped[str | None] = mapped_column(String(16))

    # ── 라이브 포토 (§6.5) ──────────────────────────────────────────
    # 단방향 참조: 정지컷이 주(主), MOV 가 종(從).
    content_id: Mapped[str | None] = mapped_column(Text)  # Apple ContentIdentifier
    live_motion_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset.id"))
    is_live_motion: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    # ── 큐레이션 (§5.1) ─────────────────────────────────────────────
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_screenshot: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    # ── 사용자 편집 (§5.3) ──────────────────────────────────────────
    rotation: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    caption: Mapped[str | None] = mapped_column(Text)

    # owner_id 는 출처 기록일 뿐 권한 제어가 아니다 — 모든 구성원이 전부 본다 (§5.2).
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # 중복 제거. 소프트 삭제된 행도 걸리므로, 재업로드 시 새 행을 만들지 않고
        # 기존 행을 되살린다 (§5.2).
        UniqueConstraint("sha256", name="uq_asset_sha256"),
        CheckConstraint(_chk("kind", enums.KIND), name="ck_asset_kind"),
        CheckConstraint(_chk("date_source", enums.DATE_SOURCE), name="ck_asset_date_source"),
        CheckConstraint(_chk("derive_status", enums.DERIVE_STATUS), name="ck_asset_derive_status"),
        CheckConstraint(
            f"video_status IS NULL OR {_chk('video_status', enums.VIDEO_STATUS)}",
            name="ck_asset_video_status",
        ),
        CheckConstraint(_chk("rotation", enums.ROTATION), name="ck_asset_rotation"),
        # 타임라인. 삭제된 행은 조회하지 않으므로 부분 인덱스로 작게 유지한다.
        Index(
            "ix_asset_timeline",
            text("taken_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # "과거의 오늘" (§5.1)
        Index(
            "ix_asset_on_this_day",
            "taken_md",
            text("taken_local DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # 뒤늦게 도착한 MOV 를 짝에 붙일 때 쓴다 (§6.5). 드롭 폴더에서는 흔한 경로다.
        Index(
            "ix_asset_content_id",
            "content_id",
            postgresql_where=text("content_id IS NOT NULL"),
        ),
        Index("ix_asset_exif", "exif", postgresql_using="gin"),
    )


class Album(Base):
    __tablename__ = "album"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=_UUID_PK)
    name: Mapped[str] = mapped_column(Text)
    cover_asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset.id"))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AlbumAsset(Base):
    __tablename__ = "album_asset"

    album_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("album.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))  # 수동 정렬


class Tag(Base):
    """전 구성원 공용. 가족이 같은 어휘를 쓰는 편이 검색에 유리하다 (§5.3)."""

    __tablename__ = "tag"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=_UUID_PK)
    name: Mapped[str] = mapped_column(Text, unique=True)


class AssetTag(Base):
    __tablename__ = "asset_tag"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True
    )


class ShareLink(Base):
    """앨범 또는 자산 중 정확히 하나를 가리킨다."""

    __tablename__ = "share_link"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=_UUID_PK)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    album_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("album.id", ondelete="CASCADE"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset.id", ondelete="CASCADE"))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(Text)
    allow_download: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("num_nonnulls(album_id, asset_id) = 1", name="ck_share_link_target"),
    )


class IngestLog(Base):
    """큐가 아니라 이력이다 (§5.2).

    작업 큐는 Redis+arq 가 들고 있다. 여기에 큐 상태를 중복 저장하면 둘이 어긋나고
    어느 쪽이 진실인지 알 수 없어진다. append-only 로만 쓴다.
    """

    __tablename__ = "ingest_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=_UUID_PK)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset.id", ondelete="SET NULL"))
    source_filename: Mapped[str] = mapped_column(Text)
    event: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(_chk("event", enums.INGEST_EVENT), name="ck_ingest_log_event"),
        Index("ix_ingest_log_created", text("created_at DESC")),
    )
