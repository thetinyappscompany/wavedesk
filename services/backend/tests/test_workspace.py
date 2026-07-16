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
