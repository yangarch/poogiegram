"""드롭 폴더 스캐너 (§6.1).

사용자는 `incoming/drop/` 에 파일을 던져 넣기만 한다. 이 모듈은 그중
**처리해도 안전한 파일**을 골라낸다.

가장 중요한 일은 **업로드 중인 파일을 걸러내는 것**이다. SFTP 로 500MB 영상을 올리는
중에도 파일은 즉시 목록에 보인다. 이때 집어가면 잘린 파일이 원본으로 저장되고,
원본은 앱이 수정하지 않는 영역이라 나중에 발견해도 되돌리기 번거롭다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings

log = logging.getLogger("poogiegram.ingest.scanner")

# 이름만으로 걸러낼 것들. 확장자가 아니라 "이런 파일은 아직 완성본이 아니다"라는 신호다.
_IGNORED_SUFFIXES = {".part", ".filepart", ".crdownload", ".partial", ".tmp", ".download"}
_IGNORED_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
# 동기화 도구·NAS 가 만드는 디렉터리. 안에 원본 사본이 있어 중복을 유발한다.
_IGNORED_DIRS = {"@eadir", "#recycle", "__macosx", ".git"}

REDIS_KEY_SEEN = "ingest:seen"


@dataclass(frozen=True)
class Candidate:
    path: Path
    size: int
    mtime: float

    @property
    def key(self) -> str:
        return str(self.path)


def _is_ignored(path: Path, root: Path) -> str | None:
    """무시할 이유를 돌려준다. 처리 대상이면 None."""
    if path.name.startswith("."):
        return "숨김 파일"
    if path.name.lower() in _IGNORED_NAMES:
        return "시스템 파일"
    if path.suffix.lower() in _IGNORED_SUFFIXES:
        return "전송 중 임시 파일"
    for part in path.relative_to(root).parts[:-1]:
        if part.startswith(".") or part.lower() in _IGNORED_DIRS:
            return f"무시 디렉터리({part})"
    return None


def walk_drop_dir(root: Path) -> list[Path]:
    """드롭 폴더를 재귀 탐색한다.

    하위 폴더째로 드래그해도 되도록 재귀로 훑는다. 원본의 폴더 구조는 보존하지 않는다 —
    배치 기준은 EXIF 촬영일시다 (§6.1).
    """
    found: list[Path] = []
    if not root.is_dir():
        return found

    for path in root.rglob("*"):
        # 심볼릭 링크는 따라가지 않는다. drop/ 안에 외부를 가리키는 링크가 생기면
        # chroot 밖의 파일을 읽어들이게 된다.
        if path.is_symlink():
            log.warning("심볼릭 링크 무시: %s", path)
            continue
        if not path.is_file():
            continue
        if (reason := _is_ignored(path, root)) is not None:
            log.debug("무시(%s): %s", reason, path.name)
            continue
        found.append(path)
    return found


def is_stable(cand: Candidate, previous: tuple[int, float] | None, stable_seconds: int) -> bool:
    """지금 처리해도 되는 파일인지 판정한다.

    두 조건을 모두 만족해야 한다.

    1. **mtime 이 충분히 오래됐다** — 마지막 쓰기 이후 `stable_seconds` 가 지났다는 뜻이다.
       전송 중에는 데이터가 쓰일 때마다 mtime 이 갱신되므로 이것만으로 대부분 걸러진다.

    2. **직전 관측과 크기가 같다** — 일부 SFTP 클라이언트는 "타임스탬프 보존" 옵션으로
       원본 mtime 을 복원한다. 그 경우 1번이 뚫릴 수 있어 크기 비교로 한 겹 더 막는다.
       직전 관측이 없으면(=이번에 처음 본 파일) 1번만으로 판정한다.
    """
    if time.time() - cand.mtime < stable_seconds:
        return False
    if previous is not None and previous[0] != cand.size:
        return False
    return True


def _decode(raw: dict) -> dict[str, str]:
    """Redis 응답을 str 로 정규화한다.

    arq 의 풀은 `decode_responses=False` 라 bytes 를 돌려주고, API 쪽 클라이언트는
    `decode_responses=True` 라 str 을 돌려준다. 같은 해시를 양쪽이 읽으므로
    여기서 맞춰준다. 이걸 빠뜨리면 str 키로 조회해 항상 못 찾고, 차집합 연산이
    매 스캔마다 전체 삭제로 동작해 **크기 비교 방어막이 조용히 죽는다.**
    """
    return {
        (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
        for k, v in (raw or {}).items()
    }


async def scan(settings: Settings, redis) -> tuple[list[Candidate], list[Candidate]]:
    """드롭 폴더를 훑어 (처리 가능, 대기 중) 목록을 돌려준다.

    관측 기록은 Redis 에 둔다. 워커가 재시작해도 크기 비교가 이어지고,
    API 쪽에서 대기 목록을 읽을 수도 있다.
    """
    root = settings.drop_dir
    stable_seconds = settings.ingest_stable_seconds

    previous = _decode(await redis.hgetall(REDIS_KEY_SEEN))
    ready: list[Candidate] = []
    waiting: list[Candidate] = []
    observed: dict[str, str] = {}

    for path in walk_drop_dir(root):
        try:
            st = path.stat()
        except FileNotFoundError:
            # 스캔 도중 사라졌다. 다음 사이클에서 다시 본다.
            continue

        cand = Candidate(path=path, size=st.st_size, mtime=st.st_mtime)
        observed[cand.key] = f"{cand.size}"

        prev_raw = previous.get(cand.key)
        prev = (int(prev_raw), 0.0) if prev_raw else None

        if is_stable(cand, prev, stable_seconds):
            ready.append(cand)
        else:
            waiting.append(cand)

    # 사라진 파일의 관측 기록은 지운다. 그대로 두면 Redis 에 계속 쌓인다.
    if previous:
        gone = set(previous) - set(observed)
        if gone:
            await redis.hdel(REDIS_KEY_SEEN, *gone)
    if observed:
        await redis.hset(REDIS_KEY_SEEN, mapping=observed)

    return ready, waiting
