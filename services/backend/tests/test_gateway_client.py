"""Gateway HTTP client — error messages must be log-safe (non-negotiable #6)."""

import pytest

from app import gateway


class _Resp:
    status_code = 404
    content = b"{}"


def test_gateway_error_redacts_phone_bearing_paths(monkeypatch):
    """Legacy group JIDs embed a raw phone (<phone>-<ts>@g.us); the compat
    dispatcher logs GatewayError verbatim, so the message must never carry it."""
    monkeypatch.setattr(gateway.httpx, "request", lambda *a, **k: _Resp())
    with pytest.raises(gateway.GatewayError) as err:
        gateway.group_participants_update(
            "sess-1", "911234567890-1590000000@g.us", ["919999900001"], "add"
        )
    msg = str(err.value)
    assert "911234567890" not in msg  # the phone is redacted…
    assert "…" in msg
    assert "404" in msg  # …but the diagnostic status survives
