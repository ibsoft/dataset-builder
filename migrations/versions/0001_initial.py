"""DatasetBuilder initial relational schema, including immutable version history.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('users',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('username',sa.String(80),nullable=False,unique=True),
        sa.Column('display_name',sa.String(160),nullable=False),
        sa.Column('password_hash',sa.String(255),nullable=False),
        sa.Column('role',sa.String(20),nullable=False),
        sa.Column('active',sa.Boolean(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.Column('last_login_at',sa.DateTime()),
        sa.Column('preferred_language',sa.String(2),nullable=False))
    op.create_table('documents',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('title',sa.String(240),nullable=False),
        sa.Column('slug',sa.String(260),nullable=False),
        sa.Column('markdown',sa.Text(),nullable=False),
        sa.Column('category',sa.String(120),nullable=False),
        sa.Column('knowledge_status',sa.String(60),nullable=False),
        sa.Column('product',sa.String(120),nullable=False),
        sa.Column('language',sa.String(40),nullable=False),
        sa.Column('created_by_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('updated_by_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.Column('updated_at',sa.DateTime(),nullable=False),
        sa.Column('deleted_at',sa.DateTime()),
        sa.Column('sync_error',sa.Text()))
    op.create_index('ix_documents_search_filters','documents',['deleted_at','knowledge_status','category'])
    op.create_table('document_revisions',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('document_id',sa.Integer(),sa.ForeignKey('documents.id',ondelete='CASCADE'),nullable=False),
        sa.Column('number',sa.Integer(),nullable=False),
        sa.Column('title',sa.String(240),nullable=False),
        sa.Column('slug',sa.String(260),nullable=False),
        sa.Column('markdown',sa.Text(),nullable=False),
        sa.Column('edited_by_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('action',sa.String(30),nullable=False),
        sa.Column('note',sa.String(500),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.UniqueConstraint('document_id','number',name='uq_doc_revision'))
    op.create_index('ix_document_revisions_document_id','document_revisions',['document_id'])
    op.create_table('audit_events',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('actor_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('document_id',sa.Integer(),sa.ForeignKey('documents.id',ondelete='SET NULL')),
        sa.Column('action',sa.String(50),nullable=False),
        sa.Column('details',sa.Text(),nullable=False),
        sa.Column('ip_address',sa.String(64)),
        sa.Column('created_at',sa.DateTime(),nullable=False))


def downgrade():
    op.drop_table('audit_events')
    op.drop_index('ix_document_revisions_document_id','document_revisions')
    op.drop_table('document_revisions')
    op.drop_index('ix_documents_search_filters','documents')
    op.drop_table('documents')
    op.drop_table('users')
