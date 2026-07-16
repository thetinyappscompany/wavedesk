# Temporary live-verification probe — run via:
#   bench --site dev.localhost execute wavedesk._live_probe.run
# Deleted after the go-live verification pass; never ships.
import urllib.request


def run():
    from wavedesk.ai import transcription
    from wavedesk.pipeline import media_store

    results = []

    # --- 1. MinIO media round-trip through the real code path ---
    client = media_store._client()
    assert client is not None, "S3 client unconfigured (boto3/env)"
    key = "media/LIVE-PROBE/roundtrip-check"
    payload = b"wavedesk-live-probe-bytes"
    client.put_object(
        Bucket=media_store.media_bucket(), Key=key, Body=payload,
        ContentType="application/octet-stream",
    )
    url = media_store.presigned_url(key)
    assert url, "presign returned None"
    assert urllib.request.urlopen(url, timeout=10).read() == payload, "presigned GET mismatch"
    assert media_store.download_bytes(key) == payload, "download_bytes mismatch"
    client.delete_object(Bucket=media_store.media_bucket(), Key=key)
    results.append("media-roundtrip")

    # --- 2. Voice note: real speech WAV -> S3 -> whisper transcription ---
    wav = open("/mnt/d/wave/.probe_voice.wav", "rb").read()
    vkey = "media/LIVE-PROBE/voice-note"
    client.put_object(
        Bucket=media_store.media_bucket(), Key=vkey, Body=wav, ContentType="audio/wav"
    )
    audio = media_store.download_bytes(vkey)
    assert audio == wav, "S3 voice fetch mismatch"
    text = transcription.transcribe_bytes(audio, "audio/wav")
    client.delete_object(Bucket=media_store.media_bucket(), Key=vkey)
    assert text, "whisper returned no text"
    lowered = text.lower()
    assert "voice note" in lowered or "wave" in lowered, f"unexpected transcript: {text!r}"
    results.append(f"whisper-transcript={text!r}")

    print("LIVE-PROBE-PASS ::", " | ".join(results))


def run_qdrant():
    """Qdrant round-trip via rag.py's own HTTP layer (synthetic vectors — the
    NVIDIA embedding call is exercised separately once the key is in env)."""
    from wavedesk.ai import rag

    ws = "LIVE-PROBE-WS"
    coll = rag.ensure_collection(ws, dim=4)
    rag._qdrant(
        "PUT", f"/collections/{coll}/points?wait=true",
        json={"points": [
            {"id": rag._point_id("doc-a", 0), "vector": [1.0, 0.0, 0.0, 0.0],
             "payload": {"doc": "doc-a", "text": "alpha chunk"}},
            {"id": rag._point_id("doc-b", 0), "vector": [0.0, 1.0, 0.0, 0.0],
             "payload": {"doc": "doc-b", "text": "beta chunk"}},
        ]},
    )
    res = rag._qdrant(
        "POST", f"/collections/{coll}/points/search",
        json={"vector": [0.95, 0.05, 0.0, 0.0], "limit": 1, "with_payload": True},
    )
    hits = res.get("result", [])
    assert hits and hits[0]["payload"]["doc"] == "doc-a", f"wrong hit: {hits}"
    rag.delete_doc(ws, "doc-a")
    res2 = rag._qdrant(
        "POST", f"/collections/{coll}/points/search",
        json={"vector": [0.95, 0.05, 0.0, 0.0], "limit": 1, "with_payload": True},
    )
    assert res2["result"][0]["payload"]["doc"] == "doc-b", "delete_doc did not remove doc-a"
    rag._qdrant("DELETE", f"/collections/{coll}")
    print(
        "QDRANT-PROBE-PASS :: ensure_collection + upsert + cosine search "
        "+ delete_doc, collection dropped"
    )


def run_wallet():
    """Runbook check: a retried charge (same idempotency key) never double-debits.
    Runs on the real DB inside a rolled-back transaction — no residue."""
    import frappe

    from wavedesk.wallet import ledger

    ws = frappe.get_all("WD Workspace", limit=1, pluck="name")
    assert ws, "no workspace on this site"
    ws = ws[0]
    try:
        ledger.credit(ws, 100.0, "live-probe", "probe-credit-1")
        ledger.credit(ws, 100.0, "live-probe", "probe-credit-1")  # retried credit
        before = ledger.get_balance(ws)
        ledger.charge(ws, 40.0, "live-probe", "probe-charge-1")
        ledger.charge(ws, 40.0, "live-probe", "probe-charge-1")  # retried charge
        after = ledger.get_balance(ws)
        assert before - after == 40.0, f"double-charge! delta={before - after}"
        rows = frappe.get_all(
            "WD Wallet Transaction",
            filters={"idempotency_key": ["in", ["probe-credit-1", "probe-charge-1"]]},
        )
        assert len(rows) == 2, f"expected 2 ledger rows, found {len(rows)}"
        print("WALLET-PROBE-PASS :: retried credit+charge produced 1 row each; delta 40.0")
    finally:
        frappe.db.rollback()
