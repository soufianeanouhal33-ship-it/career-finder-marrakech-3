import io

from tests.conftest import register

PDF = b"%PDF-1.4\n%fake pdf for tests\n"


def _company(client, headers, nom="Acme IT", email="rh@acme.ma", **extra):
    r = client.post("/api/opportunities/manual", headers=headers, json={"nom": nom, "email": email, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _send(client, headers, opp_id, force=False, filename="cv.pdf", content=PDF):
    return client.post(
        "/api/send-cv", headers=headers,
        data={"opportunity_id": str(opp_id), "subject": "Candidature", "message": "Bonjour", "force": str(force).lower()},
        files={"cv": (filename, io.BytesIO(content), "application/pdf")},
    )


def test_web_interface_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Career Finder" in r.text
    assert client.get("/js/core.js").status_code == 200


def test_meta_lists(client):
    h = register(client, "alice")
    meta = client.get("/api/meta", headers=h).json()
    assert "Informatique" in meta["secteurs"] and "Stage" in meta["contrats"]
    assert "Envoyée" in meta["statuts"]


def test_sector_is_detected_and_email_validated(client):
    h = register(client, "alice")
    opp_id = _company(client, h, nom="Atlas Informatique")
    opp = next(o for o in client.get("/api/opportunities", headers=h).json() if o["id"] == opp_id)
    assert opp["secteur"] == "Informatique" and opp["email"] == "rh@acme.ma"
    bad = client.post("/api/opportunities/manual", headers=h, json={"nom": "X", "email": "pas-un-email"})
    assert bad.status_code == 422


def test_edit_company_permissions(client):
    admin, bob, carol = register(client, "alice"), register(client, "bob"), register(client, "carol")
    opp_id = _company(client, bob, nom="BobCo", email="")
    assert client.patch(f"/api/opportunities/{opp_id}", headers=carol, json={"email": "a@b.ma"}).status_code == 403
    assert client.patch(f"/api/opportunities/{opp_id}", headers=bob, json={"email": "a@b.ma", "secteur": "Marketing"}).status_code == 200
    assert client.patch(f"/api/opportunities/{opp_id}", headers=admin, json={"telephone": "0600000000"}).status_code == 200
    assert client.patch(f"/api/opportunities/{opp_id}", headers=bob, json={"email": "invalide"}).status_code == 422
    assert client.patch(f"/api/opportunities/{opp_id}", headers=bob, json={"secteur": "Inconnu"}).status_code == 422


def test_offers_crud_and_filters(client):
    h = register(client, "alice")
    r = client.post("/api/offers", headers=h, json={
        "titre": "Stage IA", "entreprise": "Acme", "contrat": "Stage", "type_stage": "Stage de fin d'études",
        "date_publication": "2026-09-25"})
    assert r.status_code == 201
    assert client.post("/api/offers", headers=h, json={
        "titre": "Stage IA", "entreprise": "Acme", "date_publication": "2026-09-25"}).status_code == 409
    client.post("/api/offers", headers=h, json={"titre": "Dev Web", "contrat": "CDI"})
    assert len(client.get("/api/offers", headers=h).json()) == 2
    assert len(client.get("/api/offers", headers=h, params={"contrat": "CDI"}).json()) == 1
    assert len(client.get("/api/offers", headers=h, params={"type_stage": "Stage de fin d'études"}).json()) == 1
    assert len(client.get("/api/offers", headers=h, params={"q": "web"}).json()) == 1
    bad = client.post("/api/offers", headers=h, json={"titre": "X", "url": "javascript:alert(1)"})
    assert bad.status_code == 422


def test_offer_delete_permissions(client):
    admin, bob, carol = register(client, "alice"), register(client, "bob"), register(client, "carol")
    oid = client.post("/api/offers", headers=bob, json={"titre": "Offre Bob"}).json()["id"]
    assert client.delete(f"/api/offers/{oid}", headers=carol).status_code == 403
    assert client.delete(f"/api/offers/{oid}", headers=bob).status_code == 200


def test_offers_import_csv_with_flexible_columns(client):
    h = register(client, "alice")
    opp_id = _company(client, h, nom="Acme")
    csv = ("Intitulé;Société;Type de contrat;Type de stage;Date de publication;Lien\n"
           "Stage IA;Acme;Stage;PFE;25/09/2026;https://x.ma/1\n"
           "Stage IA;Acme;Stage;PFE;25/09/2026;https://x.ma/1\n"
           "Dev;Autre SA;cdi;;;javascript:alert(1)\n").encode()
    r = client.post("/api/offers/import", headers=h, files={"file": ("offres.csv", io.BytesIO(csv), "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["report"]["ajoutees"] == 2 and r.json()["report"]["ignorees"] == 1
    offers = client.get("/api/offers", headers=h).json()
    ia = next(o for o in offers if o["titre"] == "Stage IA")
    assert ia["opportunity_id"] == opp_id and ia["date_publication"] == "2026-09-25"
    assert ia["type_stage"] == "Stage de fin d'études"
    assert next(o for o in offers if o["titre"] == "Dev")["url"] == ""   # lien non http(s) rejeté


def test_stats_shape(client):
    h = register(client, "alice")
    _company(client, h)
    client.post("/api/offers", headers=h, json={"titre": "Stage", "contrat": "Stage"})
    s = client.get("/api/stats", headers=h).json()
    assert s["total_opportunites"] == 1 and s["total_offres"] == 1 and s["entreprises_avec_email"] == 1
    assert s["par_secteur"] and s["offres_par_contrat"] == {"Stage": 1}
    assert s["presence_numerique"]["avec_email"] == 1


def test_application_status_is_validated(client):
    h = register(client, "alice")
    assert client.post("/api/applications", headers=h, json={"company": "X", "poste": "Y", "statut": "Bidon"}).status_code == 422


# ---------- Envoi du CV ----------

def test_send_cv_requires_smtp_configuration(client, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    h = register(client, "alice")
    assert _send(client, h, _company(client, h)).status_code == 503


def test_send_cv_flow(client, monkeypatch):
    import backend.main as main
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_FROM", "app@test.ma")
    sent = []
    monkeypatch.setattr(main, "send_message", lambda msg: sent.append(msg))

    h = register(client, "alice")
    opp_id = _company(client, h)

    assert _send(client, h, opp_id, filename="cv.docx").status_code == 422             # extension
    assert _send(client, h, opp_id, content=b"pas un pdf").status_code == 422          # contenu
    assert _send(client, h, _company(client, h, nom="SansMail", email="")).status_code == 400
    assert _send(client, h, 99999).status_code == 404

    ok = _send(client, h, opp_id)
    assert ok.status_code == 200 and ok.json()["to"] == "rh@acme.ma"
    assert len(sent) == 1 and sent[0]["To"] == "rh@acme.ma"

    apps = client.get("/api/applications", headers=h).json()
    assert len(apps) == 1 and apps[0]["statut"] == "Envoyée" and apps[0]["opportunity_id"] == opp_id
    opp = next(o for o in client.get("/api/opportunities", headers=h).json() if o["id"] == opp_id)
    assert opp["cv_envoye_le"]

    assert _send(client, h, opp_id).status_code == 409                 # doublon récent
    assert _send(client, h, opp_id, force=True).status_code == 200      # confirmation explicite
    assert len(sent) == 2


def test_send_cv_hourly_limit_and_recipient_comes_from_db(client, monkeypatch):
    import backend.main as main
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_FROM", "app@test.ma")
    monkeypatch.setattr(main, "MAX_CV_PER_HOUR", 1)
    sent = []
    monkeypatch.setattr(main, "send_message", lambda msg: sent.append(msg))

    h = register(client, "alice")
    a, b = _company(client, h, nom="A", email="a@a.ma"), _company(client, h, nom="B", email="b@b.ma")
    r = client.post("/api/send-cv", headers=h, data={
        "opportunity_id": str(a), "subject": "S", "message": "M", "to": "victime@evil.com"},
        files={"cv": ("cv.pdf", io.BytesIO(PDF), "application/pdf")})
    assert r.status_code == 200 and sent[0]["To"] == "a@a.ma"          # le champ « to » est ignoré
    assert _send(client, h, b).status_code == 429


def test_send_cv_requires_auth(client):
    assert _send(client, {}, 1).status_code == 401
