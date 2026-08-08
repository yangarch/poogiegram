"""촬영일 판정 (§6.7).

스냅사진 납품본은 촬영일이 깨져 있는 경우가 흔하다. 그냥 mtime 을 쓰면
`originals/1980/01/01/` 에 쌓여 타임라인 끝에 뭉치고 "과거의 오늘"에서 매년 1월 1일에
튀어나온다. 우선순위 체인으로 최선의 값을 찾고, **어디서 얻었는지를 함께 기록**한다.

실측으로 확인한 두 가지가 이 모듈의 핵심이다 (2026-08-08, 아이폰 16 Pro).

1. **사진과 영상의 시각 기준이 다르다.**
   EXIF `DateTimeOriginal` 은 현지 벽시계 시각이고, QuickTime `CreateDate` 는 UTC 다.
   같은 순간의 라이브 포토 쌍이 15:27(HEIC) 과 06:27(MOV) 로 기록돼 있었다.
   똑같이 다루면 9시간이 어긋나고, 밤 촬영이면 **날짜가 하루 밀린다.**

2. **영상에는 오프셋을 가진 `QuickTime:CreationDate` 가 따로 있다.**
   `2026:08:08 15:27:47+09:00` 형태라, 이걸 1순위로 쓰면 위 문제가 사라진다.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path

log = logging.getLogger("poogiegram.ingest.dates")

# 이 범위를 벗어난 값은 신뢰하지 않고 다음 순위로 넘어간다.
#   1980-01-01 = MS-DOS/ZIP 에폭. 작가가 ZIP 으로 납품했고 압축 해제 때
#   타임스탬프가 유실됐다는 신호이지 촬영일이 아니다.
#   1970-01-01 = 유닉스 에폭. 같은 성격.
#   카메라 시계가 초기화되면 2000-01-01 이 박히기도 한다.
MIN_PLAUSIBLE = dt.datetime(1995, 1, 1)
FUTURE_TOLERANCE = dt.timedelta(days=1)

_EXIF_DT = re.compile(r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})")
_OFFSET = re.compile(r"([+-])(\d{2}):?(\d{2})$")

# 파일명에서 날짜를 뽑는다. 작가들이 흔히 쓰는 형태들.
_FILENAME_PATTERNS = [
    re.compile(r"(?<!\d)(20\d{2})[-_]?(\d{2})[-_]?(\d{2})(?!\d)"),   # 20240315 / 2024-03-15
    re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})_\d+"),                # 20240315_001
]


def _parse_exif_datetime(value: str) -> dt.datetime | None:
    m = _EXIF_DT.match(str(value))
    if not m:
        return None
    try:
        return dt.datetime(*(int(g) for g in m.groups()))
    except ValueError:
        return None


def _parse_offset_minutes(value: str) -> int | None:
    """'+09:00' → 540. 값 끝에 붙은 오프셋도 인식한다."""
    m = _OFFSET.search(str(value).strip())
    if not m:
        return None
    sign, hh, mm = m.groups()
    minutes = int(hh) * 60 + int(mm)
    return -minutes if sign == "-" else minutes


def is_plausible(value: dt.datetime) -> bool:
    if value < MIN_PLAUSIBLE:
        return False
    return value <= dt.datetime.now() + FUTURE_TOLERANCE


def from_filename(name: str) -> dt.datetime | None:
    """파일명에서 날짜를 뽑는다. 시각 정보는 없으므로 정오로 둔다.

    자정으로 두면 타임존 보정이나 반올림에서 하루가 밀릴 수 있다.
    """
    for pattern in _FILENAME_PATTERNS:
        if m := pattern.search(name):
            try:
                value = dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), 12)
            except ValueError:
                continue
            if is_plausible(value):
                return value
    return None


def resolve(
    tags: dict,
    path: Path,
    kind: str,
    sibling_hint: dt.datetime | None = None,
) -> tuple[dt.datetime, int | None, str]:
    """(현지 촬영시각, 오프셋(분), 판정 근거) 를 돌려준다.

    반환하는 시각은 항상 **현지 벽시계 기준**이다 — 날짜 그룹핑과 "과거의 오늘"이
    현지 날짜로 동작해야 하기 때문이다 (§5).
    """
    # 1) 영상: 오프셋을 가진 CreationDate 가 가장 정확하다
    if kind == "video":
        if raw := tags.get("QuickTime:CreationDate"):
            if (value := _parse_exif_datetime(raw)) and is_plausible(value):
                return value, _parse_offset_minutes(raw), "exif"

    # 2) 사진: EXIF 촬영일시 + 오프셋
    for date_key, offset_key in (
        ("EXIF:DateTimeOriginal", "EXIF:OffsetTimeOriginal"),
        ("EXIF:CreateDate", "EXIF:OffsetTime"),
    ):
        if raw := tags.get(date_key):
            if (value := _parse_exif_datetime(raw)) and is_plausible(value):
                offset = _parse_offset_minutes(tags.get(offset_key, "") or "")
                return value, offset, "exif"

    # 3) XMP — 라이트룸 내보내기에서 EXIF 가 지워져도 살아남는 경우가 많다
    for key in ("XMP:DateTimeOriginal", "XMP:CreateDate"):
        if raw := tags.get(key):
            if (value := _parse_exif_datetime(raw)) and is_plausible(value):
                return value, _parse_offset_minutes(raw), "xmp"

    # 4) UTC 기준 QuickTime 값. 오프셋을 모르므로 그대로 두고 근거만 남긴다.
    #    라이브 포토의 동반 MOV 는 타임라인에서 숨겨지므로 영향이 작다.
    if raw := tags.get("QuickTime:CreateDate"):
        if (value := _parse_exif_datetime(raw)) and is_plausible(value):
            return value, None, "exif"

    # 5) 파일명 — 스냅사진에서 의외로 잘 맞는다
    if value := from_filename(path.name):
        return value, None, "filename"

    # 6) 같은 배치의 형제 파일. 200장 중 190장이 정상이면 나머지도 같은 촬영이다.
    if sibling_hint is not None:
        return sibling_hint, None, "sibling"

    # 7) 파일 mtime. 신뢰도가 낮아 "과거의 오늘"에서 제외된다 (§5.1).
    try:
        value = dt.datetime.fromtimestamp(path.stat().st_mtime)
        if is_plausible(value):
            return value, None, "mtime"
    except OSError:
        pass

    # 8) 판정 실패. 거부하지 않고 _undated/ 로 들여보낸 뒤 나중에 고칠 수 있게 한다.
    log.warning("촬영일 판정 실패: %s", path.name)
    return dt.datetime.now(), None, "unknown"


def to_utc(local: dt.datetime, offset_minutes: int | None) -> dt.datetime:
    """현지 시각을 절대 시각으로 바꾼다.

    오프셋을 모르면 서버 로컬 타임존으로 해석한다 — 대부분의 사진이 같은 지역에서
    찍히므로 무작정 UTC 로 보는 것보다 낫다.
    """
    if offset_minutes is None:
        return local.astimezone().astimezone(dt.timezone.utc)
    tz = dt.timezone(dt.timedelta(minutes=offset_minutes))
    return local.replace(tzinfo=tz).astimezone(dt.timezone.utc)
