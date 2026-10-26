"""사진 댓글 (§5.6).

읽기는 §5.2 그대로 모두가 전부 본다. 쓰기만 작성자 기준이다 — 사진은 올린 사람의
것이 아니지만(owner_id 는 권한이 아니다), 댓글은 말한 사람의 것이다.

목록·작성은 사진 아래(`/api/assets/{id}/comments`), 수정·삭제는 댓글 자체
(`/api/comments/{id}`)에 둔다. 수정·삭제에 사진 id 까지 받으면 두 id 가 어긋나는
경우를 따로 검사해야 한다.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from .deps import current_user
from .models import COMMENT_BODY_MAX, AppUser, Asset, Comment

router = APIRouter(tags=["comments"], dependencies=[Depends(current_user)])


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=COMMENT_BODY_MAX)


def normalize_body(raw: str) -> str:
    """앞뒤 공백만 걷는다. 줄바꿈은 살린다 — 태그 이름과 달리 문장이다."""
    body = raw.strip()
    if not body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "내용이 비어 있습니다")
    return body


def can_edit(user: AppUser, comment: Comment) -> bool:
    """본인만. 남의 말을 고치면 그 사람이 한 말이 아니게 된다."""
    return comment.author_id == user.id


def can_delete(user: AppUser, comment: Comment) -> bool:
    """본인 + admin. 잘못 단 것을 정리할 사람이 있어야 한다."""
    return comment.author_id == user.id or user.role == "admin"


def _serialize(c: Comment, author_name: str | None) -> dict:
    return {
        "id": str(c.id),
        "body": c.body,
        "author_id": str(c.author_id) if c.author_id else None,
        # 계정이 지워졌으면 비어 있다. 화면이 "알 수 없음"으로 그린다.
        "author_name": author_name,
        "created_at": c.created_at.isoformat(),
        "edited_at": c.edited_at.isoformat() if c.edited_at else None,
    }


async def _live_asset(session, asset_id: uuid.UUID) -> None:
    """휴지통 사진에는 댓글을 보이지도 달지도 않는다. 사진 자체가 404 다."""
    found = await session.scalar(
        select(Asset.id).where(Asset.id == asset_id, Asset.deleted_at.is_(None))
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "사진을 찾지 못했습니다")


async def _author_name(session, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    return await session.scalar(select(AppUser.display_name).where(AppUser.id == user_id))


@router.get("/api/assets/{asset_id}/comments")
async def list_comments(asset_id: uuid.UUID, request: Request) -> dict:
    """오래된 것부터. 대화는 위에서 아래로 읽힌다."""
    async with request.app.state.sessionmaker() as session:
        await _live_asset(session, asset_id)
        rows = (
            await session.execute(
                select(Comment, AppUser.display_name)
                .outerjoin(AppUser, AppUser.id == Comment.author_id)
                .where(Comment.asset_id == asset_id)
                .order_by(Comment.created_at, Comment.id)
            )
        ).all()
    return {"items": [_serialize(c, name) for c, name in rows]}


@router.post("/api/assets/{asset_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(
    asset_id: uuid.UUID,
    body: CommentIn,
    request: Request,
    user: AppUser = Depends(current_user),
) -> dict:
    text = normalize_body(body.body)
    async with request.app.state.sessionmaker() as session:
        async with session.begin():
            await _live_asset(session, asset_id)
            comment = Comment(asset_id=asset_id, author_id=user.id, body=text)
            session.add(comment)
            await session.flush()
            await session.refresh(comment)
    return _serialize(comment, user.display_name)


async def _get_comment(session, comment_id: uuid.UUID) -> Comment:
    comment = await session.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "댓글을 찾지 못했습니다")
    return comment


@router.patch("/api/comments/{comment_id}")
async def edit_comment(
    comment_id: uuid.UUID,
    body: CommentIn,
    request: Request,
    user: AppUser = Depends(current_user),
) -> dict:
    text = normalize_body(body.body)
    async with request.app.state.sessionmaker() as session:
        async with session.begin():
            comment = await _get_comment(session, comment_id)
            if not can_edit(user, comment):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "본인 댓글만 고칠 수 있습니다")
            # 내용이 같으면 "수정됨"을 붙이지 않는다. 저장만 다시 눌러도 표시가 생기면
            # 대화가 바뀐 것처럼 보인다.
            if comment.body != text:
                comment.body = text
                comment.edited_at = dt.datetime.now(dt.timezone.utc)
            name = await _author_name(session, comment.author_id)
    return _serialize(comment, name)


@router.delete("/api/comments/{comment_id}")
async def delete_comment(
    comment_id: uuid.UUID,
    request: Request,
    user: AppUser = Depends(current_user),
) -> dict:
    async with request.app.state.sessionmaker() as session:
        async with session.begin():
            comment = await _get_comment(session, comment_id)
            if not can_delete(user, comment):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "본인 댓글만 지울 수 있습니다")
            await session.delete(comment)
    return {"ok": True}
