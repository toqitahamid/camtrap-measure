"""Local state: cached login session (JSON file), the SQLite mirror of cloud data, and measurement results."""

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
create table if not exists photos (
    path text primary key, site text not null, captured_at text, make text, model text,
    calibration_image text, held_reason text, measured_at text not null);
create table if not exists detections (
    path text not null, idx integer not null, method text not null,
    x1 real, y1 real, x2 real, y2 real, species text, confidence real,
    distance_m real, q05_m real, q95_m real, match_score real,
    primary key (path, idx, method));
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


def config() -> dict:
    """Installer-written settings (`hf_token`, ...); {} when absent."""
    try:
        return json.loads((DATA_DIR / "config.json").read_text())
    except (OSError, ValueError):
        return {}


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
            "insert or replace into calibrations values "
            "(:site, :image_name, :updated_at, :captured_at, :ok, :reason, :model)",
            fits,
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
    """{(site, image_name): annotation updated_at} of every green calibration — skip their refits."""
    with closing(_db()) as con:
        return {(r["site"], r["image_name"]): r["updated_at"]
                for r in con.execute("select site, image_name, updated_at from calibrations where ok")}


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


# --- results -----------------------------------------------------------------

def record(photo: dict, method: str, detections: list[dict]) -> None:
    """One current answer per photo: upsert its row, replace its detections for this method.
    A held photo (held_reason set) keeps no numbers at all — every method's rows go."""
    # ponytail: photo key = absolute path; a moved folder simply re-measures.
    photo = {**photo, "measured_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    with closing(_db()) as con, con:
        con.execute("insert or replace into photos (path, site, captured_at, make, model, calibration_image, held_reason, measured_at) "
                    "values (:path, :site, :captured_at, :make, :model, :calibration_image, :held_reason, :measured_at)", photo)
        if photo["held_reason"]:
            con.execute("delete from detections where path=?", (photo["path"],))
        else:
            con.execute("delete from detections where path=? and method=?", (photo["path"], method))
        con.executemany(
            "insert into detections values (:path, :idx, :method, :x1, :y1, :x2, :y2, :species, :confidence, "
            ":distance_m, :q05_m, :q95_m, :match_score)",
            [{**d, "path": photo["path"], "idx": i, "method": method} for i, d in enumerate(detections)],
        )


def detections() -> list[dict]:
    """Every detection row joined with its photo (camera, timestamp, EXIF make/model, calibration used)."""
    with closing(_db()) as con:
        rows = con.execute(
            "select p.site, p.captured_at, p.make, p.model, p.calibration_image, d.* from detections d "
            "join photos p on p.path = d.path order by p.site, p.captured_at, d.path, d.method, d.idx").fetchall()
    return [dict(r) for r in rows]
