"""촬영일 판정 검증 (§6.7).

픽스처는 **실제 아이폰 16 Pro 파일에서 뽑은 값**이다 (2026-08-08 실측).
지어낸 값으로 테스트하면 현실의 필드 이름·형식 차이를 놓친다.
"""

import datetime as dt
from pathlib import Path

import pytest

from poogiegram.ingest.dates import from_filename, is_plausible, resolve, to_utc

# ── 실측 픽스처 ──────────────────────────────────────────────────────

HEIC = {
    "EXIF:Make": "Apple",
    "EXIF:Model": "iPhone 16 Pro",
    "EXIF:DateTimeOriginal": "2026:08:08 15:27:48",
    "EXIF:CreateDate": "2026:08:08 15:27:48",
    "EXIF:OffsetTimeOriginal": "+09:00",
    "EXIF:OffsetTime": "+09:00",
    "MakerNotes:MediaGroupUUID": "0191DCC6-51E8-452F-9829-3F21FE2E39EA",
}

# 같은 순간의 동반 MOV. CreateDate 는 UTC(06:27), CreationDate 는 현지+오프셋(15:27).
MOV = {
    "QuickTime:CreateDate": "2026:08:08 06:27:48",
    "QuickTime:ModifyDate": "2026:08:08 06:27:50",
    "QuickTime:CreationDate": "2026:08:08 15:27:47+09:00",
    "QuickTime:ContentIdentifier": "0191DCC6-51E8-452F-9829-3F21FE2E39EA",
}


def test_사진은_EXIF_현지시각과_오프셋을_쓴다():
    local, offset, src = resolve(HEIC, Path("IMG_2774.HEIC"), "image")
    assert (local.hour, local.minute) == (15, 27)
    assert offset == 540
    assert src == "exif"


def test_영상은_CreationDate를_우선한다():
    """CreateDate(UTC) 를 쓰면 9시간이 어긋난다."""
    local, offset, src = resolve(MOV, Path("IMG_2774.mov"), "video")
    assert local.hour == 15, "UTC 06:27 이 아니라 현지 15:27 이어야 한다"
    assert offset == 540
    assert src == "exif"


def test_라이브포토_쌍이_같은_순간으로_기록된다():
    """페어링의 전제다. 9시간 벌어지면 날짜 헤더까지 갈라진다."""
    still, _, _ = resolve(HEIC, Path("IMG_2774.HEIC"), "image")
    motion, _, _ = resolve(MOV, Path("IMG_2774.mov"), "video")
    assert abs((still - motion).total_seconds()) < 5


def test_CreationDate가_없으면_UTC값이라도_쓴다():
    tags = {k: v for k, v in MOV.items() if k != "QuickTime:CreationDate"}
    local, offset, src = resolve(tags, Path("a.mov"), "video")
    assert local.hour == 6 and offset is None and src == "exif"


# ── 타당성 검사 ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,ok",
    [
        (dt.datetime(1980, 1, 1), False),   # MS-DOS/ZIP 에폭
        (dt.datetime(1970, 1, 1), False),   # 유닉스 에폭
        (dt.datetime(1994, 12, 31), False),
        (dt.datetime(2000, 1, 1), True),    # 카메라 시계 초기화값이지만 범위 안
        (dt.datetime(2024, 3, 15), True),
        (dt.datetime.now() + dt.timedelta(days=10), False),  # 미래
    ],
)
def test_타당성_범위(value, ok):
    assert is_plausible(value) is ok


def test_ZIP_에폭이면_다음_순위로_넘어간다(tmp_path):
    """스냅사진 납품본에서 실제로 겪는 상황."""
    f = tmp_path / "20240315_001.jpg"
    f.write_bytes(b"x")
    tags = {"EXIF:DateTimeOriginal": "1980:01:01 00:00:00"}
    local, _, src = resolve(tags, f, "image")
    assert src == "filename", "EXIF 를 버리고 파일명으로 넘어가야 한다"
    assert (local.year, local.month, local.day) == (2024, 3, 15)


# ── 파일명 추출 ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,expected",
    [
        ("20240315_001.jpg", (2024, 3, 15)),
        ("2024-03-15_1234.jpg", (2024, 3, 15)),
        ("2024_03_15 결혼식.jpg", (2024, 3, 15)),
        ("IMG_2774.HEIC", None),
        # 사진앱 내보내기 파일명. UUID 라 날짜가 없다 — 실제로 받은 형태다.
        ("94808A62-B17C-4605-BD8A-D745A1ED05D2_1_102_o.jpeg", None),
        ("20241340_x.jpg", None),   # 13월 40일
    ],
)
def test_파일명_패턴(name, expected):
    got = from_filename(name)
    assert (None if got is None else (got.year, got.month, got.day)) == expected


# ── 폴백 ─────────────────────────────────────────────────────────────


def test_아무것도_없으면_mtime(tmp_path):
    f = tmp_path / "x.jpg"
    f.write_bytes(b"x")
    _, _, src = resolve({}, f, "image")
    assert src == "mtime"


def test_형제_힌트가_mtime보다_우선(tmp_path):
    f = tmp_path / "x.jpg"
    f.write_bytes(b"x")
    hint = dt.datetime(2024, 3, 15, 12)
    local, _, src = resolve({}, f, "image", sibling_hint=hint)
    assert src == "sibling" and local == hint


# ── UTC 변환 ─────────────────────────────────────────────────────────


def test_오프셋으로_절대시각_계산():
    utc = to_utc(dt.datetime(2026, 8, 8, 15, 27, 48), 540)
    assert utc == dt.datetime(2026, 8, 8, 6, 27, 48, tzinfo=dt.timezone.utc)


def test_자정_근처_날짜_경계():
    """KST 는 UTC+9 이므로 UTC = 현지 − 9시간이다.

    서울 **오전** 촬영분이 UTC 로는 전날이 된다. UTC 기준으로 날짜를 자르면
    아침에 찍은 사진이 하루 전으로 밀린다 — taken_local 을 따로 두는 이유다 (§5.1).
    """
    local = dt.datetime(2026, 8, 8, 8, 30)   # 서울 8/8 오전 8시 반
    utc = to_utc(local, 540)
    assert (utc.day, utc.hour) == (7, 23), "절대 시각은 8/7 23:30 — 전날"
    assert local.day == 8, "현지 날짜는 8일 — taken_md 는 이쪽을 쓴다"
