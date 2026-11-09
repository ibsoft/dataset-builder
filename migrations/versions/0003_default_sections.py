"""Store administrator-managed default sections.

Revision ID: 0003_default_sections
Revises: 0002_user_theme
"""
from alembic import op
import sqlalchemy as sa

revision = '0003_default_sections'
down_revision = '0002_user_theme'
branch_labels = None
depends_on = None


def upgrade():
    sections = op.create_table(
        'default_sections',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('title_key', sa.String(400), nullable=False, unique=True),
        sa.Column('greek_label', sa.String(120), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
    )
    defaults = [
        ('PROBLEM DESCRIPTION', 'Περιγραφή προβλήματος'),
        ('POSSIBLE SYMPTOMS', 'Πιθανά συμπτώματα'),
        ('TOTALCARE MESSAGES', 'Μηνύματα TotalCare'),
        ('POSSIBLE CAUSES', 'Πιθανές αιτίες'),
        ('DIAGNOSTIC PROCEDURE', 'Διαγνωστική διαδικασία'),
        ('CORRECTIVE ACTIONS', 'Διορθωτικές ενέργειες'),
        ('VERIFICATION', 'Επαλήθευση'),
        ('REQUIRED INFORMATION FOR FURTHER DIAGNOSIS', 'Απαιτούμενες πληροφορίες'),
        ('RELATED QUESTIONS', 'Σχετικές ερωτήσεις'),
    ]
    op.bulk_insert(sections, [
        {'title': title, 'title_key': title.casefold(), 'greek_label': greek, 'position': position}
        for position, (title, greek) in enumerate(defaults)
    ])


def downgrade():
    op.drop_table('default_sections')
