"""자산 API 검증 (§3, §7.1)."""

import datetime as dt

import pytest

from poogiegram.ingest.metadata import _display_size, parse
from poogiegram.routes_assets import _decode_cursor, _encode_cursor, _derived_rel

SHA = "abcd1234" + "0" * 56


# ── 커서 ────────────────────────────────────────────────────────────


def test_커서_왕복():
    taken = dt.datetime(2026, 8, 8, 15, 27, 48, tzinfo=dt.timezone.utc)
    got_taken, got_id = _decode_cursor(_encode_cursor(taken, "abc-123"))
    assert got_taken == taken and got_id == "abc-123"


def test_잘못된_커서는_400():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _decode_cursor("!!!not-base64!!!")
    assert exc.value.status_code == 400


# ── 파생물 경로 ─────────────────────────────────────────────────────


def test_파생물_경로가_해시로_쪼개진다():
    class A:
        sha256 = SHA

    assert _derived_rel(A(), "thumb_320.webp") == f"ab/cd/{SHA}/thumb_320.webp"


# ── 화면에 보이는 크기 (§7.1) ───────────────────────────────────────
#
# 그리드는 이미지 로드 전에 비율로 자리를 잡는다. 여기가 틀리면 세로 사진이
# 전부 가로로 배치됐다가 로드 후 튄다.


@pytest.mark.parametrize("orientation,expected", [
    (1, (4000, 3000)),      # 회전 없음
    (3, (4000, 3000)),      # 180도 — 가로세로 그대로
    (6, (3000, 4000)),      # 90도 CW — 세로로 보인다
    (8, (3000, 4000)),      # 270도
    (None, (4000, 3000)),   # 태그 없음
])
def test_EXIF_회전이_크기에_반영된다(orientation, expected):
    raw = {"File:ImageWidth": 4000, "File:ImageHeight": 3000}
    if orientation is not None:
        raw["EXIF:Orientation"] = orientation
    assert _display_size(raw, "image") == expected


@pytest.mark.parametrize("rotation,expected", [
    (0, (1920, 1080)),
    (90, (1080, 1920)),
    (180, (1920, 1080)),
    (270, (1080, 1920)),
])
def test_영상_회전도_반영된다(rotation, expected):
    raw = {"QuickTime:ImageWidth": 1920, "QuickTime:ImageHeight": 1080,
           "Composite:Rotation": rotation}
    assert _display_size(raw, "video") == expected


def test_크기_정보가_없으면_None():
    assert _display_size({}, "image") == (None, None)


def test_세로_아이폰_사진_전체_경로():
    """실측 형태 — 센서는 가로로 저장하고 Orientation 으로 회전을 지시한다."""
    meta = parse({
        "File:MIMEType": "image/heic",
        "File:ImageWidth": 5712,
        "File:ImageHeight": 4284,
        "EXIF:Orientation": 6,
        "EXIF:Make": "Apple",
        "EXIF:Model": "iPhone 16 Pro",
    })
    assert (meta.width, meta.height) == (4284, 5712), "화면에 보이는 대로여야 한다"
