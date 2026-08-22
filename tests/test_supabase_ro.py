"""Guard: the Supabase wrapper is read-only and is the only Supabase client."""

import json
import re
from pathlib import Path

import httpx
import pytest

from camtrap_measure import supabase_ro as sb

SRC_DIR = Path(sb.__file__).parent
WRAPPER_SRC = Path(sb.__file__).read_text()


def test_public_surface_is_auth_plus_three_reads():
    assert set(sb.__all__) == {
        "AuthError",
        "Offline",
        "request_code",
        "verify_code",
        "refresh",
        "select_annotations",
        "select_sites",
        "download_object",
    }
    public = {n for n in dir(sb) if not n.startswith("_") and callable(getattr(sb, n))}
    assert public == set(sb.__all__)


def test_wrapper_source_has_no_write_verbs():
    # All traffic goes through _send(); the only non-GETs are the auth calls (token grant, code request, code check).
    assert WRAPPER_SRC.count("_http.") == 1 and "_http.request(method" in WRAPPER_SRC
    sends = re.findall(r'_send\("(\w+)", ([^,)]+)', WRAPPER_SRC)  # verb must be a literal
    assert WRAPPER_SRC.count("_send(") == len(sends) + 1  # +1: the def; no dynamic verbs
    assert [(m, p) for m, p in sends if m != "GET"] == [("POST", '"/auth/v1/token"'), ("POST", "path")]
    auth_posts = re.findall(r'_auth_post\("([^"]+)"', WRAPPER_SRC)  # the one parameterised POST only ever sees these
    assert auth_posts == ["/auth/v1/otp", "/auth/v1/verify"]
    assert "upsert" not in WRAPPER_SRC and "Prefer" not in WRAPPER_SRC


def test_wrapper_is_the_only_supabase_client():
    needles = ("supabase", "rest/v1", "storage/v1", "auth/v1", "httpx", "requests", "urllib", "postgrest")
    for py in SRC_DIR.rglob("*.py"):
        if py == Path(sb.__file__):
            continue
        text = py.read_text().replace("supabase_ro", "")  # importing the wrapper is the point
        for needle in needles:
            assert needle not in text, f"{py.name} talks to Supabase directly ({needle})"
    for ts in (SRC_DIR.parent.parent / "frontend" / "src").rglob("*.ts*"):
        assert "supabase" not in ts.read_text().lower(), f"{ts.name}: frontend must go through the engine"


@pytest.fixture
def recorded(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/auth/v1/otp":
            return httpx.Response(200, json={})
        if req.url.path in ("/auth/v1/token", "/auth/v1/verify"):
            return httpx.Response(
                200,
                json={"access_token": "at", "refresh_token": "rt", "user": {"email": "a@b"}},
            )
        if req.url.path.startswith("/storage/v1/object/"):
            if req.url.path.endswith("/gone.JPG"):
                return httpx.Response(404, json={"error": "not_found"})
            return httpx.Response(200, content=b"\xff\xd8jpeg")
        return httpx.Response(200, json=[])

    monkeypatch.setattr(
        sb, "_http", httpx.Client(base_url=sb._http.base_url, transport=httpx.MockTransport(handler))
    )
    return seen


def test_every_data_request_is_a_get(recorded):
    sess = sb.verify_code("a@b", "123456")
    sb.refresh(sess["refresh_token"])
    sb.select_annotations("at")
    sb.select_sites("at")
    assert sb.download_object("at", "SRF_CAM08/IMG_3792.JPG") == b"\xff\xd8jpeg"
    assert sb.download_object("at", "SRF_CAM08/gone.JPG") is None  # deleted in the cloud: caller decides
    data_reqs = [r for r in recorded if not r.url.path.startswith("/auth/")]
    assert len(data_reqs) == 4
    assert {r.method for r in data_reqs} == {"GET"}
    assert all(r.headers["authorization"] == "Bearer at" for r in data_reqs)


def test_auth_error_surfaces_server_message(monkeypatch):
    def handler(req):
        return httpx.Response(400, json={"msg": "Invalid login credentials"})

    monkeypatch.setattr(
        sb, "_http", httpx.Client(base_url=sb._http.base_url, transport=httpx.MockTransport(handler))
    )
    with pytest.raises(sb.AuthError, match="Invalid login credentials"):
        sb.verify_code("a@b", "000000")


def test_code_request_never_creates_an_account_and_rate_limits_are_user_facing(recorded, monkeypatch):
    sb.request_code("a@b")
    assert recorded[-1].url.path == "/auth/v1/otp" and recorded[-1].method == "POST"
    assert json.loads(recorded[-1].content) == {"email": "a@b", "create_user": False}
    sb.verify_code("a@b", " 123456 ")
    assert json.loads(recorded[-1].content) == {"type": "email", "email": "a@b", "token": "123456"}

    def handler(req):
        return httpx.Response(429, json={"msg": "For security purposes, you can only request this after 42 seconds."})

    monkeypatch.setattr(
        sb, "_http", httpx.Client(base_url=sb._http.base_url, transport=httpx.MockTransport(handler))
    )
    with pytest.raises(sb.AuthError, match="42 seconds"):
        sb.request_code("a@b")


def test_network_failure_raises_offline(monkeypatch):
    def handler(req):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(
        sb, "_http", httpx.Client(base_url=sb._http.base_url, transport=httpx.MockTransport(handler))
    )
    with pytest.raises(sb.Offline):
        sb.select_sites("at")


def test_server_blip_during_refresh_is_not_an_auth_error(monkeypatch):
    def handler(req):
        return httpx.Response(503, text="<html>bad gateway</html>")

    monkeypatch.setattr(
        sb, "_http", httpx.Client(base_url=sb._http.base_url, transport=httpx.MockTransport(handler))
    )
    with pytest.raises(httpx.HTTPStatusError):
        sb.refresh("rt")  # must NOT be AuthError — the caller would sign the user out
