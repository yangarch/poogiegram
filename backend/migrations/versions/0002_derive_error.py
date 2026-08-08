"""asset.derive_error 추가

파생물 생성이 실패해도 이유가 남지 않아, 원인을 보려면 워커 컨테이너 로그를
뒤져야 했다. 로그는 재시작하면 잘리고 시간이 지나면 사라진다.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('asset', sa.Column('derive_error', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('asset', 'derive_error')
