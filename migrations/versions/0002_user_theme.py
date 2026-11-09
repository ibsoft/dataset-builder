"""Add the per-user interface theme preference.

Revision ID: 0002_user_theme
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_user_theme'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users',
        sa.Column('preferred_theme',sa.String(5),nullable=False,server_default='dark'))


def downgrade():
    op.drop_column('users','preferred_theme')
