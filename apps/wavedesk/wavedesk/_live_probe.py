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


def run_rag():
    """Full RAG round-trip: real NVIDIA embeddings -> Qdrant -> semantic search.
    Needs NVIDIA_API_KEY (+ QDRANT_URL) in env. Cleans up after itself."""
    from wavedesk.ai import rag

    ws = "LIVE-PROBE-WS"
    coll = rag.collection_name(ws)
    try:
        n = rag.index_doc(
            ws, "probe-refunds",
            "Refund policy: customers can request a full refund within 14 days "
            "of purchase. After 14 days we offer store credit only.",
        )
        assert n >= 1, "index_doc stored no chunks"
        rag.index_doc(
            ws, "probe-shipping",
            "Shipping: orders dispatch within 24 hours and arrive in 3-5 "
            "business days across India.",
        )
        hits = rag.search(ws, "how long do I have to get my money back?", top_k=1)
        assert hits, "search returned nothing"
        assert hits[0]["doc"] == "probe-refunds", f"semantic miss: {hits[0]}"
        print(f"RAG-PROBE-PASS :: embed+index {n} chunk(s); semantic search hit "
              f"probe-refunds at score {hits[0]['score']:.3f}")
    finally:
        try:
            rag._qdrant("DELETE", f"/collections/{coll}")
        except Exception:
            pass


def run_zoho():
    """Live Zoho Billing round-trip through billing/zoho_client.py: refresh-token
    -> access-token mint -> real API call with the org header. Read-only."""
    import requests

    from wavedesk.billing import zoho_client

    assert zoho_client.is_configured(), "Zoho env incomplete (id/secret/refresh/org)"
    headers = zoho_client._headers()
    assert headers, "access-token mint failed"
    resp = requests.get(f"{zoho_client._api_base()}/plans", headers=headers, timeout=30)
    resp.raise_for_status()
    plans = (resp.json() or {}).get("plans", [])
    print(f"ZOHO-PROBE-PASS :: token minted + /plans returned {len(plans)} plan(s) "
          f"for org (API + org header accepted)")


def run_anthropic():
    """Minimal Anthropic key sanity ping (1-token Haiku call, ~zero cost).
    Bypasses the metered provider on purpose — this validates the KEY, not billing."""
    import os

    import anthropic

    assert os.environ.get("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY unset"
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1,
        messages=[{"role": "user", "content": "ping"}],
    )
    assert resp.id, "no response id"
    print("ANTHROPIC-PROBE-PASS :: key valid, 1-token Haiku round-trip ok")


def run_reconcile_repro():
    """Debug: does a name-in filter round-trip a UUID-named WD Message?"""
    import uuid as uuidlib

    import frappe

    ws = frappe.get_all("WD Workspace", limit=1, pluck="name")[0]
    try:
        chat = frappe.get_doc({
            "doctype": "WD Chat", "workspace": ws, "chat_type": "dm",
            "wa_chat_id": f"repro-{uuidlib.uuid4().hex[:8]}", "status": "open",
        }).insert(ignore_permissions=True)
        msg = frappe.get_doc({
            "doctype": "WD Message", "workspace": ws, "chat": chat.name,
            "direction": "out", "message_type": "text", "body": "x",
            "wa_message_id": f"R-{uuidlib.uuid4().hex[:8]}", "status": "failed",
        }).insert(ignore_permissions=True)
        plucked = frappe.get_all(
            "WD Message", filters={"name": ("in", [msg.name]), "status": "failed"},
            pluck="name",
        )
        print("stored:", repr(msg.name))
        print("plucked:", [repr(r) for r in plucked])
        print("set-match:", msg.name in set(plucked))
        print("db-status:", frappe.db.get_value("WD Message", msg.name, "status"))
    finally:
        frappe.db.rollback()


def run_wallet():
    """Runbook check: a retried charge (same idempotency key) never double-debits.
    Runs on the real DB inside a rolled-back transaction — no residue."""
    import frappe

    from wavedesk.wallet import ledger

    try:
        ws = frappe.get_all("WD Workspace", limit=1, pluck="name")
        if ws:
            ws = ws[0]
        else:
            # fresh site (e.g. the Postgres one) — probe workspace lives only
            # inside this transaction, rolled back below
            import uuid as uuidlib

            doc = frappe.new_doc("WD Workspace")
            doc.workspace_name = f"Live Probe WS {uuidlib.uuid4().hex[:8]}"
            doc.plan = "Trial"
            doc.append("members", {"user": "Administrator", "role": "Owner"})
            doc.insert(ignore_permissions=True)
            ws = doc.name
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
