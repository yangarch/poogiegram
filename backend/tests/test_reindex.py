"""originals/ 에서 DB 를 복구하는 재색인 (§4.1).

**DB 를 잃어도 원본만 있으면 복구할 수 있어야 한다.** 파일명에 날짜와 해시를
넣어둔 것도 그 때문인데, 정작 실행할 도구가 없다가 실제로 DB 행을 날린 뒤에
만들었다. 그때 첫 실행이 AttributeError 로 죽었다 — 그래서 여기서 실제로
돌려본다.

DB 가 필요하다.  make test-db
"""

import datetime as dt

import pytest
import pytest_asyncio
import testdb
from PIL import Image
from sqlalchemy import delete, select

from poogiegram.db import make_engine, make_sessionmaker
from poogiegram.ingest.pipeline import reindex_all, reindex_file
from poogiegram.models import Asset

pytestmark = testdb.guard()



@pytest.fixture
def settings(tmp_path):
    """reindex 는 originals_dir 만 본다. 실제 Settings 를 만들 필요가 없다."""
    from types import SimpleNamespace

    originals = tmp_path / "originals"
    (originals / "2026/08/08").mkdir(parents=True)
    return SimpleNamespace(originals_dir=originals)


@pytest_asyncio.fixture
async def sessionmaker_():
    import os

    engine = make_engine(os.environ["DATABASE_URL"])
    maker = make_sessionmaker(engine)
    async with maker() as s:
        async with s.begin():
            await s.execute(delete(Asset))
    yield maker
    await engine.dispose()


def _photo(path, size=(48, 32)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (120, 90, 60)).save(path, format="JPEG")
    return path


async def test_originals_에서_DB_를_복구한다(sessionmaker_, settings):
    _photo(settings.originals_dir / "2026/08/08/a__deadbeef.jpg")
    _photo(settings.originals_dir / "2026/08/08/b__cafebabe.jpg")

    counts, new_ids = await reindex_all(sessionmaker_, settings)

    assert counts.get("reindexed") == 2, counts
    assert len(new_ids) == 2, "파생물을 큐에 넣으려면 id 가 필요하다"

    async with sessionmaker_() as session:
        rows = (await session.scalars(select(Asset))).all()
    assert {r.path for r in rows} == {
        "2026/08/08/a__deadbeef.jpg",
        "2026/08/08/b__cafebabe.jpg",
    }
    assert all(r.derive_status == "pending" for r in rows)


async def test_파일을_옮기지_않는다(sessionmaker_, settings):
    """경로를 다시 계산하면 이미 붙은 해시 접미사 위에 또 붙는다."""
    src = _photo(settings.originals_dir / "2026/08/08/keep__12345678.jpg")

    await reindex_all(sessionmaker_, settings)

    assert src.exists(), "원본이 사라졌다 — 재색인은 파일을 건드리면 안 된다"
    async with sessionmaker_() as session:
        row = await session.scalar(select(Asset))
    assert row.path == "2026/08/08/keep__12345678.jpg"


async def test_여러_번_돌려도_안전하다(sessionmaker_, settings):
    _photo(settings.originals_dir / "2026/08/08/dup__aaaaaaaa.jpg")

    first, ids = await reindex_all(sessionmaker_, settings)
    second, ids2 = await reindex_all(sessionmaker_, settings)

    assert first.get("reindexed") == 1 and len(ids) == 1
    assert second.get("reindexed") is None, "두 번째 실행은 등록할 것이 없어야 한다"
    assert second.get("duplicate") == 1
    assert ids2 == [], "이미 있는 자산의 파생물을 다시 큐에 넣지 않는다"


async def test_마커_파일은_건너뛴다(sessionmaker_, settings):
    """.poogiegram-ok 는 마운트 확인용이다 (§4.6). 자산이 아니다."""
    (settings.originals_dir / ".poogiegram-ok").write_text("")
    _photo(settings.originals_dir / "2026/08/08/real__bbbbbbbb.jpg")

    counts, _ = await reindex_all(sessionmaker_, settings)

    assert counts.get("reindexed") == 1, counts


async def test_읽을_수_없는_파일은_실패로_센다(sessionmaker_, settings):
    """전체가 멈추면 안 된다 — 나머지는 계속 등록돼야 한다."""
    broken = settings.originals_dir / "2026/08/08/broken__cccccccc.jpg"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("이건 JPEG 가 아니다")
    _photo(settings.originals_dir / "2026/08/08/ok__dddddddd.jpg")

    counts, new_ids = await reindex_all(sessionmaker_, settings)

    assert counts.get("reindexed") == 1
    assert counts.get("failed") == 1
    assert len(new_ids) == 1


async def test_재색인한_자산도_날짜가_채워진다(sessionmaker_, settings):
    """EXIF 가 없으면 파일 mtime 으로 떨어진다 (§6.7). 날짜가 비면 타임라인에서 사라진다."""
    src = _photo(settings.originals_dir / "2026/08/08/nodate__eeeeeeee.jpg")

    async with sessionmaker_() as session:
        async with session.begin():
            result = await reindex_file(session, settings, src)
            asset = await session.scalar(select(Asset).where(Asset.id == result.asset_id))
            assert asset.taken_local is not None
            assert asset.taken_at is not None
            assert asset.date_source in ("mtime", "filename", "exif", "sibling")
            assert isinstance(asset.taken_local, dt.datetime)
