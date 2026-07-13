# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Account-security API (master doc §Phase 5 feature 6): 2FA (TOTP) enrollment
+ verification and active-session management. All self-service — every method
operates on the authenticated caller (frappe.session.user), never another user."""

import frappe

from wavedesk.auth import sessions, twofa


def _me() -> str:
    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw("Login required", frappe.AuthenticationError)
    return user


# --- 2FA / TOTP ------------------------------------------------------------


@frappe.whitelist()
def twofa_status() -> dict:
    return twofa.status(_me())


@frappe.whitelist()
def twofa_begin_enroll() -> dict:
    return twofa.begin_enroll(_me())


@frappe.whitelist()
def twofa_confirm(code: str) -> dict:
    return twofa.confirm_enroll(_me(), code)


@frappe.whitelist()
def twofa_disable(code: str) -> dict:
    return twofa.disable(_me(), code)


@frappe.whitelist()
def twofa_verify(code: str) -> dict:
    """Second-factor check the SPA calls after password login when 2FA is on."""
    return {"verified": twofa.verify(_me(), code)}


# --- active sessions -------------------------------------------------------


@frappe.whitelist()
def list_sessions() -> dict:
    return {"sessions": sessions.list_sessions(_me())}


@frappe.whitelist()
def revoke_session(sid_tail: str) -> dict:
    return sessions.revoke_session(_me(), sid_tail)


@frappe.whitelist()
def revoke_other_sessions() -> dict:
    return sessions.revoke_other_sessions(_me())
