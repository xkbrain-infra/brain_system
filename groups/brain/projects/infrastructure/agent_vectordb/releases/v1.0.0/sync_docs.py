#!/usr/bin/env python3
"""Sync docs/code into brain_docs vector DB.

Coverage:
- /xkagent_infra/brain/base/{spec,workflow,knowledge,evolution,skills}
- /root/.codex/skills
- /xkagent_infra/groups/** (spec/docs/memory/src and common text/code files)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import httpx
import yaml
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

import sys
sys.path.insert(0, "/xkagent_infra/brain/infrastructure/service/agent_vectordb/releases/v1.0.0")

from src.models import Document, DocumentKeyword, DocumentTag, DocumentVector
from src.queries import EMBEDDING_MODEL, EMBEDDING_URL, async_session

TEXT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".yaml", ".yml", ".json", ".toml",
    ".ini", ".cfg", ".conf", ".py", ".sh", ".bash", ".zsh", ".sql",
    ".c", ".h", ".cpp", ".hpp", ".js", ".ts", ".tsx", ".jsx", ".go",
    ".rs", ".java", ".kt", ".swift", ".rb", ".php", ".proto", ".xml",
    ".csv", ".env", ".dockerfile",
}

SKIP_DIR_NAMES = {
    ".git", "__pycache__", "node_modules", "venv", ".venv", "dist", "build",
    "releases", "snapshots", ".archive", ".archived", "target",
}

MAX_FILE_SIZE_BYTES = 512 * 1024
EMBED_BATCH_SIZE = 6


@dataclass
class DocRecord:
    doc_id: str
    domain: str
    scope: str
    category: str
    title: str
    description: str
    path: str
    content_hash: str
    last_modified: date
    tags: list[str]
    keywords: list[str]
    embed_text: str


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _stable_auto_id(domain: str, path: str) -> str:
    digest = hashlib.sha1(path.encode("utf-8", errors="ignore")).hexdigest()[:14].upper()
    return f"AUTO-{domain.upper()}-{digest}"


def _tokenize(text: str) -> list[str]:
    parts = re.split(r"[^0-9A-Za-z_\u4e00-\u9fff]+", text)
    return [p.lower() for p in parts if p and len(p) >= 2]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _extract_title(path: Path, content: str) -> str:
    if content:
        for line in content.splitlines():
            s = line.strip()
            if s.startswith("#"):
                return s.lstrip("#").strip()[:200]
            if s.lower().startswith("title:"):
                return s.split(":", 1)[1].strip().strip('"\'')[:200]
    return path.name


def _extract_description(content: str, fallback: str) -> str:
    if not content:
        return fallback
    for line in content.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        return s[:300]
    return fallback


def _guess_group_category(path: str) -> str:
    if "/spec/" in path:
        return "GROUP_SPEC"
    if "/docs/" in path:
        return "GROUP_DOC"
    if "/memory/" in path:
        return "GROUP_MEMORY"
    if "/src/" in path:
        return "CODE"
    return "GROUP_FILE"


def _domain_for_path(path: str) -> str:
    if path.startswith("/xkagent_infra/brain/base/spec/"):
        return "spec"
    if path.startswith("/xkagent_infra/brain/base/workflow/"):
        return "wf"
    if path.startswith("/xkagent_infra/brain/base/knowledge/"):
        return "knlg"
    if path.startswith("/xkagent_infra/brain/base/evolution/"):
        return "evo"
    if "/skills/" in path:
        return "skill"
    if path.startswith("/xkagent_infra/groups/"):
        return "group"
    return "misc"


def _scope_for_path(path: str) -> str:
    if path.startswith("/xkagent_infra/groups/"):
        return "GROUP"
    if "/skills/" in path:
        return "SKILL"
    return "G"


def _category_for_path(path: str) -> str:
    if path.startswith("/xkagent_infra/brain/base/spec/"):
        return "SPEC"
    if path.startswith("/xkagent_infra/brain/base/workflow/"):
        return "WORKFLOW"
    if path.startswith("/xkagent_infra/brain/base/knowledge/"):
        return "KNOWLEDGE"
    if path.startswith("/xkagent_infra/brain/base/evolution/"):
        return "EVOLUTION"
    if "/skills/" in path:
        return "SKILL"
    if path.startswith("/xkagent_infra/groups/"):
        return _guess_group_category(path)
    return "MISC"


def _iter_files(roots: list[Path], max_files: int) -> Iterable[Path]:
    count = 0
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES and not d.startswith(".")]
            for filename in filenames:
                if count >= max_files:
                    return
                ext = Path(filename).suffix.lower()
                if ext not in TEXT_EXTENSIONS and filename.lower() != "dockerfile":
                    continue
                p = Path(dirpath) / filename
                if p.is_symlink() or not p.is_file():
                    continue
                try:
                    if p.stat().st_size > MAX_FILE_SIZE_BYTES:
                        continue
                except OSError:
                    continue
                count += 1
                yield p


def _load_registry_docs() -> dict[str, dict[str, Any]]:
    registry_files = [
        Path("/xkagent_infra/brain/base/spec/registry.yaml"),
        Path("/xkagent_infra/brain/base/workflow/registry.yaml"),
        Path("/xkagent_infra/brain/base/knowledge/registry.yaml"),
        Path("/xkagent_infra/brain/base/evolution/registry.yaml"),
    ]
    by_path: dict[str, dict[str, Any]] = {}
    for rf in registry_files:
        if not rf.exists():
            continue
        data = yaml.safe_load(rf.read_text(encoding="utf-8")) or {}
        docs = ((data.get("registry") or {}).get("documents") or {})
        for _k, v in docs.items():
            p = v.get("path")
            if not p:
                continue
            by_path[p] = v
    return by_path


def _build_record(path: Path, registry_docs: dict[str, dict[str, Any]]) -> DocRecord | None:
    abs_path = str(path.resolve())
    try:
        content = _read_text(path)
    except Exception:
        return None

    stat = path.stat()
    content_hash = _sha256_text(content)
    domain = _domain_for_path(abs_path)
    scope = _scope_for_path(abs_path)
    category = _category_for_path(abs_path)

    reg = registry_docs.get(abs_path)
    if reg:
        doc_id = reg.get("id") or _stable_auto_id(domain, abs_path)
        title = reg.get("title") or _extract_title(path, content)
        description = reg.get("description") or _extract_description(content, abs_path)
        tags = [str(t).lower() for t in (reg.get("tags") or [])]
        category = str(reg.get("category") or category).upper()
        scope = str(reg.get("scope") or scope)
    else:
        doc_id = _stable_auto_id(domain, abs_path)
        title = _extract_title(path, content)
        description = _extract_description(content, f"{abs_path} [{domain}]")
        tags = []

    ext = path.suffix.lower().lstrip(".") or "text"
    path_parts = [p.lower() for p in path.parts[-6:]]
    tags.extend([domain, category.lower(), ext])
    tags.extend([p for p in path_parts if p not in {"brain", "base", "groups", "org"} and len(p) > 2])

    raw_keywords = _tokenize(" ".join([title, description, path.name] + tags))
    keywords = list(dict.fromkeys(raw_keywords))[:25]
    tags = sorted({t for t in tags if t and len(t) >= 2})[:30]

    # Keep embedding payload compact to avoid embedding service stalls on long source files.
    embed_source = f"{title}\n{description}\n\n{content[:1800]}"

    return DocRecord(
        doc_id=doc_id,
        domain=domain,
        scope=scope,
        category=category,
        title=title[:300],
        description=description[:1000],
        path=abs_path,
        content_hash=content_hash,
        last_modified=date.fromtimestamp(stat.st_mtime),
        tags=tags,
        keywords=keywords,
        embed_text=embed_source,
    )


async def _embed_one(client: httpx.AsyncClient, text: str) -> list[float] | None:
    try:
        resp = await client.post(
            EMBEDDING_URL,
            json={"input": [text], "model": EMBEDDING_MODEL},
        )
        resp.raise_for_status()
    except Exception:
        return None

    data = resp.json()
    if "data" in data and data["data"]:
        return data["data"][0].get("embedding")
    if "dense_embeddings" in data and data["dense_embeddings"]:
        return data["dense_embeddings"][0].get("vector")
    return None


async def _embed_batch(texts: list[str]) -> list[list[float] | None]:
    async with httpx.AsyncClient(timeout=45.0) as client:
        tasks = [_embed_one(client, t) for t in texts]
        return await asyncio.gather(*tasks)


async def sync_docs(max_files: int, with_embeddings: bool, prune: bool) -> dict[str, Any]:
    roots = [
        Path("/xkagent_infra/brain/base/spec"),
        Path("/xkagent_infra/brain/base/workflow"),
        Path("/xkagent_infra/brain/base/knowledge"),
        Path("/xkagent_infra/brain/base/evolution"),
        Path("/xkagent_infra/brain/base/skills"),
        Path("/root/.codex/skills"),
        Path("/xkagent_infra/groups"),
    ]
    registry_docs = _load_registry_docs()

    records: list[DocRecord] = []
    for file_path in _iter_files(roots=roots, max_files=max_files):
        rec = _build_record(file_path, registry_docs)
        if rec is not None:
            records.append(rec)

    if not records:
        return {"scanned": 0, "upserted": 0, "embedded": 0, "pruned": 0}

    embeddings: dict[str, list[float]] = {}
    if with_embeddings:
        for i in range(0, len(records), EMBED_BATCH_SIZE):
            batch = records[i:i + EMBED_BATCH_SIZE]
            vecs = await _embed_batch([r.embed_text for r in batch])
            for rec, vec in zip(batch, vecs):
                if vec is not None:
                    embeddings[rec.doc_id] = vec

    async with async_session() as session:
        for rec in records:
            doc_payload = {
                "id": rec.doc_id,
                "domain": rec.domain,
                "scope": rec.scope,
                "category": rec.category,
                "title": rec.title,
                "description": rec.description,
                "path": rec.path,
                "content_hash": rec.content_hash,
                "last_modified": rec.last_modified,
            }

            stmt = pg_insert(Document).values(**doc_payload)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Document.id],
                set_=doc_payload,
            )
            await session.execute(stmt)

            await session.execute(delete(DocumentTag).where(DocumentTag.doc_id == rec.doc_id))
            await session.execute(delete(DocumentKeyword).where(DocumentKeyword.doc_id == rec.doc_id))

            if rec.tags:
                tag_stmt = pg_insert(DocumentTag).on_conflict_do_nothing(
                    index_elements=[DocumentTag.doc_id, DocumentTag.tag]
                )
                await session.execute(tag_stmt, [{"doc_id": rec.doc_id, "tag": t} for t in rec.tags])
            if rec.keywords:
                kw_stmt = pg_insert(DocumentKeyword).on_conflict_do_nothing(
                    index_elements=[DocumentKeyword.doc_id, DocumentKeyword.keyword]
                )
                await session.execute(kw_stmt, [{"doc_id": rec.doc_id, "keyword": k} for k in rec.keywords])

            vec = embeddings.get(rec.doc_id)
            if vec is not None:
                vstmt = pg_insert(DocumentVector).values(doc_id=rec.doc_id, embedding=vec)
                vstmt = vstmt.on_conflict_do_update(
                    index_elements=[DocumentVector.doc_id],
                    set_={"embedding": vec},
                )
                await session.execute(vstmt)

        pruned = 0
        if prune:
            managed_roots = ["/xkagent_infra/brain/base/%", "/xkagent_infra/groups/%", "/root/.codex/skills/%"]
            managed_cond = (
                Document.path.like(managed_roots[0]) |
                Document.path.like(managed_roots[1]) |
                Document.path.like(managed_roots[2])
            )
            seen_ids = [r.doc_id for r in records]
            prune_stmt = delete(Document).where(managed_cond)
            if seen_ids:
                prune_stmt = prune_stmt.where(~Document.id.in_(seen_ids))
            result = await session.execute(prune_stmt)
            pruned = result.rowcount or 0

        await session.commit()

    return {
        "scanned": len(records),
        "upserted": len(records),
        "embedded": len(embeddings),
        "pruned": pruned,
    }


async def _main_async(args: argparse.Namespace) -> None:
    result = await sync_docs(
        max_files=args.max_files,
        with_embeddings=not args.no_embeddings,
        prune=not args.no_prune,
    )
    print(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync brain docs/code into vector DB")
    parser.add_argument("--max-files", type=int, default=8000)
    parser.add_argument("--no-embeddings", action="store_true")
    parser.add_argument("--no-prune", action="store_true")
    args = parser.parse_args()

    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
