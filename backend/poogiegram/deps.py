"""요청 의존성.

인증은 **기본이 필수**다. 공개할 엔드포인트만 명시적으로 예외로 둔다 —
반대로 하면 새 라우터를 추가할 때 보호를 빠뜨려도 아무도 모른다.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select

from .auth import SESSION_COOKIE, read_session
from .models import AppUser


async def current_user(request: Request) -> AppUser:
    token = request.cookies.get(SESSION_COOKIE, "")
    user_id = await read_session(
        request.app.state.redis, token, request.app.state.settings.session_ttl_seconds
    )
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요합니다")

    async with request.app.state.sessionmaker() as session:
        user = await session.scalar(select(AppUser).where(AppUser.id == user_id))
    if user is None:
        # 세션은 살아 있는데 계정이 지워진 경우
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "계정을 찾을 수 없습니다")
    return user


async def require_admin(user: AppUser = Depends(current_user)) -> AppUser:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "관리자만 가능합니다")
    return user


def client_ip(request: Request) -> str:
    """호스트 nginx 가 앞에 있으므로 X-Forwarded-For 를 본다 (§3.2).

    맨 앞 값만 신뢰한다. 우리 nginx 가 붙이는 값이고, 그 앞에 다른 프록시는 없다.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
