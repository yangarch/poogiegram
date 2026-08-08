"""exiftool 로 메타데이터를 뽑아 정규화한다.

실제 아이폰 16 Pro 파일에서 확인한 것들을 근거로 한다 (2026-08-08 실측).
필드 이름이 사진과 영상에서 다르고, **시각의 기준마저 다르다** — 그 차이를 여기서 흡수한다.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("poogiegram.ingest.metadata")

EXIFTOOL_TIMEOUT = 60

# 저장할 필요가 없는 그룹. File: 은 인제스트 시점의 경로가 들어가는데,
# 파일을 originals/ 로 옮기고 나면 곧바로 낡은 정보가 된다.
_DROPPED_GROUPS = ("File:", "ExifTool:")

_VIDEO_MIME = ("video/",)

# 처리할 수 있는 형식만 받는다. exiftool 은 내용이 깨진 파일에도 오류를 내지 않고
# 최소 정보만 돌려주므로, MIME 검사가 없으면 텍스트 파일도 사진으로 들어온다.
SUPPORTED_IMAGE = {
    "image/jpeg", "image/heic", "image/heif", "image/png",
    "image/webp", "image/tiff", "image/gif", "image/avif",
}
SUPPORTED_VIDEO = {
    "video/quicktime", "video/mp4", "video/x-m4v",
    "video/3gpp", "video/webm", "video/mpeg", "video/x-msvideo",
}
# RAW 는 범위에서 제외했다 (§4.5). 조용히 실패시키지 않고 이유를 밝힌다.
RAW_MIME = {
    "image/x-adobe-dng", "image/x-canon-cr2", "image/x-canon-cr3",
    "image/x-sony-arw", "image/x-nikon-nef", "image/x-fuji-raf",
    "image/x-olympus-orf", "image/x-panasonic-rw2",
}

# 촬영 기기의 흔적. 하나라도 있으면 스크린샷이 아니다.
_CAMERA_EVIDENCE = (
    "EXIF:ExposureTime", "EXIF:FNumber", "EXIF:ISO", "EXIF:FocalLength",
    "EXIF:LensModel", "EXIF:LensMake", "EXIF:ShutterSpeedValue",
    "EXIF:ApertureValue", "EXIF:GPSLatitude", "Composite:GPSLatitude",
)


class MetadataError(RuntimeError):
    pass


@dataclass
class Metadata:
    raw: dict                       # exif 컬럼에 통째로 저장
    mime: str | None = None
    kind: str = "image"
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    camera: str | None = None
    lat: float | None = None
    lon: float | None = None
    codec: str | None = None
    # 라이브 포토 그룹 키. 정지컷은 MediaGroupUUID, 영상은 ContentIdentifier 로
    # **필드 이름이 다르지만 값은 같다.**
    content_id: str | None = None
    is_screenshot: bool = False
    tags: dict = field(default_factory=dict)   # 날짜 판정에 쓸 원시 문자열들


def run_exiftool(path: Path) -> dict:
    """단일 파일의 전체 메타데이터를 dict 로 돌려준다.

    `-n` 이 중요하다 — 없으면 GPS 가 "37 deg 25' 49.26\\"" 같은 문자열로 나와
    파싱이 필요해진다. `-G` 는 EXIF: / QuickTime: 그룹을 구분하기 위해 쓴다.
    """
    try:
        proc = subprocess.run(
            ["exiftool", "-json", "-n", "-G", "-charset", "filename=utf8", str(path)],
            capture_output=True,
            timeout=EXIFTOOL_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise MetadataError(f"exiftool 시간 초과({EXIFTOOL_TIMEOUT}s)") from exc

    if proc.returncode != 0 or not proc.stdout.strip():
        err = proc.stderr.decode(errors="replace").strip()
        raise MetadataError(f"exiftool 실패: {err or '출력 없음'}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise MetadataError(f"exiftool 출력을 해석할 수 없음: {exc}") from exc

    if not data:
        raise MetadataError("exiftool 이 빈 결과를 돌려줌")
    return data[0]


def _first(raw: dict, *keys: str):
    for k in keys:
        v = raw.get(k)
        if v not in (None, ""):
            return v
    return None


def _looks_like_screenshot(raw: dict, kind: str, make, model) -> bool:
    """스크린샷 판별 (§5.1).

    "카메라 정보가 없으면 스크린샷"만으로는 부족하다. **EXIF 가 지워진 정상 사진**
    (라이트룸 내보내기, 스냅 납품본)도 Make/Model 이 없어서 같이 걸린다.
    진짜 사진이 "과거의 오늘"에서 조용히 빠지는 것은 스크린샷이 섞이는 것보다 나쁘다.

    그래서 노출·렌즈·GPS 같은 **촬영 흔적이 하나도 없을 때만** 스크린샷으로 본다.
    판단이 애매하면 스크린샷이 아닌 쪽으로 기운다.
    """
    if kind != "image" or make or model:
        return False
    return not any(raw.get(tag) not in (None, "") for tag in _CAMERA_EVIDENCE)


# EXIF Orientation 5~8 은 90/270도 회전을 뜻한다 — 화면에 보이는 가로세로가 뒤바뀐다.
_SWAPPED_ORIENTATIONS = {5, 6, 7, 8}


def _display_size(raw: dict, kind: str) -> tuple[int | None, int | None]:
    """**화면에 보이는** 가로세로를 돌려준다.

    파일에 저장된 값과 다를 수 있다. 세로로 찍은 아이폰 사진은 센서 방향 그대로
    가로로 저장되고 Orientation 태그로 회전을 지시한다. 파생물은 회전을 적용해
    만들므로(derive.py), DB 값도 같은 기준이어야 한다.

    안 맞으면 그리드(§7.1)가 이미지 로드 전에 잘못된 비율로 자리를 잡아
    세로 사진이 전부 가로로 배치된다.
    """
    w = _first(raw, "File:ImageWidth", "QuickTime:ImageWidth", "EXIF:ImageWidth")
    h = _first(raw, "File:ImageHeight", "QuickTime:ImageHeight", "EXIF:ImageHeight")
    if w is None or h is None:
        return w, h

    if kind == "video":
        rotation = _first(raw, "Composite:Rotation", "QuickTime:Rotation") or 0
        swap = int(float(rotation)) % 180 == 90
    else:
        orientation = _first(raw, "EXIF:Orientation")
        swap = orientation is not None and int(orientation) in _SWAPPED_ORIENTATIONS

    return (h, w) if swap else (w, h)


def parse(raw: dict) -> Metadata:
    mime = raw.get("File:MIMEType")
    kind = "video" if (mime or "").startswith(_VIDEO_MIME) else "image"

    if mime in RAW_MIME:
        raise MetadataError(f"RAW 는 지원하지 않습니다 (§4.5): {mime}")
    if mime not in SUPPORTED_IMAGE and mime not in SUPPORTED_VIDEO:
        raise MetadataError(
            f"지원하지 않는 형식입니다: {mime or '판별 불가'} "
            f"(FileType={raw.get('File:FileType') or '알 수 없음'})"
        )

    make = _first(raw, "EXIF:Make", "QuickTime:Make")
    model = _first(raw, "EXIF:Model", "QuickTime:Model")
    camera = " ".join(x for x in (make, model) if x) or None

    duration = _first(raw, "QuickTime:Duration", "Composite:Duration")
    duration_ms = int(float(duration) * 1000) if duration is not None else None

    width, height = _display_size(raw, kind)

    return Metadata(
        raw={k: v for k, v in raw.items() if not k.startswith(_DROPPED_GROUPS)},
        mime=mime,
        kind=kind,
        width=width,
        height=height,
        duration_ms=duration_ms,
        camera=camera,
        # -n 덕분에 십진수로 들어온다. Composite 쪽이 부호(남반구·서반구)까지 반영한 값이다.
        lat=_first(raw, "Composite:GPSLatitude", "EXIF:GPSLatitude"),
        lon=_first(raw, "Composite:GPSLongitude", "EXIF:GPSLongitude"),
        codec=_first(raw, "QuickTime:CompressorID"),
        # 같은 값인데 이름이 다르다 — 실측으로 확인한 사실이다.
        content_id=_first(raw, "MakerNotes:MediaGroupUUID", "QuickTime:ContentIdentifier"),
        is_screenshot=_looks_like_screenshot(raw, kind, make, model),
        tags=raw,
    )


def extract(path: Path) -> Metadata:
    return parse(run_exiftool(path))
