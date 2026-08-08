"""드롭 폴더 스캐너 검증 (§6.1).

안정성 판정이 틀리면 업로드 중인 파일이 잘린 채로 원본에 저장된다.
원본은 앱이 수정하지 않는 영역이라 나중에 발견해도 되돌리기 번거롭다.
"""

import os
import time

import pytest

from poogiegram.ingest.scanner import Candidate, is_stable, walk_drop_dir

STABLE = 30


def _cand(tmp_path, name="a.heic", size=100, age=0.0):
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    return Candidate(path=p, size=size, mtime=time.time() - age)


# ── 안정성 판정 ──────────────────────────────────────────────────────


def test_방금_쓰인_파일은_대기(tmp_path):
    """전송 중에는 데이터가 쓰일 때마다 mtime 이 갱신된다."""
    assert not is_stable(_cand(tmp_path, age=0), None, STABLE)


def test_충분히_오래된_파일은_처리대상(tmp_path):
    assert is_stable(_cand(tmp_path, age=STABLE + 1), None, STABLE)


def test_경계값_직전은_대기(tmp_path):
    assert not is_stable(_cand(tmp_path, age=STABLE - 1), None, STABLE)


def test_크기가_변했으면_대기(tmp_path):
    """타임스탬프 보존 옵션으로 mtime 이 오래돼 보여도 크기 비교로 잡는다.

    일부 SFTP 클라이언트는 전송 후 원본 mtime 을 복원한다. mtime 만 믿으면
    전송 중인 파일을 집을 수 있어 한 겹 더 둔다.
    """
    cand = _cand(tmp_path, size=200, age=STABLE + 1)
    assert not is_stable(cand, previous=(100, 0.0), stable_seconds=STABLE)


def test_크기가_같으면_처리대상(tmp_path):
    cand = _cand(tmp_path, size=200, age=STABLE + 1)
    assert is_stable(cand, previous=(200, 0.0), stable_seconds=STABLE)


# ── 탐색·필터 ────────────────────────────────────────────────────────


def test_하위폴더를_재귀로_훑는다(tmp_path):
    """폴더째로 드래그해도 되어야 한다. 원본 폴더 구조는 보존하지 않는다."""
    (tmp_path / "2024" / "여행").mkdir(parents=True)
    (tmp_path / "2024" / "여행" / "a.heic").write_bytes(b"x")
    (tmp_path / "b.jpg").write_bytes(b"x")
    assert {p.name for p in walk_drop_dir(tmp_path)} == {"a.heic", "b.jpg"}


@pytest.mark.parametrize(
    "name",
    [
        ".DS_Store",           # 맥이 폴더마다 만든다
        "._a.heic",            # 맥 리소스 포크
        "a.heic.part",         # 전송 중
        "b.jpg.filepart",      # FileZilla
        "c.mov.crdownload",    # 크롬 다운로드
        "Thumbs.db",           # 윈도우
        "desktop.ini",
    ],
)
def test_임시_시스템_파일은_무시(tmp_path, name):
    (tmp_path / name).write_bytes(b"x")
    assert walk_drop_dir(tmp_path) == []


def test_동기화_디렉터리는_무시(tmp_path):
    """@eaDir 등에는 원본 사본이 들어 있어 중복을 유발한다."""
    (tmp_path / "@eaDir").mkdir()
    (tmp_path / "@eaDir" / "a.heic").write_bytes(b"x")
    (tmp_path / "__MACOSX").mkdir()
    (tmp_path / "__MACOSX" / "b.jpg").write_bytes(b"x")
    assert walk_drop_dir(tmp_path) == []


def test_심볼릭_링크는_따라가지_않는다(tmp_path):
    """drop/ 안의 링크가 외부를 가리키면 chroot 밖 파일을 읽게 된다."""
    outside = tmp_path.parent / "outside.heic"
    outside.write_bytes(b"secret")
    (tmp_path / "link.heic").symlink_to(outside)
    assert walk_drop_dir(tmp_path) == []


