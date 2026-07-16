"""RAG — workspace-scoped Qdrant collections + NVIDIA embeddings (thin HTTP).
Env: QDRANT_URL, NVIDIA_API_KEY, WD_EMBED_DIM."""

import hashlib
import os
import uuid

import httpx

CHUNK_CHARS = 1000
TOP_K = 4


def _qdrant_url() -> str:
    return (os.environ.get("QDRANT_URL") or "http://localhost:6333").rstrip("/")


def _qdrant(method: str, path: str, json: dict | None = None) -> dict:
    resp = httpx.request(method, _qdrant_url() + path, json=json, timeout=30)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def collection_name(workspace_id) -> str:
    return f"wd_{str(workspace_id).replace('-', '')}"


def embed_texts(texts: list[str], input_type: str = "passage") -> list[list[float]]:
    key = os.environ.get("NVIDIA_API_KEY")
    if not key:
        raise RuntimeError("NVIDIA_API_KEY unset")
    resp = httpx.post(
        (os.environ.get("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1")
        + "/embeddings",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "input": texts,
            "model": os.environ.get("WD_EMBED_MODEL") or "nvidia/nv-embedqa-e5-v5",
            "input_type": "query" if input_type == "query" else "passage",
        },
        timeout=60,
    )
    resp.raise_for_status()
    return [d["embedding"] for d in resp.json()["data"]]


def chunk_text(text: str) -> list[str]:
    text = text or ""
    return [text[i:i + CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)] if text else []


def _point_id(doc: str, idx: int) -> str:
    return str(uuid.UUID(hashlib.md5(f"{doc}:{idx}".encode()).hexdigest()))


def ensure_collection(workspace_id, dim: int) -> str:
    coll = collection_name(workspace_id)
    try:
        _qdrant("GET", f"/collections/{coll}")
    except httpx.HTTPStatusError:
        _qdrant("PUT", f"/collections/{coll}",
                {"vectors": {"size": dim, "distance": "Cosine"}})
    return coll


def index_doc(workspace_id, doc: str, content: str) -> int:
    chunks = chunk_text(content)
    if not chunks:
        return 0
    vectors = embed_texts(chunks, "passage")
    coll = ensure_collection(workspace_id, len(vectors[0]))
    _qdrant("PUT", f"/collections/{coll}/points?wait=true", {
        "points": [
            {"id": _point_id(doc, i), "vector": vectors[i],
             "payload": {"doc": doc, "text": chunks[i]}}
            for i in range(len(chunks))
        ],
    })
    return len(chunks)


def search(workspace_id, query: str, top_k: int = TOP_K) -> list[dict]:
    vector = embed_texts([query], "query")[0]
    coll = collection_name(workspace_id)
    res = _qdrant("POST", f"/collections/{coll}/points/search",
                  {"vector": vector, "limit": top_k, "with_payload": True})
    return [
        {"text": h["payload"].get("text"), "doc": h["payload"].get("doc"), "score": h["score"]}
        for h in res.get("result", [])
    ]


def delete_doc(workspace_id, doc: str) -> None:
    coll = collection_name(workspace_id)
    _qdrant("POST", f"/collections/{coll}/points/delete?wait=true",
            {"filter": {"must": [{"key": "doc", "match": {"value": doc}}]}})
