"""Query layer for brain_docs — 4 query types."""

import os
import re
from typing import Any

import httpx
from pgvector.sqlalchemy import Vector
from sqlalchemy import select, text, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import selectinload

from .models import Base, Document, DocumentTag, DocumentKeyword, DocumentVector

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@system-graph-db:5432/brain_docs")
EMBEDDING_URL = os.environ.get("EMBEDDING_URL", "http://lml-embedding:8001/v1/embeddings")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "bge-m3")

engine = create_async_engine(DATABASE_URL, pool_size=5, max_overflow=2)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _tokenize(text_input: str) -> list[str]:
    parts = re.split(r"[^0-9A-Za-z_\u4e00-\u9fff]+", text_input)
    return [p for p in parts if p]


def _doc_to_dict(doc: Document) -> dict[str, Any]:
    return {
        "id": doc.id,
        "domain": doc.domain,
        "scope": doc.scope,
        "category": doc.category,
        "title": doc.title,
        "description": doc.description,
        "path": doc.path,
        "last_modified": str(doc.last_modified) if doc.last_modified else None,
        "tags": [t.tag for t in doc.tags] if doc.tags else [],
        "keywords": [k.keyword for k in doc.keywords] if doc.keywords else [],
    }


async def _get_embedding(text_input: str) -> list[float] | None:
    """Get embedding from local lml-embedding service."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                EMBEDDING_URL,
                json={"input": [text_input], "model": EMBEDDING_MODEL},
            )
            resp.raise_for_status()
            data = resp.json()
            # Support both OpenAI format and lml-embedding format
            if "data" in data:
                return data["data"][0]["embedding"]
            elif "dense_embeddings" in data:
                return data["dense_embeddings"][0]["vector"]
            return None
    except Exception:
        return None


async def query_docs(
    keyword: str | None = None,
    domain: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Combined keyword/domain/category/tags query."""
    async with async_session() as session:
        stmt = select(Document).options(
            selectinload(Document.tags),
            selectinload(Document.keywords),
        )

        conditions = []
        if domain:
            conditions.append(Document.domain == domain)
        if category:
            conditions.append(Document.category == category.upper())
        if keyword:
            kw_like = f"%{keyword}%"
            conditions.append(or_(
                Document.title.ilike(kw_like),
                Document.description.ilike(kw_like),
                Document.id.ilike(kw_like),
            ))
        if conditions:
            stmt = stmt.where(and_(*conditions))

        if tags:
            stmt = stmt.join(Document.tags).where(DocumentTag.tag.in_(tags))

        stmt = stmt.distinct().limit(limit)
        result = await session.execute(stmt)
        docs = result.scalars().unique().all()
        return [_doc_to_dict(d) for d in docs]


async def get_doc_by_id(doc_id: str) -> dict[str, Any] | None:
    """Exact lookup by document ID."""
    async with async_session() as session:
        stmt = select(Document).options(
            selectinload(Document.tags),
            selectinload(Document.keywords),
        ).where(Document.id == doc_id)
        result = await session.execute(stmt)
        doc = result.scalar_one_or_none()
        return _doc_to_dict(doc) if doc else None


async def get_related(doc_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """Find related documents via vector similarity."""
    async with async_session() as session:
        # Get the source document's vector
        vec_stmt = select(DocumentVector.embedding).where(DocumentVector.doc_id == doc_id)
        vec_result = await session.execute(vec_stmt)
        source_vec = vec_result.scalar_one_or_none()
        if source_vec is None:
            return []

        # Find nearest neighbors (exclude self)
        stmt = (
            select(Document, DocumentVector.embedding.cosine_distance(source_vec).label("distance"))
            .join(DocumentVector, Document.id == DocumentVector.doc_id)
            .options(selectinload(Document.tags), selectinload(Document.keywords))
            .where(Document.id != doc_id)
            .order_by("distance")
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.all()
        return [
            {**_doc_to_dict(row[0]), "similarity": round(1.0 - float(row[1]), 4)}
            for row in rows
        ]


async def semantic_search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Semantic search using embedding similarity."""
    query_vec = await _get_embedding(query)
    if query_vec is None:
        return await _keyword_fallback_search(query=query, limit=limit)

    async with async_session() as session:
        stmt = (
            select(Document, DocumentVector.embedding.cosine_distance(query_vec).label("distance"))
            .join(DocumentVector, Document.id == DocumentVector.doc_id)
            .options(selectinload(Document.tags), selectinload(Document.keywords))
            .order_by("distance")
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.all()
        vector_results = [
            {**_doc_to_dict(row[0]), "similarity": round(1.0 - float(row[1]), 4)}
            for row in rows
        ]
        if vector_results:
            return vector_results
        return await _keyword_fallback_search(query=query, limit=limit)


async def _keyword_fallback_search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Fallback search when embedding/vector path is unavailable."""
    tokens = _tokenize(query)
    if not tokens and query.strip():
        tokens = [query.strip()]
    if not tokens:
        return []

    async with async_session() as session:
        conditions = []
        for tok in tokens[:8]:
            tok_like = f"%{tok}%"
            conditions.append(or_(
                Document.title.ilike(tok_like),
                Document.description.ilike(tok_like),
                Document.id.ilike(tok_like),
                Document.path.ilike(tok_like),
            ))

        stmt = (
            select(Document)
            .options(selectinload(Document.tags), selectinload(Document.keywords))
            .where(or_(*conditions))
            .limit(limit)
        )
        result = await session.execute(stmt)
        docs = result.scalars().unique().all()
        return [{**_doc_to_dict(doc), "similarity": None, "mode": "keyword_fallback"} for doc in docs]
