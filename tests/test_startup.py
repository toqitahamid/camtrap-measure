"""The window comes first; the engine starts behind it.

2026-09-29: the first start after an update took about two minutes from the click to a window, with nothing
on screen, and the researcher clicked again. The engine's imports were done before the window existed. Now
the window opens with a Starting page, the engine is imported and started once the window is shown, and the
window then goes to the engine's page. Each step writes its time to the launcher's log.
"""

import subprocess
import sys
import types

import pytest

import camtrap_measure.main as main
from camtrap_measure import dialogs, win_icon


def test_importing_the_launcher_does_not_import_the_engine():
    """A fresh interpreter: other tests have imported the engine into this one already."""
    code = "import sys, camtrap_measure.main; print(sorted(m for m in ('camtrap_measure.api', 'torch', 'uvicorn') if m in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"


class Shown:
    def __init__(self, log):
        self.log = log

    def wait(self, timeout):
        self.log.append("shown")
        return True


class FakeWindow:
    def __init__(self, log, **kw):
        self.log, self.kw = log, kw
        self.events = types.SimpleNamespace(shown=Shown(log))

    def load_url(self, url):
        self.log.append(("load_url", url))

    def load_html(self, html):
        self.log.append(("load_html", html))


@pytest.fixture
def fake_webview(monkeypatch):
    """pywebview without a screen: create_window records, start runs the GUI thread's function inline."""
    log = []
    mod = types.ModuleType("webview")
    mod.settings = {}

    def create_window(title, url=None, html=None, **kw):
        log.append(("create_window", title, url, html))
        return FakeWindow(log, **kw)

    def start(func, args, icon=None):
        log.append(("start", icon))
        func(*args)

    mod.create_window, mod.start = create_window, start
    monkeypatch.setitem(sys.modules, "webview", mod)
    monkeypatch.setattr(dialogs, "window", None)
    monkeypatch.setattr(win_icon, "identify", lambda: log.append("identify"))
    monkeypatch.setattr(main, "_wear_icon", lambda w: log.append("icon"))
    monkeypatch.setattr(main, "shutdown", lambda: log.append("shutdown"))
    monkeypatch.setattr(main, "say", lambda msg: log.append(("say", msg)))
    return log


def test_the_window_opens_on_the_starting_page_before_the_engine_starts(fake_webview, monkeypatch):
    log = fake_webview

    def engine():
        log.append("engine")
        return "http://127.0.0.1:1234"

    monkeypatch.setattr(main, "start_engine", engine)
    main.run_window()
    steps = [s if isinstance(s, str) else s[0] for s in log]
    assert steps == ["identify", "create_window", "start", "shown", "say", "icon", "engine", "load_url", "shutdown"]
    create = log[1]
    assert create[1] == win_icon.TITLE and create[2] is None and create[3] == main.STARTING_PAGE
    assert ("load_url", "http://127.0.0.1:1234") in log
    assert log[4][1].startswith("window shown in ")
    assert log[2] == ("start", str(win_icon.ICON))
    assert dialogs.window is not None  # the folder chooser has a window to open on


def test_an_engine_that_fails_leaves_the_window_saying_so(fake_webview):
    log = fake_webview

    def broken():
        raise RuntimeError("no engine today")

    window = FakeWindow(log)
    main._bring_up(window, engine=broken, wear_icon=lambda w: None)
    assert ("load_html", main.FAILED_PAGE) in log
    said = [s[1] for s in log if isinstance(s, tuple) and s[0] == "say"]
    assert any("engine did not start: RuntimeError: no engine today" in s for s in said)
    assert not any(isinstance(s, tuple) and s[0] == "load_url" for s in log)


def test_the_starting_pages_are_plain_and_self_contained():
    for page in (main.STARTING_PAGE, main.FAILED_PAGE):
        assert "http" not in page and "<script" not in page  # no server, no files: it shows before the engine
        assert "—" not in page  # no em dashes in what the researcher reads
    assert "Starting&hellip;" in main.STARTING_PAGE
    assert "#0e1013" in main.STARTING_PAGE and "#e8a13c" in main.STARTING_PAGE  # --bg, --amber


def test_the_engine_says_how_long_it_took(monkeypatch):
    said = []
    monkeypatch.setattr(main, "say", said.append)
    url = main.start_engine()
    assert url.startswith("http://127.0.0.1:")
    assert said[0].startswith("engine imported in ") and said[1].startswith("engine up in ")


def test_the_server_timeout_is_far_above_the_measured_start():
    """Measured 2026-09-29: the server is up 0.1 s after the import, warm; a cold start after an update ran
    about ten times slower. The import is not under the limit at all (see ENGINE_START_TIMEOUT)."""
    assert main.ENGINE_START_TIMEOUT >= 60
