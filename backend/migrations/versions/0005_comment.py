"""comment 테이블 — 사진에 다는 댓글 (§5.6)

asset.caption 은 그대로 둔다. caption 은 사진의 설명이고 댓글은 누가 언제 했는지가
의미의 일부인 대화라, 한 컬럼에 섞으면 둘 중 하나를 잃는다.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'comment',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('asset_id', sa.Uuid(), nullable=False),
        sa.Column('author_id', sa.Uuid(), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('char_length(body) BETWEEN 1 AND 1000', name='ck_comment_body'),
        sa.ForeignKeyConstraint(['asset_id'], ['asset.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_id'], ['app_user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_comment_asset', 'comment', ['asset_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_comment_asset', table_name='comment')
    op.drop_table('comment')
