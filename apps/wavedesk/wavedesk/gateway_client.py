"""HTTP client for the wa-gateway internal API (shared-secret auth, §2.2).

Site config keys:
  wa_gateway_url     (default http://localhost:8081)
  wa_gateway_secret  (must match the gateway's WA_GATEWAY_INTERNAL_SECRET)
"""

import frappe
import requests

INTERNAL_HEADER = "X-Wavedesk-Internal"
TIMEOUT_S = 15


class GatewayError(frappe.ValidationError):
    pass


def _base_url() -> str:
    return (frappe.conf.get("wa_gateway_url") or "http://localhost:8081").rstrip("/")


def _headers() -> dict:
    secret = frappe.conf.get("wa_gateway_secret") or "dev-internal-secret"
    return {INTERNAL_HEADER: secret}


def _request(method: str, path: str, json: dict | None = None) -> dict:
    try:
        response = requests.request(
            method, _base_url() + path, json=json, headers=_headers(), timeout=TIMEOUT_S
        )
    except requests.RequestException as err:
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
