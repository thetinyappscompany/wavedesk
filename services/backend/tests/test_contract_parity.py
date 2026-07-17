"""R7 — the contract is the acceptance test. This meta-test fails if the SPA's
api-client ever calls a dotted method the backend doesn't register. It is the
guard that keeps the frozen-contract promise true as the rewrite continues."""

import re
from pathlib import Path

import app.main  # noqa: F401 — registers every handler
from app.compat import _REGISTRY

_CLIENT = Path(__file__).resolve().parents[3] / "packages" / "api-client" / "src" / "index.ts"
_CALL_RE = re.compile(r"this\.call\('([^']+)'")


def _client_methods() -> set[str]:
    text = _CLIENT.read_text(encoding="utf-8")
    return set(_CALL_RE.findall(text))


def test_every_client_call_is_registered():
    missing = sorted(_client_methods() - set(_REGISTRY))
    assert not missing, f"api-client calls these unregistered methods: {missing}"


def test_core_contract_shapes():
    """A handful of shape checks the SPA depends on."""
    # login/logout/whoami present
    for name in ("login", "logout", "frappe.auth.get_logged_user"):
        assert name in _REGISTRY
    # the big feature surfaces all resolve
    for prefix in ("chats", "messages", "contacts", "send", "groups", "broadcasts",
                   "automation", "sla", "ai", "copilot", "agent", "flagging",
                   "publicapi", "webhooks", "admin", "privacy", "security"):
        assert any(m.startswith(f"wavedesk.api.{prefix}.") for m in _REGISTRY), prefix
