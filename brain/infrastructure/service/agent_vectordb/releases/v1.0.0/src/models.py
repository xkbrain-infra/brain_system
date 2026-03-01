"""SQLAlchemy ORM models for brain_docs database."""

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column, Date, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True)
    domain = Column(String, nullable=False)       # spec, wf, knlg, evo
    scope = Column(String, nullable=False, default="G")
    category = Column(String, nullable=False)      # CORE, POLICY, STANDARD, ...
    title = Column(String, nullable=False)
    description = Column(Text)
    path = Column(String, nullable=False)
    content_hash = Column(String)                  # SHA256
    last_modified = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    tags = relationship("DocumentTag", back_populates="document", cascade="all, delete-orphan")
    keywords = relationship("DocumentKeyword", back_populates="document", cascade="all, delete-orphan")
    vector = relationship("DocumentVector", back_populates="document", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_documents_domain", "domain"),
        Index("idx_documents_category", "category"),
    )


class DocumentTag(Base):
    __tablename__ = "document_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    tag = Column(String, nullable=False)

    document = relationship("Document", back_populates="tags")

    __table_args__ = (
        UniqueConstraint("doc_id", "tag"),
        Index("idx_document_tags_tag", "tag"),
    )


class DocumentKeyword(Base):
    __tablename__ = "document_keywords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    keyword = Column(String, nullable=False)

    document = relationship("Document", back_populates="keywords")

    __table_args__ = (
        UniqueConstraint("doc_id", "keyword"),
        Index("idx_document_keywords_keyword", "keyword"),
    )


class DocumentVector(Base):
    __tablename__ = "document_vectors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True)
    embedding = Column(Vector(1024), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="vector")
