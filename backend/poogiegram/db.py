"""엔진·세션 팩토리. API·워커·Alembic 이 공유한다."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> AsyncEngine:
    # pool_pre_ping: 컨테이너 재시작이나 네트워크 끊김 뒤 죽은 커넥션을 잡는다.
    return create_async_engine(url, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
