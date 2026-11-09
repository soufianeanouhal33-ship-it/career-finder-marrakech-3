from tests.conftest import register


def test_protected_routes_require_token(client):
    for path in ["/api/opportunities", "/api/applications", "/api/profile",
                 "/api/stats", "/api/maps-key", "/api/matching", "/api/auth/me"]:
        assert client.get(path).status_code == 401, path
    assert client.get("/api/opportunities", headers={"Authorization": "Bearer nimportequoi"}).status_code == 401


def test_health_is_public(client):
    assert client.get("/api/health").status_code == 200


def test_first_user_is_admin_second_is_not(client):
    h1 = register(client, "alice")
    h2 = register(client, "bob")
    assert client.get("/api/auth/me", headers=h1).json() == {"username": "alice", "is_admin": True}
    assert client.get("/api/auth/me", headers=h2).json()["is_admin"] is False


def test_register_validation(client):
    assert client.post("/api/auth/register", json={"username": "ab", "password": "motdepasse123"}).status_code == 422
    assert client.post("/api/auth/register", json={"username": "alice", "password": "court"}).status_code == 422
    register(client, "alice")
    dup = client.post("/api/auth/register", json={"username": "ALICE", "password": "motdepasse123"})
    assert dup.status_code == 409


def test_login_ok_and_wrong_password(client):
    register(client, "alice", "motdepasse123")
    ok = client.post("/api/auth/login", json={"username": "alice", "password": "motdepasse123"})
    assert ok.status_code == 200 and ok.json()["access_token"]
    bad = client.post("/api/auth/login", json={"username": "alice", "password": "mauvais"})
    assert bad.status_code == 401
    ghost = client.post("/api/auth/login", json={"username": "inconnu", "password": "motdepasse123"})
    assert ghost.status_code == 401
    assert bad.json()["detail"] == ghost.json()["detail"]  # pas d'énumération de comptes


def test_login_rate_limit(client):
    register(client, "alice")
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "alice", "password": "x"}).status_code == 401
    blocked = client.post("/api/auth/login", json={"username": "alice", "password": "motdepasse123"})
    assert blocked.status_code == 429


def test_registration_can_be_disabled_after_first_user(client, monkeypatch):
    import backend.main as main
    register(client, "alice")
    monkeypatch.setattr(main, "ALLOW_REGISTRATION", False)
    r = client.post("/api/auth/register", json={"username": "bob", "password": "motdepasse123"})
    assert r.status_code == 403


def test_applications_are_isolated_between_users(client):
    h1, h2 = register(client, "alice"), register(client, "bob")
    client.post("/api/applications", headers=h1, json={"company": "Acme", "poste": "Stage IA"})
    assert len(client.get("/api/applications", headers=h1).json()) == 1
    assert client.get("/api/applications", headers=h2).json() == []

    app_id = client.get("/api/applications", headers=h1).json()[0]["id"]
    assert client.patch(f"/api/applications/{app_id}", headers=h2, json={"statut": "Refusée"}).status_code == 404
    assert client.delete(f"/api/applications/{app_id}", headers=h2).status_code == 404
    assert client.patch(f"/api/applications/{app_id}", headers=h1, json={"statut": "Envoyée"}).status_code == 200


def test_client_cannot_spoof_application_owner(client):
    h1, h2 = register(client, "alice"), register(client, "bob")
    client.post("/api/applications", headers=h2, json={"user": "alice", "company": "X", "poste": "Y"})
    assert client.get("/api/applications", headers=h1).json() == []
    assert len(client.get("/api/applications", headers=h2).json()) == 1


def test_favorites_are_per_user(client):
    h1, h2 = register(client, "alice"), register(client, "bob")
    opp_id = client.post("/api/opportunities/manual", headers=h1, json={"nom": "TechCo"}).json()["id"]
    assert client.patch(f"/api/opportunities/{opp_id}/favorite", headers=h1).json()["favori"] is True
    fav1 = client.get("/api/opportunities", headers=h1, params={"favoris_only": True}).json()
    fav2 = client.get("/api/opportunities", headers=h2, params={"favoris_only": True}).json()
    assert len(fav1) == 1 and fav2 == []


def test_profile_is_per_user(client):
    h1, h2 = register(client, "alice"), register(client, "bob")
    client.post("/api/profile", headers=h1, json={"skills": "python, sql"})
    assert client.get("/api/profile", headers=h1).json()["skills"] == "python, sql"
    assert client.get("/api/profile", headers=h2).json()["skills"] == ""


def test_only_author_or_admin_can_delete_opportunity(client):
    admin, bob, carol = register(client, "alice"), register(client, "bob"), register(client, "carol")
    opp_id = client.post("/api/opportunities/manual", headers=bob, json={"nom": "BobCo"}).json()["id"]
    assert client.delete(f"/api/opportunities/{opp_id}", headers=carol).status_code == 403
    assert client.delete(f"/api/opportunities/{opp_id}", headers=bob).status_code == 200

    opp2 = client.post("/api/opportunities/manual", headers=bob, json={"nom": "BobCo2"}).json()["id"]
    assert client.delete(f"/api/opportunities/{opp2}", headers=admin).status_code == 200
