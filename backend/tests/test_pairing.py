"""라이브 포토 페어링 검증 (§6.5).

DB 가 필요하다. DATABASE_URL 이 없으면 건너뛴다.
    DATABASE_URL=postgresql+asyncpg://... pytest tests/test_pairing.py

exiftool 로 픽스처를 만들려 했으나 **비-Apple 파일에는 MediaGroupUUID /
ContentIdentifier 를 써넣지 못한다.** 그래서 메타데이터 추출은 건너뛰고
페어링 로직 자체를 DB 행으로 검증한다.
"""

import datetime as dt
import os
import uuid
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from sqlalchemy import delete

from poogiegram.db import make_engine, make_sessionmaker
from poogiegram.ingest.pipeline import _pair_live_photo
from poogiegram.models import Asset

DB_URL = os.environ.get("DATABASE_URL")

# **이 파일은 asset 테이블을 통째로 비운다.** 운영 DB 를 가리킨 채 돌리면 사진이
# 전부 사라진다. 실제로 그렇게 날렸다 — make test 가 앱 컨테이너에서 돌면서
# 운영 DATABASE_URL 을 그대로 물려받았고, 자산 행이 지워졌다.
# (원본 파일은 남아 있어 cli reindex 로 복구했다.)
#
# 그래서 DB 이름으로 한 번 더 막는다. Makefile 이 실수로 되돌아가도 여기서 걸린다.
_TEST_DB_SUFFIX = "_test"


def _is_test_db(url: str) -> bool:
    """DB 이름이 _test 로 끝나야 파괴적 테스트를 허용한다."""
    name = urlsplit(url).path.lstrip("/").split("?")[0]
    return name.endswith(_TEST_DB_SUFFIX)


pytestmark = [
    pytest.mark.skipif(not DB_URL, reason="DATABASE_URL 미설정"),
    pytest.mark.skipif(
        bool(DB_URL) and not _is_test_db(DB_URL),
        reason=(
            "DATABASE_URL 이 테스트용 DB 가 아닙니다. 이 테스트는 asset 테이블을 비웁니다 — "
            f"DB 이름이 '{_TEST_DB_SUFFIX}' 로 끝나야 실행합니다. (make test-db)"
        ),
    ),
]

CID = "0191DCC6-51E8-452F-9829-3F21FE2E39EA"


@pytest_asyncio.fixture
async def session():
    engine = make_engine(DB_URL)
    maker = make_sessionmaker(engine)
    async with maker() as s:
        async with s.begin():
            await s.execute(delete(Asset))
        async with s.begin():
            yield s
    await engine.dispose()


def _asset(name, kind, content_id=CID, **kw):
    now = dt.datetime(2026, 8, 8, 15, 27, 48)
    return Asset(
        sha256=(uuid.uuid4().hex + uuid.uuid4().hex),   # 64자
        path=f"2026/08/08/{name}",
        original_filename=name,
        kind=kind,
        taken_local=now,
        taken_at=now.replace(tzinfo=dt.timezone.utc),
        date_source="exif",
        content_id=content_id,
        **kw,
    )


async def _add(session, asset):
    session.add(asset)
    await session.flush()
    return asset


async def test_정지컷_먼저_도착한_경우(session):
    still = await _add(session, _asset("IMG_1.HEIC", "image"))
    await _pair_live_photo(session, still)          # 짝이 없어 아무 일도 없어야 한다
    assert still.live_motion_id is None

    motion = await _add(session, _asset("IMG_1.mov", "video"))
    await _pair_live_photo(session, motion)

    assert motion.is_live_motion is True, "MOV 는 타임라인에서 숨겨져야 한다"
    assert still.live_motion_id == motion.id


async def test_MOV_가_먼저_도착한_경우(session):
    """드롭 폴더에서는 도착 순서가 정해져 있지 않다."""
    motion = await _add(session, _asset("IMG_2.mov", "video"))
    await _pair_live_photo(session, motion)
    assert motion.is_live_motion is True

    still = await _add(session, _asset("IMG_2.HEIC", "image"))
    await _pair_live_photo(session, still)
    assert still.live_motion_id == motion.id


