"""R0 acceptance — workspace creation + tenancy guards."""


def _create(client, name="Acme Traders"):
    r = client.post(
        "/api/method/wavedesk.api.onboarding.create_workspace",
        json={"workspace_name": name},
    )
    assert r.status_code == 200, r.text
    return r.json()["message"]


def test_create_workspace_makes_caller_owner_and_activates(client, login):
    login()
    out = _create(client)
    assert out["role"] == "Owner"

    active = client.get("/api/method/wavedesk.api.workspace.get_active").json()["message"]
    assert active["workspace"] == out["workspace"]
    assert active["plan"] == "Trial"
    assert active["role"] == "Owner"


def test_cannot_activate_foreign_workspace(client, login):
    login()
    ws = _create(client)["workspace"]

    # a different user must not be able to activate the first user's workspace
    client.cookies.clear()
    login()
    r = client.post(
        "/api/method/wavedesk.api.workspace.set_active", json={"workspace": ws}
    )
    assert r.status_code == 403


def test_get_active_requires_membership_recheck(client, login):
    login()
    r = client.get("/api/method/wavedesk.api.workspace.get_active")
    assert r.status_code == 400  # no active workspace yet


def test_workspace_settings_returns_full_contract(client, login):
    """get_workspace_settings must return business_hours + routing/OOO fields
    the SPA needs — a missing business_hours white-screens the Settings page."""
    login()
    _create(client)
    s = client.get(
        "/api/method/wavedesk.api.workspace.get_workspace_settings"
    ).json()["message"]
    # business_hours is always a full object (never undefined)
    assert s["business_hours"] == {
        "enabled": False,
        "timezone": "Asia/Kolkata",
        "days": {},
        "holidays": [],
    }
    for key in ("workspace_name", "default_routing_team", "ooo_reply_enabled",
                "ooo_reply_message", "mask_numbers", "needs_reply_minutes", "role"):
        assert key in s


def test_workspace_settings_persists_business_hours_and_ooo(client, login):
    login()
    _create(client)
    bh = {"enabled": True, "timezone": "Asia/Kolkata",
          "days": {"mon": {"open": "09:00", "close": "18:00"}}, "holidays": ["2026-01-01"]}
    r = client.post(
        "/api/method/wavedesk.api.workspace.update_workspace_settings",
        json={"business_hours": bh, "ooo_reply_enabled": True,
              "ooo_reply_message": "Away — back at 9am"},
    )
    assert r.status_code == 200, r.text
    out = r.json()["message"]
    assert out["business_hours"] == bh
    assert out["ooo_reply_enabled"] is True
    assert out["ooo_reply_message"] == "Away — back at 9am"
