"""R0 acceptance — login contract parity (cookie sid + {"message": ...} envelope)."""


def test_login_sets_cookie_and_envelope(client, make_user):
    user = make_user()
    r = client.post("/api/method/login", json={"usr": user.email, "pwd": "s3cret-pass"})
    assert r.status_code == 200
    assert r.json() == {"message": "Logged In"}
    assert "sid" in r.cookies

    who = client.get("/api/method/frappe.auth.get_logged_user")
    assert who.json()["message"] == user.email


def test_login_rejects_wrong_password(client, make_user):
    user = make_user()
    r = client.post("/api/method/login", json={"usr": user.email, "pwd": "wrong"})
    assert r.status_code == 401


def test_login_binds_existing_workspace(client, make_user, db):
    """Regression: a returning user with a workspace must land with an active
    workspace bound, so workspace-scoped calls work instead of 400."""
    from app.models import Workspace, WorkspaceMember

    user = make_user()
    ws = Workspace(name="Bound WS")
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="Owner"))
    db.commit()

    assert client.post(
        "/api/method/login", json={"usr": user.email, "pwd": "s3cret-pass"}
    ).status_code == 200

    active = client.get("/api/method/wavedesk.api.workspace.get_active")
    assert active.status_code == 200, active.text  # was 400 "No active workspace"
    assert active.json()["message"]["workspace"] == str(ws.id)


def test_login_without_workspace_stays_in_onboarding(client, make_user):
    """A brand-new user with no membership binds nothing → onboarding path."""
    user = make_user()
    assert client.post(
        "/api/method/login", json={"usr": user.email, "pwd": "s3cret-pass"}
    ).status_code == 200
    # No workspace bound: the scoped call still 400s and the SPA routes to
    # /onboarding (create_workspace then sets the active workspace).
    assert client.get("/api/method/wavedesk.api.workspace.get_active").status_code == 400


def test_guest_blocked_from_authed_methods(client):
    r = client.get("/api/method/frappe.auth.get_logged_user")
    assert r.status_code == 401


def test_logout_destroys_session(client, login):
    login()
    assert client.post("/api/method/logout").status_code == 200
    assert client.get("/api/method/frappe.auth.get_logged_user").status_code == 401


def test_unknown_method_404(client, login):
    login()
    assert client.get("/api/method/no.such.method").status_code == 404


def test_login_workspace_binding_is_deterministic_on_ties(client, db, make_user):
    """Memberships flushed in one transaction share created_at (server_default
    now()); without the id tiebreaker the same user could land in different
    workspaces on successive logins."""
    from app.models import Workspace, WorkspaceMember

    user = make_user()
    ws_a = Workspace(name="Tie A")
    ws_b = Workspace(name="Tie B")
    db.add_all([ws_a, ws_b])
    db.flush()
    # One transaction → identical created_at on both memberships.
    db.add_all([
        WorkspaceMember(workspace_id=ws_a.id, user_id=user.id, role="Agent"),
        WorkspaceMember(workspace_id=ws_b.id, user_id=user.id, role="Agent"),
    ])
    db.commit()

    def _login_active() -> str:
        client.cookies.clear()
        r = client.post("/api/method/login", json={"usr": user.email, "pwd": "s3cret-pass"})
        assert r.status_code == 200, r.text
        r = client.get("/api/method/wavedesk.api.workspace.get_active")
        assert r.status_code == 200, r.text
        return r.json()["message"]["workspace"]

    first = _login_active()
    for _ in range(3):
        assert _login_active() == first  # same pick every login
