"""파생물 생성 (§6.2).

**HEIC 는 크롬·파이어폭스에서 표시되지 않는다.** 사파리만 된다. 그래서 아이폰 사진은
파생물이 생기기 전까지 화면에 아무것도 안 뜬다 — 파생물 생성은 최적화가 아니라
표시의 전제 조건이다.

원본은 절대 수정하지 않는다. 회전도 여기서 파생물에만 적용한다 (§4.1, §5.3).
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pillow_heif
from PIL import Image, ImageOps

log = logging.getLogger("poogiegram.ingest.derive")

pillow_heif.register_heif_opener()

# 초대형 이미지에서 Pillow 가 경고를 내지 않도록. 우리가 넣는 파일은 우리가 안다.
Image.MAX_IMAGE_PIXELS = None

THUMB = 320       # 그리드
PREVIEW = 1600    # 라이트박스
DISPLAY = 2560    # HEIC 의 브라우저 표시용 원본 대체

FFMPEG_TIMEOUT = 120


class DeriveError(RuntimeError):
    pass


@dataclass
class Derived:
    thumb: str
    preview: str
    display: str | None = None


def derived_dir(root: Path, sha256: str) -> Path:
    """해시를 2단계로 쪼개 디렉터리 하나에 파일이 몰리지 않게 한다.

    3만 장이 한 디렉터리에 들어가면 ls 하나에도 몇 초가 걸린다.
    """
    return root / sha256[:2] / sha256[2:4] / sha256


def _save_atomic(img: Image.Image, dest: Path, fmt: str, quality: int) -> None:
    """임시 파일에 쓰고 rename 한다.

    도중에 죽으면 반쪽 파일이 남는데, 크기가 0 이 아니라 '있는데 깨진' 상태라
    다음 실행에서 정상으로 오인된다.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dest.parent, suffix=".tmp", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        img.save(tmp_path, format=fmt, quality=quality, method=4 if fmt == "WEBP" else None)
        tmp_path.replace(dest)
    except TypeError:
        # JPEG 등 method 인자를 받지 않는 포맷
        img.save(tmp_path, format=fmt, quality=quality)
        tmp_path.replace(dest)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def poster_frame(video: Path, dest: Path) -> None:
    """영상에서 대표 프레임을 뽑는다.

    맨 앞 프레임은 검거나 흐린 경우가 많아 1초 지점을 쓴다. 1초보다 짧으면
    (라이브 포토 동반 클립이 대개 3초 안팎) 맨 앞으로 떨어진다.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    for seek in ("1", "0"):
        proc = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-ss", seek, "-i", str(video),
             "-frames:v", "1", "-q:v", "2", str(dest)],
            capture_output=True, timeout=FFMPEG_TIMEOUT,
        )
        if proc.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            return
    raise DeriveError(f"대표 프레임 추출 실패: {proc.stderr.decode(errors='replace')[:200]}")


def _load_image(path: Path, rotation: int) -> Image.Image:
    img = Image.open(path)
    img.load()
    # EXIF Orientation 을 픽셀에 반영한다. 이걸 빼면 아이폰 세로 사진이 눕는다.
    img = ImageOps.exif_transpose(img)
    if rotation:
        # 사용자가 지정한 추가 회전 (§5.3). 원본은 그대로 두고 파생물에만 적용한다.
        img = img.rotate(-rotation, expand=True)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


def generate(
    src: Path,
    sha256: str,
    kind: str,
    derived_root: Path,
    *,
    needs_display: bool = False,
    rotation: int = 0,
) -> Derived:
    """썸네일·프리뷰(·표시용 사본)를 만들고 상대경로를 돌려준다."""
    out = derived_dir(derived_root, sha256)
    rel = f"{sha256[:2]}/{sha256[2:4]}/{sha256}"

    tmp_poster: Path | None = None
    try:
        if kind == "video":
            tmp_poster = out / "poster.jpg"
            poster_frame(src, tmp_poster)
            source_img = tmp_poster
        else:
            source_img = src

        try:
            img = _load_image(source_img, rotation)
        except Exception as exc:  # noqa: BLE001 — Pillow 는 다양한 예외를 던진다
            raise DeriveError(f"이미지를 열 수 없음: {type(exc).__name__}: {exc}") from exc

        thumb = img.copy()
        thumb.thumbnail((THUMB, THUMB), Image.LANCZOS)
        _save_atomic(thumb, out / "thumb_320.webp", "WEBP", 80)

        preview = img.copy()
        preview.thumbnail((PREVIEW, PREVIEW), Image.LANCZOS)
        _save_atomic(preview, out / "preview_1600.webp", "WEBP", 82)

        display_rel = None
        if needs_display:
            # 원본을 그대로 못 보여주는 형식(HEIC)의 대체본. 여기까지 끝나야
            # 크롬에서 사진이 보인다 (§6.2).
            display = img.copy()
            display.thumbnail((DISPLAY, DISPLAY), Image.LANCZOS)
            _save_atomic(display, out / "display.jpg", "JPEG", 88)
            display_rel = f"{rel}/display.jpg"

        return Derived(f"{rel}/thumb_320.webp", f"{rel}/preview_1600.webp", display_rel)
    finally:
        if tmp_poster is not None:
            tmp_poster.unlink(missing_ok=True)
