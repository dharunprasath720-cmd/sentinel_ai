from pathlib import Path

from fastapi.testclient import TestClient

from sentinel.api.app import create_app
from sentinel.api.frontend import mount_frontend
from sentinel.db import init_db, make_engine

SECRET = "frontend-mount-test-secret-that-is-at-least-32-bytes"


def app_and_client():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    app = create_app(engine, secret=SECRET)
    return app, TestClient(app)


def test_mount_serves_index_and_api_still_wins(tmp_path: Path):
    (tmp_path / "index.html").write_text("<html><title>SENTINEL</title></html>", encoding="utf-8")
    app, client = app_and_client()
    assert mount_frontend(app, tmp_path) is True
    root = client.get("/")
    assert root.status_code == 200 and "SENTINEL" in root.text
    assert client.get("/alerts").status_code == 401  # API route, not the static mount
    assert client.get("/docs").status_code == 200


def test_mount_returns_false_when_there_is_no_build(tmp_path: Path):
    app, client = app_and_client()
    assert mount_frontend(app, tmp_path / "dist") is False
    assert client.get("/").status_code == 404
