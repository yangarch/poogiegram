import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

# 모델을 임포트해야 Base.metadata 가 채워진다 (autogenerate 에 필요)
from poogiegram import models  # noqa: F401
from poogiegram.db import Base

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

# 접속 정보는 환경변수에서만 받는다. alembic.ini 에 URL 을 적어두면
# 비밀번호가 저장소에 들어간다.
url = os.environ.get("DATABASE_URL")
if not url:
    raise RuntimeError("DATABASE_URL 이 설정되지 않았습니다")
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # 컬럼 타입 변경도 감지한다
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
