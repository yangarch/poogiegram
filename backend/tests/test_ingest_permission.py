"""권한 때문에 못 읽는 파일은 격리하지 않는다 (§6.1 — 일시적 실패와 영구적 실패).

맥에서 600 인 사진을 sftp 로 올리면 서버에서도 600 이 되어 워커가 못 읽는다.
호스트 타이머가 권한을 고치므로 drop/ 에 남아 있어야 다음 스캔에서 처리된다.
실제로 격리돼서 failed/ 에서 손으로 되살려야 했다.

테스트는 root 로 도는 경우가 많아 chmod 로는 읽기를 막을 수 없다. 해시 계산에서
PermissionError 를 내게 바꿔 끼운다. DB 에 닿기 전에 끝나므로 DB 가 필요 없다.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

from poogiegram.ingest import pipeline


class _Session:
    @asynccontextmanager
    async def begin(self):
        yield self

    def add(self, _):
        raise AssertionError("권한 대기는 ingest_log 에 남기지 않는다")


@asynccontextmanager
async def _sessionmaker():
    yield _Session()


def _settings(tmp_path):
    return SimpleNamespace(failed_dir=tmp_path / "incoming" / "failed")


async def test_권한이_없으면_drop에_남긴다(tmp_path, monkeypatch):
    src = tmp_path / "incoming" / "drop" / "IMG_1059.JPG"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"jpeg")

    def denied(_path):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(pipeline, "sha256_of", denied)

    result = await pipeline.ingest_one(_sessionmaker, _settings(tmp_path), src)

    assert result.event == "deferred"
    assert src.exists(), "drop/ 에 남아 있어야 타이머가 권한을 고친 뒤 처리된다"
    assert not (tmp_path / "incoming" / "failed").exists()


async def test_권한이_아닌_읽기_오류는_격리한다(tmp_path, monkeypatch):
    """깨진 디스크 블록 같은 진짜 파일 문제까지 붙잡아 두면 드롭 폴더가 막힌다."""
    src = tmp_path / "incoming" / "drop" / "broken.jpg"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")

    def io_error(_path):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(pipeline, "sha256_of", io_error)

    @asynccontextmanager
    async def maker():
        s = _Session()
        s.add = lambda _: None   # 격리 기록은 남긴다
        yield s

    result = await pipeline.ingest_one(maker, _settings(tmp_path), src)

    assert result.event == "failed"
    assert not src.exists()
    assert (tmp_path / "incoming" / "failed" / "broken.jpg").exists()
