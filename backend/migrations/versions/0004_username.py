"""app_user.email → username

이메일은 로그인 식별자로만 쓰였다. 비밀번호 재설정도 알림도 없어서, 가족이 쓰는
서비스에서 매번 이메일을 치는 것은 마찰일 뿐이었다.

기존 값은 @ 앞부분으로 옮긴다 — 계정이 사라지면 로그인할 수 없게 되므로 지우지
않는다. 겹치면 뒤에 숫자를 붙인다.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('app_user', 'email', new_column_name='username',
                    existing_type=sa.String(320))

    # 이메일을 아이디로 바꾼다. 로컬파트만 남기고 쓸 수 없는 문자는 없앤다.
    # 32자 제한을 걸기 전에 줄여야 한다.
    op.execute(r"""
        UPDATE app_user
           SET username = left(
                 regexp_replace(lower(split_part(username, '@', 1)), '[^a-z0-9._-]', '', 'g'),
                 32)
    """)
    # 로컬파트가 겹치는 계정이 있을 수 있다 (a@x.com, a@y.com). unique 를 걸기 전에
    # 중복을 풀어둔다 — 안 그러면 마이그레이션이 제약 위반으로 멈춘다.
    op.execute("""
        UPDATE app_user u
           SET username = left(u.username, 30) || d.rn::text
          FROM (SELECT id, row_number() OVER (PARTITION BY username ORDER BY created_at) AS rn
                  FROM app_user) d
         WHERE u.id = d.id AND d.rn > 1
    """)
    # 빈 문자열이 되어버린 경우 (이메일이 기호뿐이었던 극단적 경우)
    op.execute("UPDATE app_user SET username = 'user' || left(id::text, 8) WHERE username = ''")

    op.alter_column('app_user', 'username',
                    existing_type=sa.String(320), type_=sa.String(32))


def downgrade() -> None:
    op.alter_column('app_user', 'username', existing_type=sa.String(32), type_=sa.String(320))
    op.alter_column('app_user', 'username', new_column_name='email', existing_type=sa.String(320))
