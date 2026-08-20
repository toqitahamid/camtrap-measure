"""Local state: cached login session (JSON file) and the SQLite mirror of cloud data."""

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(os.environ.get("CAMTRAP_DATA_DIR", Path.home() / ".camtrap-measure"))

_SCHEMA = """
create table if not exists sites (name text primary key);
create table if not exists annotations (
    site text not null, image_name text not null, storage_path text,
    status text, labeler text, updated_at text, data text,
    primary key (site, image_name));
create table if not exists meta (key text primary key, value text);
create table if not exists calibrations (
    site text not null, image_name text not null, updated_at text,
    captured_at text, ok integer not null, reason text, model text,
    primary key (site, image_name));
"""


def _db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA_DIR / "camtrap.db")
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


# --- session -----------------------------------------------------------------

def _session_file() -> Path:
    return DATA_DIR / "session.json"


def session() -> dict | None:
    """{refresh_token, email} or None. Plain file on the dept machine; the
    refresh token is the only secret and is revocable from the Supabase dashboard."""
    try:
        return json.loads(_session_file().read_text())
    except (OSError, ValueError):
        return None


def save_session(s: dict | None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if s is None:
        _session_file().unlink(missing_ok=True)
    else:
        fd = os.open(_session_file(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(s))


# --- mirror ------------------------------------------------------------------

def replace_mirror(annotations: list[dict], sites: list[dict], fits: list[dict] = ()) -> str:
    """Atomically replace the local copy of cloud tables and upsert new calibration fits;
    calibrations of annotations gone from the cloud are dropped. Returns the sync time."""
    # ponytail: full replace, not row upsert — also drops cloud-deleted rows. ~300 rows today.
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with closing(_db()) as con, con:
        con.execute("delete from annotations")
        con.execute("delete from sites")
        con.executemany(
            "insert into annotations values (?,?,?,?,?,?,?)",
            [
                (a["site"], a["image_name"], a.get("storage_path"), a.get("status"),
                 a.get("labeler"), a.get("updated_at"), json.dumps(a.get("data")))
                for a in annotations
            ],
        )
        con.executemany("insert into sites values (?)", [(s["name"],) for s in sites])
        con.executemany(
            "insert or replace into calibrations values (?,?,?,?,?,?,?)",
            [(f["site"], f["image_name"], f["updated_at"], f["captured_at"], f["ok"], f["reason"], f["model"])
             for f in fits],
        )
        con.execute(
            "delete from calibrations where (site, image_name) not in (select site, image_name from annotations)"
        )
        con.execute("insert or replace into meta values ('last_sync', ?)", (now,))
    return now


def annotations() -> list[dict]:
    with closing(_db()) as con:
        rows = con.execute("select * from annotations order by site, image_name").fetchall()
    return [{**dict(r), "data": json.loads(r["data"])} for r in rows]


def sites() -> list[str]:
    with closing(_db()) as con:
        return [r["name"] for r in con.execute("select name from sites order by name")]


def calibration_versions() -> dict[tuple[str, str], str | None]:
    """{(site, image_name): annotation updated_at it was fitted from} — skip refits of unchanged rows."""
    with closing(_db()) as con:
        return {(r["site"], r["image_name"]): r["updated_at"]
                for r in con.execute("select site, image_name, updated_at from calibrations")}


def calibrations() -> list[dict]:
    with closing(_db()) as con:
        rows = con.execute("select * from calibrations order by site, image_name").fetchall()
    return [{**dict(r), "ok": bool(r["ok"])} for r in rows]


def summary() -> dict:
    with closing(_db()) as con:
        last = con.execute("select value from meta where key='last_sync'").fetchone()
        return {
            "last_sync": last["value"] if last else None,
            "annotations": con.execute("select count(*) from annotations").fetchone()[0],
            "sites": con.execute("select count(*) from sites").fetchone()[0],
        }
