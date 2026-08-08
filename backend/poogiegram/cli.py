"""관리 명령.

회원가입을 열지 않으므로(§8) 첫 계정은 여기서 만든다.

    python -m poogiegram.cli create-user <이메일> [--admin] [--name 이름]
    python -m poogiegram.cli passwd <이메일>
    python -m poogiegram.cli list-users
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import secrets
import string
import sys

from sqlalchemy import func, select

from . import auth
from .config import get_settings
from .db import make_engine, make_sessionmaker
from .models import AppUser

MIN_PASSWORD_LENGTH = 10


def _prompt_password() -> str:
    """비밀번호를 두 번 받아 확인한다. 비워두면 강한 값을 생성해 준다."""
    while True:
        pw = getpass.getpass("비밀번호 (엔터: 자동 생성): ")
        if not pw:
            alphabet = string.ascii_letters + string.digits
            pw = "".join(secrets.choice(alphabet) for _ in range(20))
            print(f"  생성된 비밀번호: {pw}")
            print("  이 값을 지금 안전한 곳에 옮겨 두세요. 다시 볼 수 없습니다.")
            return pw
        if len(pw) < MIN_PASSWORD_LENGTH:
            print(f"  {MIN_PASSWORD_LENGTH}자 이상이어야 합니다.")
            continue
        if pw != getpass.getpass("비밀번호 확인: "):
            print("  일치하지 않습니다.")
            continue
        return pw


async def _with_session(fn):
    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        maker = make_sessionmaker(engine)
        async with maker() as session:
            async with session.begin():
                return await fn(session)
    finally:
        await engine.dispose()


async def create_user(email: str, name: str | None, is_admin: bool) -> int:
    password = _prompt_password()

    async def run(session):
        existing = await session.scalar(
            select(AppUser).where(func.lower(AppUser.email) == email.lower())
        )
        if existing is not None:
            print(f"이미 존재하는 계정입니다: {email}", file=sys.stderr)
            return 1
        session.add(
            AppUser(
                email=email.lower(),
                password_hash=auth.hash_password(password),
                display_name=name or email.split("@")[0],
                role="admin" if is_admin else "member",
            )
        )
        print(f"생성됨: {email} ({'admin' if is_admin else 'member'})")
        return 0

    return await _with_session(run)


async def change_password(email: str) -> int:
    password = _prompt_password()

    async def run(session):
        user = await session.scalar(
            select(AppUser).where(func.lower(AppUser.email) == email.lower())
        )
        if user is None:
            print(f"계정을 찾을 수 없습니다: {email}", file=sys.stderr)
            return 1
        user.password_hash = auth.hash_password(password)
        print(f"비밀번호 변경됨: {email}")
        print("  기존 세션은 그대로 유효합니다. 끊으려면 로그아웃하거나 Redis 세션을 지우세요.")
        return 0

    return await _with_session(run)


async def list_users() -> int:
    async def run(session):
        users = (await session.scalars(select(AppUser).order_by(AppUser.created_at))).all()
        if not users:
            print("계정이 없습니다. create-user 로 관리자를 먼저 만드세요.")
            return 0
        for u in users:
            print(f"  {u.email:<32} {u.role:<7} {u.display_name}")
        return 0

    return await _with_session(run)


async def reindex() -> int:
    """originals/ 를 훑어 DB 에 없는 파일을 등록한다 (§4.1).

    DB 만 잃고 원본이 남은 상황의 복구 수단이다. 파일은 옮기지 않는다.
    """
    from arq import create_pool
    from arq.connections import RedisSettings

    from .ingest.pipeline import reindex_all

    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        maker = make_sessionmaker(engine)
        counts, new_ids = await reindex_all(maker, settings)
    finally:
        await engine.dispose()

    if not counts:
        print("originals/ 에 파일이 없습니다.")
        return 0

    # 파생물 작업을 바로 큐에 넣는다. 주기 스캔에 맡기면 최대 5분 동안
    # "등록은 됐는데 화면은 그대로"가 된다.
    if new_ids:
        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            for asset_id in new_ids:
                await redis.enqueue_job("derive_asset", asset_id)
        finally:
            await redis.aclose()

    for event, n in sorted(counts.items()):
        print(f"  {event:<10} {n}")
    if new_ids:
        print(f"\n파생물 {len(new_ids)}건을 큐에 넣었습니다. 진행 상황:  make status-derive")
    return 1 if counts.get("failed") else 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="poogiegram.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user", help="계정 생성")
    p.add_argument("email")
    p.add_argument("--name", help="표시 이름 (기본: 이메일 로컬파트)")
    p.add_argument("--admin", action="store_true", help="관리자 권한")

    p = sub.add_parser("passwd", help="비밀번호 변경")
    p.add_argument("email")

    sub.add_parser("list-users", help="계정 목록")
    sub.add_parser("reindex", help="originals/ 를 훑어 DB 에 없는 파일을 등록 (복구용)")

    args = parser.parse_args()
    if args.command == "create-user":
        return asyncio.run(create_user(args.email, args.name, args.admin))
    if args.command == "passwd":
        return asyncio.run(change_password(args.email))
    if args.command == "reindex":
        return asyncio.run(reindex())
    return asyncio.run(list_users())


if __name__ == "__main__":
    raise SystemExit(main())
