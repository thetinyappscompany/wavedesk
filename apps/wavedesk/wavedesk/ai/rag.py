# Copyright (c) 2026, WaveDesk
# License: proprietary
"""RAG vector store over Qdrant (master doc §Phase 4 feature 3).

Workspace-scoped collections (one per workspace — tenant isolation at the vector
layer too). Thin HTTP client so it's dependency-light and easy to mock in tests.
Knowledge docs are chunked, embedded (embeddings.py → NVIDIA), and upserted with a
deterministic point id per (doc, chunk) so re-indexing is idempotent.
"""

import os
import uuid

from wavedesk.ai import embeddings

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333").rstrip("/")
TOP_K = 4
CHUNK_CHARS = 1000
CHUNK_OVERLAP = 150


def collection_name(workspace: str) -> str:
    return "wd_kb_" + workspace.lower().replace("-", "_")


def _qdrant(method: str, path: str, **kwargs) -> dict:
    import requests

    resp = requests.request(method, f"{QDRANT_URL}{path}", timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.json() if resp.text else {}


def ensure_collection(workspace: str, dim: int = embeddings.EMBED_DIM) -> str:
    """Create the workspace collection if it doesn't exist (idempotent)."""
    import requests

    coll = collection_name(workspace)
    try:
        _qdrant("GET", f"/collections/{coll}")
    except requests.HTTPError:
        _qdrant("PUT", f"/collections/{coll}", json={"vectors": {"size": dim, "distance": "Cosine"}})
    return coll


def chunk_text(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    step = max(1, CHUNK_CHARS - CHUNK_OVERLAP)
    i = 0
    while i < len(text):
        chunks.append(text[i : i + CHUNK_CHARS])
        i += step
    return chunks


def _point_id(doc: str, idx: int) -> str:
    # Deterministic UUID per (doc, chunk) so re-indexing overwrites, not duplicates.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc}:{idx}"))


def index_doc(workspace: str, doc: str, content: str) -> int:
    """Chunk → embed → upsert. Returns the chunk count."""
    chunks = chunk_text(content)
    if not chunks:
        delete_doc(workspace, doc)
        return 0
    coll = ensure_collection(workspace)
    vectors = embeddings.embed_texts(chunks, input_type="passage")
    points = [
        {"id": _point_id(doc, i), "vector": vec, "payload": {"doc": doc, "text": chunk}}
        for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True))
    ]
    _qdrant("PUT", f"/collections/{coll}/points?wait=true", json={"points": points})
    return len(chunks)


def delete_doc(workspace: str, doc: str) -> None:
    import requests

    coll = collection_name(workspace)
    try:
        _qdrant(
            "POST", f"/collections/{coll}/points/delete?wait=true",
            json={"filter": {"must": [{"key": "doc", "match": {"value": doc}}]}},
        )
    except requests.HTTPError:
        pass  # collection may not exist yet — nothing to delete


def search(workspace: str, query: str, top_k: int = TOP_K) -> list[dict]:
    """Return top-k chunks: [{text, doc, score}] (highest score first)."""
    import requests

    coll = collection_name(workspace)
    vec = embeddings.embed_texts([query], input_type="query")[0]
    try:
        res = _qdrant(
            "POST", f"/collections/{coll}/points/search",
            json={"vector": vec, "limit": top_k, "with_payload": True},
        )
    except requests.HTTPError:
        return []  # no collection / no knowledge yet
    return [
        {"text": h["payload"].get("text"), "doc": h["payload"].get("doc"), "score": h.get("score", 0.0)}
        for h in res.get("result", [])
    ]
