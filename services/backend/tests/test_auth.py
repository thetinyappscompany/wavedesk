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
