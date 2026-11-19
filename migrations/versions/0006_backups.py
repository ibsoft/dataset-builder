"""Add backup scheduling and retention settings."""
from alembic import op
import sqlalchemy as sa

revision = '0006_backups'
down_revision = '0005_rag_uploads'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'backup_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('schedule', sa.String(10), nullable=False, server_default='manual'),
        sa.Column('schedule_time', sa.String(5), nullable=False, server_default='02:00'),
        sa.Column('schedule_weekday', sa.Integer(), nullable=False, server_default='6'),
        sa.Column('max_backups', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('last_run_at', sa.DateTime()),
        sa.Column('last_scheduled_key', sa.String(16)),
        sa.Column('last_error', sa.String(500), nullable=False, server_default=''),
    )
    op.execute(
        "INSERT INTO backup_settings "
        "(id, schedule, schedule_time, schedule_weekday, max_backups, last_error) "
        "VALUES (1, 'manual', '02:00', 6, 10, '')"
    )


def downgrade():
    op.drop_table('backup_settings')
