"""asset_tag 에 tag_id 선행 인덱스 추가

PK 는 (asset_id, tag_id) 라 tag_id 만으로는 인덱스를 못 탄다. 태그로 거르는 것이
주된 사용법인데(§5.5), 그대로 두면 사진이 늘수록 전체 훑기가 된다.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-09
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_asset_tag_by_tag', 'asset_tag', ['tag_id', 'asset_id'])


def downgrade() -> None:
    op.drop_index('ix_asset_tag_by_tag', table_name='asset_tag')
