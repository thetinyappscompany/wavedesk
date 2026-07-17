"""Media presigning — browser-facing URLs must be signed against the PUBLIC
endpoint, never the internal service DNS (unreachable from a browser)."""

from app import media_store


def _reset_clients():
    media_store._client.cache_clear()
    media_store._presign_client.cache_clear()


def test_presigned_url_uses_public_endpoint(monkeypatch):
    monkeypatch.setenv("S3_ACCESS_KEY", "test-access")
    monkeypatch.setenv("S3_SECRET_KEY", "test-secret")
    monkeypatch.setenv("S3_ENDPOINT", "http://srv-captain--minio:9000")
    monkeypatch.setenv("S3_PUBLIC_ENDPOINT", "https://media.example.com")
    _reset_clients()
    try:
        url = media_store.presigned_url("ws1/msg1.jpg")
        assert url is not None
        assert url.startswith("https://media.example.com/")
        assert "srv-captain--minio" not in url
    finally:
        _reset_clients()  # never leak env-bound clients into other tests


def test_presigned_url_falls_back_to_internal_endpoint(monkeypatch):
    """Dev/compose: one endpoint serves both roles when no public one is set."""
    monkeypatch.setenv("S3_ACCESS_KEY", "test-access")
    monkeypatch.setenv("S3_SECRET_KEY", "test-secret")
    monkeypatch.setenv("S3_ENDPOINT", "http://localhost:9000")
    monkeypatch.delenv("S3_PUBLIC_ENDPOINT", raising=False)
    _reset_clients()
    try:
        url = media_store.presigned_url("ws1/msg1.jpg")
        assert url is not None
        assert url.startswith("http://localhost:9000/")
    finally:
        _reset_clients()


def test_presigned_url_graceful_without_creds(monkeypatch):
    monkeypatch.delenv("S3_ACCESS_KEY", raising=False)
    _reset_clients()
    try:
        assert media_store.presigned_url("ws1/msg1.jpg") is None
    finally:
        _reset_clients()
