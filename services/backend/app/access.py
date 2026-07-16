"""Per-workspace IP allowlist (Business plan). enforce() refuses API-key calls
from outside the allowlist. Proxy-aware: trusts X-Real-IP only when
WD_IP_ALLOWLIST_TRUSTED_PROXY is set (else fail-closed to peer IP)."""

import ipaddress
import os


def normalize(entries: list[str]) -> list[str]:
    out = []
    for raw in entries:
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            net = ipaddress.ip_network(raw, strict=False)
        except ValueError as err:
            raise ValueError(f"Invalid IP/CIDR: {raw}") from err
        canonical = str(net)
        if canonical not in out:
            out.append(canonical)
    return out


def is_ip_allowed(ip: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return True  # empty = allow all
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(entry, strict=False) for entry in allowlist)


def client_ip(request) -> str:
    if os.environ.get("WD_IP_ALLOWLIST_TRUSTED_PROXY"):
        xreal = request.headers.get("x-real-ip")
        if xreal:
            return xreal.strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


def enforce(workspace, ip: str) -> None:
    allowlist = (workspace.settings or {}).get("ip_allowlist") or []
    if not is_ip_allowed(ip, allowlist):
        raise PermissionError("Request IP is outside the workspace allowlist")
