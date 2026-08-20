import httpx

from camtrap_measure.main import start_engine


def test_engine_serves_health_over_real_http():
    url = start_engine()
    r = httpx.get(f"{url}/api/health", timeout=5)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
