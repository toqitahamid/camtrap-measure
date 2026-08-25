from fastapi.testclient import TestClient

from camtrap_measure.api import __version__, app

client = TestClient(app)


def test_health_reports_version():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["commit"] is None or (isinstance(body["commit"], str) and body["commit"])  # git describe of the checkout


def test_root_serves_built_page():
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert '<div id="root">' in r.text
