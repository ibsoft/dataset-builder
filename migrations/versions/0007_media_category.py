"""Add a default media category without changing existing choices.

Revision ID: 0007_media_category
Revises: 0006_backups
"""
from alembic import op
import sqlalchemy as sa

revision = '0007_media_category'
down_revision = '0006_backups'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    existing = connection.execute(sa.text(
        "SELECT id FROM metadata_options WHERE field = :field AND value_key = :key"
    ), {'field': 'Category', 'key': 'media'}).first()
    if existing is None:
        position = connection.execute(sa.text(
            "SELECT MAX(position) FROM metadata_options WHERE field = :field"
        ), {'field': 'Category'}).scalar()
        connection.execute(sa.text(
            "INSERT INTO metadata_options (field, value, value_key, greek_label, position) "
            "VALUES (:field, :value, :key, :label, :position)"
        ), {'field': 'Category', 'value': 'Media', 'key': 'media',
            'label': 'Πολυμέσα', 'position': (position + 1 if position is not None else 0)})


def downgrade():
    # Preserve administrator-managed metadata choices and existing articles.
    pass
