"""사진 댓글 (§5.6).

권한 판정은 DB 없이 돈다. 삭제·계정 정리 시 댓글이 어떻게 되는지는 DB 가 필요하다.
  make test-db
"""

import datetime as dt
import os
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
import testdb
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from poogiegram.db import make_engine, make_sessionmaker
from poogiegram.models import AppUser, Asset, AssetTag, Comment, Tag
from poogiegram.routes_comments import can_delete, can_edit, normalize_body

ME = uuid.uuid4()
OTHER = uuid.uuid4()


def _user(uid, role="member"):
    return SimpleNamespace(id=uid, role=role)


def _comment(author_id):
    return SimpleNamespace(author_id=author_id)


# ── 권한 ─────────────────────────────────────────────────────────────


def test_본인_댓글은_고치고_지울_수_있다():
    assert can_edit(_user(ME), _comment(ME))
    assert can_delete(_user(ME), _comment(ME))


def test_남의_댓글은_고칠_수도_지울_수도_없다():
    assert not can_edit(_user(ME), _comment(OTHER))
    assert not can_delete(_user(ME), _comment(OTHER))


def test_admin은_지울_수는_있지만_고칠_수는_없다():
    """남의 말을 고치면 그 사람이 한 말이 아니게 된다."""
    admin = _user(ME, role="admin")
    assert can_delete(admin, _comment(OTHER))
    assert not can_edit(admin, _comment(OTHER))


def test_작성자가_사라진_댓글은_admin만_지운다():
    assert not can_edit(_user(ME), _comment(None))
    assert not can_delete(_user(ME), _comment(None))
    assert can_delete(_user(ME, role="admin"), _comment(None))


# ── 본문 ─────────────────────────────────────────────────────────────


def test_앞뒤_공백만_걷고_줄바꿈은_살린다():
    assert normalize_body("  이거 액자로\n뽑자  ") == "이거 액자로\n뽑자"


def test_공백뿐이면_거부한다():
    with pytest.raises(HTTPException) as exc:
        normalize_body("  \n ")
    assert exc.value.status_code == 400


# ── DB ───────────────────────────────────────────────────────────────


def needs_db(fn):
    """모듈 전체에 guard 를 걸면 위의 권한 테스트까지 DB 없이는 건너뛰게 된다."""
    for mark in testdb.guard():
        fn = mark(fn)
    return fn


async def _wipe(s):
    async with s.begin():
        for model in (Comment, AssetTag, Tag, Asset, AppUser):
            await s.execute(delete(model))


@pytest_asyncio.fixture
async def maker():
    engine = make_engine(os.environ["DATABASE_URL"])
    yield make_sessionmaker(engine)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(maker):
    async with maker() as s:
        await _wipe(s)
        async with s.begin():
            yield s


async def _seed(session):
    user = AppUser(username=f"u{uuid.uuid4().hex[:8]}", password_hash="x", display_name="엄마")
    now = dt.datetime(2026, 10, 26, 12, 0, 0)
    asset = Asset(
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        path="2026/10/26/a.jpg",
        original_filename="a.jpg",
        kind="image",
        taken_local=now,
        taken_at=now.replace(tzinfo=dt.timezone.utc),
        date_source="exif",
    )
    session.add_all([user, asset])
    await session.flush()
    comment = Comment(asset_id=asset.id, author_id=user.id, body="푸기 이때 진짜 작았네")
    session.add(comment)
    await session.flush()
    return user, asset, comment


@needs_db
async def test_휴지통에_보내도_댓글은_남는다(session):
    """복원하면 같이 돌아와야 한다. 소프트 삭제는 asset 행을 지우지 않는다."""
    _, asset, comment = await _seed(session)
    asset.deleted_at = dt.datetime.now(dt.timezone.utc)
    await session.flush()

    assert await session.get(Comment, comment.id) is not None


@needs_db
async def test_영구_삭제하면_댓글도_사라진다(session):
    _, asset, comment = await _seed(session)
    await session.execute(delete(Asset).where(Asset.id == asset.id))
    session.expunge_all()

    assert await session.scalar(select(Comment).where(Comment.id == comment.id)) is None


@needs_db
async def test_계정이_지워져도_댓글은_남는다(session):
    """대화의 한쪽만 사라지면 나머지 댓글이 무슨 말인지 알 수 없다."""
    user, _, comment = await _seed(session)
    await session.execute(delete(AppUser).where(AppUser.id == user.id))
    session.expunge_all()

    kept = await session.scalar(select(Comment).where(Comment.id == comment.id))
    assert kept is not None
    assert kept.author_id is None


@needs_db
async def test_빈_본문은_DB도_거부한다(session):
    """API 를 거치지 않는 경로(마이그레이션·CLI)에서도 빈 댓글이 생기면 안 된다."""
    user, asset, _ = await _seed(session)
    # 세이브포인트 안에서 실패시킨다. 바깥 트랜잭션이 깨지면 픽스처 정리가 터진다.
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(Comment(asset_id=asset.id, author_id=user.id, body=""))


# ── API ──────────────────────────────────────────────────────────────


@needs_db
async def test_API_작성_수정_삭제_흐름(maker, tmp_path):
    """권한 함수가 맞아도 라우트가 그걸 안 부르면 소용없다. 실제 요청으로 확인한다."""
    import httpx

    from poogiegram.deps import current_user
    from poogiegram.main import create_app

    # 라우트가 자기 세션으로 읽으므로 시드는 커밋까지 해 둔다
    async with maker() as s:
        await _wipe(s)
        async with s.begin():
            author, asset, _ = await _seed(s)
            other = AppUser(username=f"o{uuid.uuid4().hex[:8]}", password_hash="x", display_name="아빠")
            s.add(other)

    app = create_app(static_dir=tmp_path / "없음")
    app.state.sessionmaker = maker
    who = {"user": author}
    app.dependency_overrides[current_user] = lambda: who["user"]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        res = await client.post(f"/api/assets/{asset.id}/comments", json={"body": "  이거 액자로 뽑자 "})
        assert res.status_code == 201, res.text
        created = res.json()
        assert created["body"] == "이거 액자로 뽑자"
        assert created["author_name"] == "엄마"

        items = (await client.get(f"/api/assets/{asset.id}/comments")).json()["items"]
        assert [c["body"] for c in items] == ["푸기 이때 진짜 작았네", "이거 액자로 뽑자"]

        # 같은 내용으로 저장하면 "수정됨"이 붙지 않는다
        same = await client.patch(f"/api/comments/{created['id']}", json={"body": "이거 액자로 뽑자"})
        assert same.json()["edited_at"] is None
        changed = await client.patch(f"/api/comments/{created['id']}", json={"body": "액자로 뽑자!"})
        assert changed.json()["edited_at"] is not None

        who["user"] = other
        assert (await client.patch(f"/api/comments/{created['id']}", json={"body": "x"})).status_code == 403
        assert (await client.delete(f"/api/comments/{created['id']}")).status_code == 403

        who["user"] = author
        assert (await client.delete(f"/api/comments/{created['id']}")).status_code == 200

        # 휴지통 사진에는 보이지도 달리지도 않는다
        async with maker() as s, s.begin():
            trashed = await s.get(Asset, asset.id)
            trashed.deleted_at = dt.datetime.now(dt.timezone.utc)
        assert (await client.get(f"/api/assets/{asset.id}/comments")).status_code == 404
        assert (await client.post(f"/api/assets/{asset.id}/comments", json={"body": "a"})).status_code == 404