async def test_사진앱_내보내기_JPEG_도_같은_UUID_를_갖는다(session):
    """실측으로 확인한 사실 — HEIC·JPEG·MOV 셋이 한 UUID 를 공유한다.

    "같은 ID 면 전부 한 묶음"으로 처리하면 JPEG 가 영상으로 오인될 수 있다.
    영상은 하나뿐이고 정지컷 여럿이 그것을 가리키는 형태여야 한다.
    """
    heic = await _add(session, _asset("IMG_3.HEIC", "image"))
    jpeg = await _add(session, _asset("IMG_3_o.jpeg", "image"))
    motion = await _add(session, _asset("IMG_3.mov", "video"))
    await _pair_live_photo(session, motion)

    assert motion.is_live_motion is True
    assert heic.is_live_motion is False, "정지컷은 타임라인에 남아야 한다"
    assert jpeg.is_live_motion is False
    assert heic.live_motion_id == motion.id
    assert jpeg.live_motion_id == motion.id


async def test_content_id_가_없으면_아무_일도_없다(session):
    a = await _add(session, _asset("plain.jpg", "image", content_id=None))
    b = await _add(session, _asset("other.mov", "video", content_id=None))
    await _pair_live_photo(session, b)
    assert a.live_motion_id is None and b.is_live_motion is False


async def test_다른_UUID_는_묶이지_않는다(session):
    still = await _add(session, _asset("A.HEIC", "image", content_id="AAAA"))
    motion = await _add(session, _asset("B.mov", "video", content_id="BBBB"))
    await _pair_live_photo(session, motion)
    assert still.live_motion_id is None


async def test_삭제된_자산과는_묶이지_않는다(session):
    still = await _add(
        session, _asset("gone.HEIC", "image", deleted_at=dt.datetime.now(dt.timezone.utc))
    )
    motion = await _add(session, _asset("gone.mov", "video"))
    await _pair_live_photo(session, motion)
    assert still.live_motion_id is None


# ── 동시 인제스트 보정 ───────────────────────────────────────────────


async def test_동시_인제스트로_누락된_짝을_보정한다(session):
    """파일마다 별도 트랜잭션이라 동시에 들어오면 서로를 못 본다.

    실제로 HEIC·JPEG·MOV 를 한꺼번에 넣었을 때 JPEG 만 연결되지 않았다.
    각자 커밋 전이라 조회에 걸리지 않았기 때문이다.
    """
    from poogiegram.ingest.pipeline import repair_pairings

    # 페어링 없이 들어온 상태를 만든다 (동시 인제스트의 결과)
    heic = await _add(session, _asset("IMG_9.HEIC", "image"))
    jpeg = await _add(session, _asset("IMG_9_o.jpeg", "image"))
    motion = await _add(session, _asset("IMG_9.mov", "video"))
    assert motion.is_live_motion is False and heic.live_motion_id is None

    n = await repair_pairings(session)

    assert n == 3, "영상 1건 + 정지컷 2건이 보정돼야 한다"
    assert motion.is_live_motion is True
    assert heic.live_motion_id == motion.id
    assert jpeg.live_motion_id == motion.id


async def test_보정은_멱등이다(session):
    from poogiegram.ingest.pipeline import repair_pairings

    await _add(session, _asset("IMG_A.HEIC", "image"))
    await _add(session, _asset("IMG_A.mov", "video"))
    assert await repair_pairings(session) == 2
    assert await repair_pairings(session) == 0, "이미 정리된 뒤에는 할 일이 없어야 한다"


async def test_짝없는_영상도_숨김_처리된다(session):
    """정지컷이 아직 안 왔어도 동반 클립은 타임라인에 노출되면 안 된다."""
    from poogiegram.ingest.pipeline import repair_pairings

    motion = await _add(session, _asset("lonely.mov", "video"))
    await repair_pairings(session)
    assert motion.is_live_motion is True
