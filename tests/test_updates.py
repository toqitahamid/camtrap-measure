"""A new version waits for the next start; the window says so until the user acts (2026-09-29).

The launcher starts the app at once and fetches behind it; a newer version is written to a file the launcher
names in CAMTRAP_UPDATE_FILE. The engine reads that file, and "Restart now" starts the launcher again through
CAMTRAP_LAUNCH_VBS and then closes the way the window close does.
"""

import json

import pytest
from fastapi.testclient import TestClient

from camtrap_measure import api, measure, updates

client = TestClient(api.app)


@pytest.fixture
def launched(monkeypatch, tmp_path):
    """The two variables the launcher sets for the app's process."""
    vbs = tmp_path / "launch.vbs"
    vbs.write_text("' the shortcut", encoding="ascii")
    update = tmp_path / "update.json"
    monkeypatch.setenv("CAMTRAP_UPDATE_FILE", str(update))
    monkeypatch.setenv("CAMTRAP_LAUNCH_VBS", str(vbs))
    return update, vbs


def test_no_file_means_no_update(launched):
    assert client.get("/api/update").json() == {"ready": False, "commit": None, "describe": None, "can_restart": True}


def test_a_written_file_means_an_update_is_waiting(launched):
    update, _ = launched
    # PowerShell 5.1's Set-Content -Encoding UTF8 writes a byte order mark; it must still read
    update.write_bytes(b"\xef\xbb\xbf" + json.dumps({"commit": "abc1234def", "describe": "v0.2.0-41-gabc1234"}).encode())
    body = client.get("/api/update").json()
    assert body == {"ready": True, "commit": "abc1234def", "describe": "v0.2.0-41-gabc1234", "can_restart": True}


def test_a_half_written_file_reads_as_nothing_yet(launched):
    update, _ = launched
    update.write_text('{"commit": "abc', encoding="utf-8")
    assert client.get("/api/update").json()["ready"] is False


def test_started_without_the_launcher_there_is_no_notice_and_no_restart(monkeypatch):
    monkeypatch.delenv("CAMTRAP_UPDATE_FILE", raising=False)
    monkeypatch.delenv("CAMTRAP_LAUNCH_VBS", raising=False)
    assert client.get("/api/update").json() == {"ready": False, "commit": None, "describe": None, "can_restart": False}
    r = client.post("/api/update/restart")
    assert r.status_code == 400 and "desktop icon" in r.json()["detail"]


def test_restart_now_starts_the_launcher_then_leaves(launched, monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "relaunch", lambda: calls.append("relaunch"))
    monkeypatch.setattr(api, "_leave_soon", lambda: calls.append("leave"))
    r = client.post("/api/update/restart")
    assert r.status_code == 200 and r.json() == {"restarting": True}
    assert calls == ["relaunch", "leave"]  # the launcher first: if it cannot start, the app stays open


def test_restart_is_refused_during_a_run(launched, monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "relaunch", lambda: calls.append("relaunch"))
    monkeypatch.setattr(api, "_leave_soon", lambda: calls.append("leave"))
    monkeypatch.setattr(measure, "current", {"status": "running"})
    r = client.post("/api/update/restart")
    assert r.status_code == 409 and r.json()["detail"] == "Finish or stop the run first."
    assert calls == []


def test_the_new_launcher_waits_for_this_process_and_outlives_it(launched, monkeypatch):
    _, vbs = launched
    seen = []

    def popen(args, creationflags, close_fds):
        seen.append((args, creationflags))

    updates.relaunch(popen=popen)
    (args, flags), = seen
    assert args[0].lower().endswith("wscript.exe") and args[1] == str(vbs)
    assert args[2:] == ["-AfterPid", str(__import__("os").getpid())]
    assert flags & updates.DETACHED_PROCESS and flags & updates.CREATE_BREAKAWAY_FROM_JOB


def test_a_job_that_forbids_breaking_away_still_gets_a_launcher(launched):
    flags_tried = []

    def popen(args, creationflags, close_fds):
        flags_tried.append(creationflags)
        if creationflags & updates.CREATE_BREAKAWAY_FROM_JOB:
            raise PermissionError("access denied")

    updates.relaunch(popen=popen)
    assert len(flags_tried) == 2 and not flags_tried[1] & updates.CREATE_BREAKAWAY_FROM_JOB
