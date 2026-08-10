"""일괄 편집 — 태그 부여·해제, 삭제·복원, 태그 병합 (§5.3).

DB 가 필요하다.  make test-db
"""

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
import testdb
from sqlalchemy import delete, select

from poogiegram.db import make_engine, make_sessionmaker
from poogiegram.ingest.pipeline import attach_tags
from poogiegram.models import Asset, AssetTag, Tag
from poogiegram.routes_edit import _move

pytestmark = testdb.guard()


@pytest_asyncio.fixture
async def session():
    import os

    engine = make_engine(os.environ["DATABASE_URL"])
    maker = make_sessionmaker(engine)
    async with maker() as s:
        async with s.begin():
            await s.execute(delete(AssetTag))
            await s.execute(delete(Tag))
            await s.execute(delete(Asset))
        async with s.begin():
            yield s
    await engine.dispose()


def _asset(name: str) -> Asset:
    now = dt.datetime(2026, 8, 10, 12, 0, 0)
    return Asset(
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        path=f"2026/08/10/{name}",
        original_filename=name,
        kind="image",
        taken_local=now,
        taken_at=now.replace(tzinfo=dt.timezone.utc),
        date_source="exif",
    )


async def _add(session, asset):
    session.add(asset)
    await session.flush()
    return asset


async def _names(session, asset) -> set[str]:
    return set(
        (await session.scalars(
            select(Tag.name).join(AssetTag, AssetTag.tag_id == Tag.id)
            .where(AssetTag.asset_id == asset.id)
        )).all()
    )


async def test_같은_태그를_두_번_붙여도_터지지_않는다(session):
    """일괄 부여는 이미 붙은 사진이 섞인 채로 들어온다. PK 중복이 나면 안 된다."""
    a = await _add(session, _asset("a.jpg"))
    await attach_tags(session, a, ["결혼기념일"])

    existing = await _names(session, a)
    fresh = [n for n in ["결혼기념일", "푸기"] if n not in existing]
    await attach_tags(session, a, fresh)

    assert await _names(session, a) == {"결혼기념일", "푸기"}


async def test_태그는_사진들_사이에_공유된다(session):
    """전 구성원 공용이라 이름이 전역 unique 다 (§5.3)."""
    a = await _add(session, _asset("a.jpg"))
    b = await _add(session, _asset("b.jpg"))
    await attach_tags(session, a, ["푸기 생일"])
    await attach_tags(session, b, ["푸기 생일"])

    tags = (await session.scalars(select(Tag).where(Tag.name == "푸기 생일"))).all()
    assert len(tags) == 1, "같은 이름으로 태그가 두 개 생겼다"


async def test_태그_병합시_중복_자산이_생기지_않는다(session):
    """양쪽에 다 붙어 있던 사진은 옮기면 PK 가 겹친다 — 그 행은 지워야 한다."""
    from sqlalchemy import delete as sql_delete
    from sqlalchemy import update

    a = await _add(session, _asset("a.jpg"))
    await attach_tags(session, a, ["푸기생일", "푸기 생일"])   # 오타본과 정본 둘 다

    wrong = await session.scalar(select(Tag).where(Tag.name == "푸기생일"))
    right = await session.scalar(select(Tag).where(Tag.name == "푸기 생일"))

    both = select(AssetTag.asset_id).where(AssetTag.tag_id == right.id)
    await session.execute(
        update(AssetTag)
        .where(AssetTag.tag_id == wrong.id, AssetTag.asset_id.not_in(both))
        .values(tag_id=right.id)
    )
    await session.execute(sql_delete(AssetTag).where(AssetTag.tag_id == wrong.id))
    await session.flush()

    assert await _names(session, a) == {"푸기 생일"}


# ── 휴지통 경로 규약 (§5.3) ──────────────────────────────────────────


def test_휴지통은_같은_상대경로를_유지한다(tmp_path):
    """path 를 바꾸지 않고 루트만 다르게 해석한다. 복원은 역방향 이동 한 번이다."""
    originals = tmp_path / "originals"
    trash = tmp_path / "trash"
    rel = "2026/08/10/IMG_1.jpg"

    src = originals / rel
    src.parent.mkdir(parents=True)
    src.write_bytes(b"photo")

    _move(src, trash / rel)
    assert not src.exists()
    assert (trash / rel).read_bytes() == b"photo"

    _move(trash / rel, originals / rel)
    assert (originals / rel).read_bytes() == b"photo"
    assert not (trash / rel).exists()


def test_파일이_없어도_진행한다(tmp_path):
    """DB 상태를 못 바꾸는 것보다, 파일이 사라진 자산을 삭제 표시라도 하는 편이 낫다."""
    _move(tmp_path / "없음.jpg", tmp_path / "trash/없음.jpg")
