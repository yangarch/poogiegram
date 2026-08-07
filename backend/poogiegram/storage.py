"""스토리지 마운트 검증 (§4.6).

`nofail` 로 마운트하기 때문에 외장 디스크가 붙지 않아도 부팅은 된다. 그 상태로 앱이
기동하면 **빈 마운트 포인트(루트 파티션)에 원본을 쓰기 시작한다.** 라이브러리는 텅 빈
것처럼 보이고 원본은 엉뚱한 디스크에 쌓인다.

그래서 originals/ 안의 마커 파일 존재를 기동 조건으로 삼는다. 마커는 실제 미디어
디스크에만 있으므로, 마운트가 안 됐다면 보이지 않는다.
"""

from __future__ import annotations

from .config import Settings


class StorageNotReady(RuntimeError):
    pass


def verify_storage(settings: Settings) -> None:
    """마운트가 정상인지 확인한다. 문제가 있으면 StorageNotReady 를 던진다."""
    marker = settings.marker_path

    if not settings.media_root.is_dir():
        raise StorageNotReady(f"MEDIA_ROOT 가 없습니다: {settings.media_root}")

    if not marker.is_file():
        raise StorageNotReady(
            f"마커 파일이 없습니다: {marker}\n"
            "미디어 디스크가 마운트되지 않았을 가능성이 큽니다. "
            "이 상태로 기동하면 원본이 엉뚱한 디스크에 쌓입니다.\n"
            "  확인:  df -h /mnt/media && ls -la /mnt/media/originals/"
        )


def ensure_runtime_dirs(settings: Settings) -> None:
    """앱이 소유하는 하위 디렉터리를 만든다. originals/ 는 이미 있어야 한다."""
    for path in (settings.drop_dir, settings.failed_dir, settings.tmp_dir, settings.trash_dir):
        path.mkdir(parents=True, exist_ok=True)
    settings.derived_root.mkdir(parents=True, exist_ok=True)
