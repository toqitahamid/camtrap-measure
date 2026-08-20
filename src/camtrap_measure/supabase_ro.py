"""The only Supabase client in this app — and it can only read.

Hard constraint (CONTEXT.md): CamTrap Measure never writes to Supabase. This
module talks to the cloud over plain REST and exposes auth plus exactly three
read operations. There is no write method to call; tests/test_supabase_ro.py
asserts that stays true and that no other module talks to Supabase.
"""

import httpx

__all__ = [
    "AuthError",
    "Offline",
    "sign_in",
    "refresh",
    "select_annotations",
    "select_sites",
    "download_object",
]

SUPABASE_URL = "https://uggjzcbozdxvuawxddrn.supabase.co"
# Publishable key: public by design, RLS does the gatekeeping.
SUPABASE_KEY = "sb_publishable_GYH2YfezrNFWjOWN6F5YDA_DxlQnevY"
_PAGE = 1000  # must be <= the project's PostgREST max-rows (default 1000) or paging ends early

_http = httpx.Client(base_url=SUPABASE_URL, headers={"apikey": SUPABASE_KEY}, timeout=30)


class AuthError(Exception):
    """Sign-in or refresh rejected by Supabase; message is user-readable."""


class Offline(Exception):
    """No route to the cloud. Callers degrade politely, never error."""


def _send(method: str, path: str, **kw) -> httpx.Response:
    try:
        return _http.request(method, path, **kw)
    except httpx.TransportError as e:
        raise Offline(str(e)) from e


def _token(grant: str, **body) -> dict:
    r = _send("POST", "/auth/v1/token", params={"grant_type": grant}, json=body)
    if r.status_code in (400, 401, 403):  # credentials rejected — not a 5xx/429 blip
        raise AuthError(_msg(r))
    r.raise_for_status()
    return r.json()


def _msg(r: httpx.Response) -> str:
    try:
        return r.json().get("msg") or r.text
    except ValueError:
        return r.text


def sign_in(email: str, password: str) -> dict:
    """Email/password sign-in → {access_token, refresh_token, user{email}}."""
    return _token("password", email=email, password=password)


def refresh(refresh_token: str) -> dict:
    """Trade a cached refresh token for a fresh session (tokens rotate)."""
    return _token("refresh_token", refresh_token=refresh_token)


def _get(path: str, access_token: str, **params) -> httpx.Response:
    r = _send("GET", path, params=params, headers={"Authorization": f"Bearer {access_token}"})
    if r.status_code == 401:
        raise AuthError("Session expired — please sign in again")
    r.raise_for_status()
    return r


def _select(table: str, access_token: str, select: str, order: str) -> list[dict]:
    rows: list[dict] = []
    while True:
        page = _get(
            f"/rest/v1/{table}", access_token,
            select=select, order=order, limit=_PAGE, offset=len(rows),
        ).json()
        rows += page
        if len(page) < _PAGE:
            return rows


def select_annotations(access_token: str) -> list[dict]:
    """Every annotation row (schema-v2 JSON in `data`)."""
    return _select(
        "annotations", access_token,
        "site,image_name,storage_path,status,labeler,updated_at,data",
        "site,image_name",
    )


def select_sites(access_token: str) -> list[dict]:
    """Camera registry: [{name}]."""
    return _select("sites", access_token, "name", "name")


def download_object(access_token: str, path: str, bucket: str = "photos") -> bytes | None:
    """Raw bytes of one storage object (flag photo, EXIF intact); None if it no longer exists."""
    r = _send("GET", f"/storage/v1/object/{bucket}/{path}", headers={"Authorization": f"Bearer {access_token}"})
    if r.status_code == 404:
        return None
    if r.status_code == 401:
        raise AuthError("Session expired — please sign in again")
    r.raise_for_status()
    return r.content
