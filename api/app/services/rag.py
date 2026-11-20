"""RAG layer: GST rule passages are embedded once and searched for every ITC decision.
Engine: Gemini embeddings when GEMINI_API_KEY is set, otherwise a local hashing embedding.
On AlloyDB the embedding column is a pgvector column and the search is `ORDER BY embedding <=> $1 LIMIT k`."""
from __future__ import annotations

import math
import re
import zlib

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import LegalChunk
from app.services import gemini, vertex_search
from app.services.util import rules_config, rules_passages

DIM = 768  # same size as the vector(768) column on AlloyDB
STOP = set("a an and are as at be by for from has have in is it of on or that the this to was were will with which any such".split())


def _tokens(text: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


def local_embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for t in _tokens(text):
        vec[zlib.crc32(t.encode()) % DIM] += 1.0
    vec = [math.log1p(v) for v in vec]
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def current_engine() -> str:
    return "gemini-embedding" if gemini.enabled() else "local-hash"


_LAST = {"vertex": None}  # whether the last search really ran on Vertex AI Search (None = not searched yet)


def backend_name() -> str:
    if vertex_search.enabled() and _LAST["vertex"] is not False:
        return "Google Cloud Vertex AI Search (managed RAG)"
    return current_engine()


def embed_many(texts: list[str], engine: str) -> list[list[float]]:
    if engine == "gemini-embedding":
        return gemini.embed(texts)
    return [local_embed(t) for t in texts]


def ensure_rules_loaded(db: Session) -> dict:
    """Load passages from the rules file and (re)embed any that use a different engine than the current one."""
    engine = current_engine()
    existing = {c.id: c for c in db.query(LegalChunk).all()}
    changed = 0
    for p in rules_passages():
        row = existing.get(p["id"])
        if row is None:
            row = LegalChunk(id=p["id"], citation=p["citation"], topic=p["topic"], body=p["body"], tags=p["tags"])
            db.add(row)
            existing[p["id"]] = row
        else:
            row.citation, row.topic, row.body, row.tags = p["citation"], p["topic"], p["body"], p["tags"]
        if not row.embedding or row.embed_engine != engine:
            text = f"{row.topic}. {row.body}"
            try:
                row.embedding = embed_many([text], engine)[0]
                row.embed_engine = engine
            except Exception:  # Gemini failed: keep working with the local engine
                row.embedding = local_embed(text)
                row.embed_engine = "local-hash"
            changed += 1
    db.commit()
    return {"passages": len(existing), "embedded_now": changed, "engine": engine}


_VCACHE: dict[tuple[str, int], list[dict]] = {}  # the rule passages do not change, so a query text always gets the same answer


def _vertex_many(texts: list[str], k: int) -> list[list[dict]]:
    """One Vertex AI Search call per DISTINCT query text (many invoices share the same rule query), in parallel, cached for the process."""
    from concurrent.futures import ThreadPoolExecutor
    todo = [t for t in dict.fromkeys(texts) if (t, k) not in _VCACHE]
    if todo:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for t, res in zip(todo, pool.map(lambda x: vertex_search.search(x, k), todo)):
                _VCACHE[(t, k)] = res
    return [_VCACHE[(t, k)] for t in texts]


def search_many(db: Session, queries: list[dict]) -> list[list[dict]]:
    """queries: [{"text": str, "tags": [str]}]. Returns top-k passages per query with scores.
    Hybrid score = cosine similarity + a small boost when the passage tag matches the rule tag."""
    cfg = rules_config()
    k = cfg["top_k"]
    if vertex_search.enabled():  # managed Google search; any failure falls through to the local engine below
        try:
            found = _vertex_many([q["text"] for q in queries], k)
            if all(found):
                _LAST["vertex"] = True
                return found
        except Exception:  # noqa: BLE001
            pass
        _LAST["vertex"] = False
    chunks = db.query(LegalChunk).all()
    if not chunks or not queries:
        return [[] for _ in queries]
    by_engine: dict[str, list[list[float]]] = {}
    for eng in {c.embed_engine for c in chunks}:
        try:
            by_engine[eng] = embed_many([q["text"] for q in queries], eng)
        except Exception:
            by_engine[eng] = [local_embed(q["text"]) for q in queries]
    out = []
    for i, q in enumerate(queries):
        scored = []
        for c in chunks:
            qv = by_engine[c.embed_engine][i]
            if len(qv) != len(c.embedding or []):
                continue
            cos = cosine(qv, c.embedding)
            boost = 0.2 if set(q.get("tags", [])) & set(c.tags or []) else 0.0
            scored.append({"id": c.id, "citation": c.citation, "topic": c.topic, "body": c.body,
                           "score": round(cos + boost, 4), "cosine": round(cos, 4), "engine": c.embed_engine})
        scored.sort(key=lambda x: x["score"], reverse=True)
        out.append(scored[:k])
    return out


def search(db: Session, text: str, tags: list[str] | None = None) -> list[dict]:
    return search_many(db, [{"text": text, "tags": tags or []}])[0]
