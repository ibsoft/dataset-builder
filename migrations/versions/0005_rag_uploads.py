"""Add RAG gateway configuration and upload tracking."""
from alembic import op
import sqlalchemy as sa

revision = '0005_rag_uploads'
down_revision = '0004_metadata_options'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'rag_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('gateway_url', sa.String(500), nullable=False),
        sa.Column('token_url', sa.String(500), nullable=False),
        sa.Column('tenant_id', sa.String(255), nullable=False),
        sa.Column('client_id', sa.String(255), nullable=False),
        sa.Column('secret_ciphertext', sa.Text(), nullable=False),
        sa.Column('subjects', sa.Text(), nullable=False),
    )
    op.create_table(
        'rag_uploads',
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('documents.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('destination', sa.String(64), nullable=False),
        sa.Column('remote_document_id', sa.String(36)),
        sa.Column('remote_version_id', sa.String(36)),
        sa.Column('revision', sa.Integer()),
        sa.Column('metadata_json', sa.Text(), nullable=False),
        sa.Column('subjects_hash', sa.String(64), nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('state', sa.String(30), nullable=False),
        sa.Column('error', sa.String(500), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table('rag_uploads')
    op.drop_table('rag_settings')
