# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Text embeddings for RAG (master doc §Phase 4 feature 3).

Anthropic has no embeddings API, so the embedding tier uses the NVIDIA
OpenAI-compatible endpoint (the founder's "keep both" — NVIDIA scoped to
embeddings). Pooled key from env only (NVIDIA_API_KEY); never committed.
Isolated + lazy so tests monkeypatch without network.
"""

import os

import frappe

NVIDIA_BASE = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
EMBED_MODEL = os.environ.get("WAVEDESK_EMBED_MODEL", "nvidia/nv-embedqa-e5-v5")
EMBED_DIM = int(os.environ.get("WAVEDESK_EMBED_DIM", "1024"))


def embed_texts(texts: list[str], input_type: str = "passage") -> list[list[float]]:
    """Embed a batch. input_type is 'passage' (documents) or 'query' (search) —
    nv-embedqa models are asymmetric and need the right one."""
    if not texts:
        return []
    key = os.environ.get("NVIDIA_API_KEY")
    if not key:
        frappe.throw("No embeddings key configured (NVIDIA_API_KEY unset).")
    import requests

    resp = requests.post(
        f"{NVIDIA_BASE}/embeddings",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": EMBED_MODEL, "input": texts, "input_type": input_type},
        timeout=60,
    )
    resp.raise_for_status()
    return [row["embedding"] for row in resp.json()["data"]]
