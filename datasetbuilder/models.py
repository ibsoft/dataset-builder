"""Database tables: article contents and immutable revisions are the source of truth."""
from datetime import datetime, timezone
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Index, UniqueConstraint
from werkzeug.security import generate_password_hash, check_password_hash


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


db = SQLAlchemy()


class RagSettings(db.Model):
    __tablename__ = "rag_settings"
    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    gateway_url = db.Column(db.String(500), nullable=False, default="https://ai-gateway.unixfor.gr")
    token_url = db.Column(db.String(500), nullable=False, default="")
    tenant_id = db.Column(db.String(255), nullable=False, default="")
    client_id = db.Column(db.String(255), nullable=False, default="")
    secret_ciphertext = db.Column(db.Text, nullable=False, default="")
    subjects = db.Column(db.Text, nullable=False, default="")


class RagUpload(db.Model):
    __tablename__ = "rag_uploads"
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    destination = db.Column(db.String(64), nullable=False)
    remote_document_id = db.Column(db.String(36))
    remote_version_id = db.Column(db.String(36))
    revision = db.Column(db.Integer)
    metadata_json = db.Column(db.Text, nullable=False, default="{}")
    subjects_hash = db.Column(db.String(64), nullable=False, default="")
    checksum = db.Column(db.String(64), nullable=False, default="")
    state = db.Column(db.String(30), nullable=False, default="not_uploaded")
    error = db.Column(db.String(500), nullable=False, default="")
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    document = db.relationship("Document", backref=db.backref("rag_upload", uselist=False, lazy="select"))


class MetadataOption(db.Model):
    __tablename__ = "metadata_options"
    __table_args__ = (UniqueConstraint("field", "value_key", name="uq_metadata_option_field_key"),)
    id = db.Column(db.Integer, primary_key=True)
    field = db.Column(db.String(40), nullable=False)
    value = db.Column(db.String(120), nullable=False)
    value_key = db.Column(db.String(400), nullable=False)
    greek_label = db.Column(db.String(120), nullable=False)
    position = db.Column(db.Integer, nullable=False)


class DefaultSection(db.Model):
    __tablename__ = "default_sections"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    title_key = db.Column(db.String(400), nullable=False, unique=True)
    greek_label = db.Column(db.String(120), nullable=False)
    position = db.Column(db.Integer, nullable=False)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True)
    display_name = db.Column(db.String(160), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="editor")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_login_at = db.Column(db.DateTime)
    preferred_language = db.Column(db.String(2), nullable=False, default="en")
    preferred_theme = db.Column(db.String(5), nullable=False, default="dark")

    @property
    def is_active(self):
        return self.active

    def set_password(self, password):
        if len(password) < 12:
            raise ValueError("Password must be at least 12 characters")
        self.password_hash = generate_password_hash(password, method="scrypt")

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def can_edit(self):
        return self.role in ("admin", "editor")

    def is_admin(self):
        return self.role == "admin"


class Document(db.Model):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_search_filters", "deleted_at", "knowledge_status", "category"),)
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(240), nullable=False)
    slug = db.Column(db.String(260), nullable=False)
    markdown = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(120), nullable=False, default="General")
    knowledge_status = db.Column(db.String(60), nullable=False, default="Draft")
    product = db.Column(db.String(120), nullable=False, default="TotalCare")
    language = db.Column(db.String(40), nullable=False, default="English")
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    deleted_at = db.Column(db.DateTime)
    sync_error = db.Column(db.Text)
    created_by = db.relationship("User", foreign_keys=[created_by_id], lazy="joined")
    updated_by = db.relationship("User", foreign_keys=[updated_by_id], lazy="joined")
    versions = db.relationship("DocumentRevision", back_populates="document", order_by="DocumentRevision.number.desc()")

    @property
    def kb_id(self):
        from flask import current_app
        return f"{current_app.config['KB_PREFIX']}-{self.id:0{current_app.config['KB_PADDING']}d}"

    @property
    def filename(self):
        return f"{self.kb_id}-{self.slug}.md"


class DocumentRevision(db.Model):
    __tablename__ = "document_revisions"
    __table_args__ = (UniqueConstraint("document_id", "number", name="uq_doc_revision"),)
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(240), nullable=False)
    slug = db.Column(db.String(260), nullable=False)
    markdown = db.Column(db.Text, nullable=False)
    edited_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    action = db.Column(db.String(30), nullable=False, default="update")
    note = db.Column(db.String(500), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    document = db.relationship("Document", back_populates="versions")
    edited_by = db.relationship("User", lazy="joined")


class AuditEvent(db.Model):
    __tablename__ = "audit_events"
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    details = db.Column(db.Text, nullable=False, default="")
    ip_address = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    actor = db.relationship("User", lazy="joined")