def test_빈_디렉터리는_결과에_없다(tmp_path):
    (tmp_path / "empty").mkdir()
    assert walk_drop_dir(tmp_path) == []


def test_없는_디렉터리를_훑어도_죽지_않는다(tmp_path):
    assert walk_drop_dir(tmp_path / "nope") == []


# ── 실전 시나리오 ────────────────────────────────────────────────────


def test_업로드_중_파일은_완료될_때까지_대기(tmp_path):
    """파일이 자라는 동안 계속 대기하다가, 멈추고 시간이 지나면 처리 대상이 된다."""
    p = tmp_path / "big.mov"
    p.write_bytes(b"x" * 1000)

    # 전송 중: mtime 이 지금이라 대기
    cand = Candidate(path=p, size=1000, mtime=time.time())
    assert not is_stable(cand, None, STABLE)

    # 더 쓰였다: 크기가 늘고 mtime 도 갱신 → 여전히 대기
    cand = Candidate(path=p, size=5000, mtime=time.time())
    assert not is_stable(cand, (1000, 0.0), STABLE)

    # 전송 완료 후 시간이 지났다: 크기 동일 + mtime 오래됨 → 처리
    cand = Candidate(path=p, size=5000, mtime=time.time() - STABLE - 1)
    assert is_stable(cand, (5000, 0.0), STABLE)


# ── Redis 왕복 ───────────────────────────────────────────────────────


class _FakeRedis:
    """arq 의 풀은 decode_responses=False 라 bytes 를 돌려준다.

    이 동작을 재현하지 않으면 str/bytes 불일치를 놓친다 — 실제로 놓쳐서
    크기 비교 방어막이 조용히 죽어 있었다.
    """

    def __init__(self, decode: bool):
        self.decode, self.h = decode, {}

    async def hgetall(self, key):
        if self.decode:
            return dict(self.h)
        return {k.encode(): v.encode() for k, v in self.h.items()}

    async def hset(self, key, mapping):
        self.h.update(mapping)

    async def hdel(self, key, *fields):
        for f in fields:
            self.h.pop(f.decode() if isinstance(f, bytes) else f, None)


@pytest.mark.parametrize("decode", [True, False])
@pytest.mark.asyncio
async def test_관측기록이_스캔_사이에_유지된다(tmp_path, decode):
    """bytes 든 str 이든 기록이 남아야 크기 비교가 성립한다."""
    from types import SimpleNamespace

    from poogiegram.ingest.scanner import scan

    drop = tmp_path / "drop"
    drop.mkdir()
    f = drop / "a.heic"
    f.write_bytes(b"x" * 100)
    os.utime(f, (time.time() - 999, time.time() - 999))

    settings = SimpleNamespace(drop_dir=drop, ingest_stable_seconds=STABLE)
    redis = _FakeRedis(decode)

    await scan(settings, redis)
    assert redis.h, "1차 스캔 뒤 관측 기록이 남아야 한다"

    # 2차 스캔에서도 기록이 살아 있어야 한다 (매번 지워지면 크기 비교가 무의미해진다)
    await scan(settings, redis)
    assert redis.h, "2차 스캔 뒤에도 기록이 유지돼야 한다"
    assert list(redis.h.values())[0] == "100"


@pytest.mark.asyncio
async def test_사라진_파일의_기록은_정리된다(tmp_path):
    from types import SimpleNamespace

    from poogiegram.ingest.scanner import scan

    drop = tmp_path / "drop"
    drop.mkdir()
    f = drop / "a.heic"
    f.write_bytes(b"x")
    settings = SimpleNamespace(drop_dir=drop, ingest_stable_seconds=STABLE)
    redis = _FakeRedis(False)

    await scan(settings, redis)
    assert redis.h
    f.unlink()
    await scan(settings, redis)
    assert not redis.h, "파일이 사라지면 기록도 지워져야 한다 (Redis 누수 방지)"
