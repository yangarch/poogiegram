"""인증 (§8).

세션 쿠키 + Redis 저장. JWT 를 쓰지 않는 이유는 이 규모에서 **로그아웃과 세션 강제 만료가
번거로워지기** 때문이다. 서버가 하나이고 Redis 가 이미 있으므로 세션 조회 비용은 무의미하다.

회원가입은 열지 않는다. admin 이 계정을 발급한다.
"""

from __future__ import annotations

import logging
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

log = logging.getLogger("poogiegram.auth")

_ph = PasswordHasher()

SESSION_COOKIE = "pg_session"
SESSION_PREFIX = "session:"
LOGIN_FAIL_PREFIX = "login:fail:"

# 로그인 실패 허용치. 인터넷에 노출되면 무차별 대입 시도를 받는다.
MAX_LOGIN_FAILURES = 10
LOGIN_BLOCK_SECONDS = 900

# 존재하지 않는 계정으로 로그인해도 검증 비용을 치르게 해, 응답 시간으로
# 계정 존재 여부를 알아내지 못하게 한다.
_DUMMY_HASH = _ph.hash("timing-attack-mitigation")


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(stored_hash: str | None, plain: str) -> bool:
    """계정이 없어도 같은 비용을 치른다."""
    try:
        _ph.verify(stored_hash or _DUMMY_HASH, plain)
        return stored_hash is not None
    except (VerifyMismatchError, VerificationError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """argon2 파라미터가 바뀌었을 때 로그인 시점에 조용히 갱신하기 위한 것."""
    return _ph.check_needs_rehash(stored_hash)


# ── 세션 ────────────────────────────────────────────────────────────


async def create_session(redis, user_id: str, ttl_seconds: int) -> str:
    token = secrets.token_urlsafe(32)
    await redis.set(f"{SESSION_PREFIX}{token}", str(user_id), ex=ttl_seconds)
    return token


async def read_session(redis, token: str, ttl_seconds: int) -> str | None:
    """유효하면 user_id 를 돌려주고 만료 시각을 연장한다(슬라이딩)."""
    if not token:
        return None
    key = f"{SESSION_PREFIX}{token}"
    user_id = await redis.get(key)
    if user_id is None:
        return None
    await redis.expire(key, ttl_seconds)
    return user_id.decode() if isinstance(user_id, bytes) else user_id


async def destroy_session(redis, token: str) -> None:
    if token:
        await redis.delete(f"{SESSION_PREFIX}{token}")


async def destroy_all_sessions(redis, user_id: str) -> int:
    """계정의 모든 세션을 끊는다. 비밀번호 변경·계정 정지에 쓴다.

    JWT 였다면 만료를 기다리거나 블랙리스트를 따로 둬야 하는 지점이다.
    """
    removed = 0
    async for key in redis.scan_iter(match=f"{SESSION_PREFIX}*", count=500):
        value = await redis.get(key)
        if value is None:
            continue
        if (value.decode() if isinstance(value, bytes) else value) == str(user_id):
            await redis.delete(key)
            removed += 1
    return removed


# ── 무차별 대입 억제 ────────────────────────────────────────────────


async def is_blocked(redis, ip: str) -> bool:
    raw = await redis.get(f"{LOGIN_FAIL_PREFIX}{ip}")
    return raw is not None and int(raw) >= MAX_LOGIN_FAILURES


async def record_failure(redis, ip: str) -> None:
    key = f"{LOGIN_FAIL_PREFIX}{ip}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, LOGIN_BLOCK_SECONDS)


async def clear_failures(redis, ip: str) -> None:
    await redis.delete(f"{LOGIN_FAIL_PREFIX}{ip}")
