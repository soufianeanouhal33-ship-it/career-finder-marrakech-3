import os

# Doit être défini AVANT l'import de backend.main (SECRET_KEY est lue à l'import)
os.environ.setdefault("SECRET_KEY", "test-secret-key-" + "x" * 32)
os.environ.setdefault("GOOGLE_MAPS_API_KEY", "")

import pytest
from fastapi.testclient import TestClient

import backend.database as db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    from backend.main import app, login_limiter

    login_limiter._failures.clear()
    with TestClient(app) as c:  # déclenche le lifespan -> init_db()
        yield c


def register(client, username, password="motdepasse123"):
    r = client.post("/api/auth/register", json={"username": username, "password": password})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
