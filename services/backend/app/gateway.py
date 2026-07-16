"""HTTP client for the wa-gateway internal API (shared-secret auth).

Same wire contract as the gateway expects today — the gateway itself is
unchanged by the rewrite. Env: WD_GATEWAY_URL, WD_GATEWAY_SECRET."""

import os

import httpx

INTERNAL_HEADER = "X-Wavedesk-Internal"
TIMEOUT_S = 15


class GatewayError(Exception):
    pass


def _base_url() -> str:
    return (os.environ.get("WD_GATEWAY_URL") or "http://localhost:8081").rstrip("/")


def _headers() -> dict:
    return {INTERNAL_HEADER: os.environ.get("WD_GATEWAY_SECRET") or "dev-internal-secret"}


def _request(method: str, path: str, json: dict | None = None) -> dict:
    try:
        response = httpx.request(
            method, _base_url() + path, json=json, headers=_headers(), timeout=TIMEOUT_S
        )
    except httpx.HTTPError as err:
        raise GatewayError(f"gateway unreachable: {type(err).__name__}") from err
    if response.status_code >= 400:
        raise GatewayError(f"gateway returned {response.status_code} for {path}")
    if response.status_code == 204 or not response.content:
        return {}
    return response.json()


def create_session(session_id: str, workspace: str) -> dict:
    return _request(
        "POST", "/sessions", {"session_id": session_id, "workspace": workspace, "stream": False}
    )


def session_status(session_id: str) -> dict:
    return _request("GET", f"/sessions/{session_id}")


def disconnect_session(session_id: str) -> dict:
    return _request("POST", f"/sessions/{session_id}/disconnect")


def reconnect_session(session_id: str) -> dict:
    return _request("POST", f"/sessions/{session_id}/reconnect")


def delete_session(session_id: str) -> dict:
    return _request("DELETE", f"/sessions/{session_id}")


def send_session_message(session_id: str, to: str, text: str) -> dict:
    return _request("POST", f"/sessions/{session_id}/messages", {"to": to, "text": text})


def send_cloud_message(phone_number_id: str, to: str, text: str) -> dict:
    return _request("POST", f"/cloud/{phone_number_id}/messages", {"to": to, "text": text})
