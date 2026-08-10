"""로그인·로그아웃 (§8)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select

from . import auth
from .deps import client_ip, current_user
from .models import AppUser

log = logging.getLogger("poogiegram.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    role: str


def _set_cookie(response: Response, token: str, request: Request) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,          # JS 에서 읽히지 않게 — XSS 로 세션이 새는 것을 막는다
        samesite="lax",         # 교차 사이트 POST 에 쿠키가 실리지 않아 CSRF 를 억제한다
        secure=settings.cookie_secure,
        path="/",
    )


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> UserOut:
    redis = request.app.state.redis
    ip = client_ip(request)

    if await auth.is_blocked(redis, ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요.",
        )

    async with request.app.state.sessionmaker() as session:
        user = await session.scalar(
            select(AppUser).where(func.lower(AppUser.username) == body.username.lower())
        )
        # 계정이 없어도 검증 비용을 치른다 — 응답 시간으로 계정 존재를 알아내지 못하게.
        valid = auth.verify_password(user.password_hash if user else None, body.password)

        if not valid or user is None:
            await auth.record_failure(redis, ip)
            log.warning("로그인 실패: %s (%s)", body.username, ip)
            # 어느 쪽이 틀렸는지 알려주지 않는다
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이메일 또는 비밀번호가 올바르지 않습니다")

        if auth.needs_rehash(user.password_hash):
            user.password_hash = auth.hash_password(body.password)
            await session.commit()

    await auth.clear_failures(redis, ip)
    token = await auth.create_session(redis, user.id, request.app.state.settings.session_ttl_seconds)
    _set_cookie(response, token, request)
    log.info("로그인: %s (%s)", user.username, ip)
    return UserOut(id=str(user.id), username=user.username, display_name=user.display_name, role=user.role)


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(auth.SESSION_COOKIE, "")
    await auth.destroy_session(request.app.state.redis, token)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: AppUser = Depends(current_user)) -> UserOut:
    return UserOut(id=str(user.id), username=user.username, display_name=user.display_name, role=user.role)
