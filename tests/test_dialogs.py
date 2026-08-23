"""Browse…: the desktop window's own folder chooser, and what the page is told when there is no window."""

import webview

from camtrap_measure import dialogs


class FakeWindow:
    """The one pywebview method pick_folder uses; `answer` is what the dialog gives back."""

    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def create_file_dialog(self, dialog_type):
        self.asked.append(dialog_type)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def pick(client, monkeypatch, window) -> dict:
    monkeypatch.setattr(dialogs, "window", window)
    return client.post("/api/folder/pick").json()


def test_browse_returns_the_folder_the_user_chose(client, tmp_path, monkeypatch):
    win = FakeWindow([str(tmp_path)])
    assert pick(client, monkeypatch, win) == {"folder": str(tmp_path.resolve()), "reason": None}
    assert win.asked == [webview.FileDialog.FOLDER]  # a folder chooser, not a file one


def test_browse_without_a_native_window_asks_for_a_typed_path(client, monkeypatch):
    body = pick(client, monkeypatch, None)  # --no-window, or the page opened in a browser
    assert body["folder"] is None and "type" in body["reason"] and "folder path" in body["reason"]


def test_cancelling_the_dialog_is_not_an_error(client, monkeypatch):
    assert pick(client, monkeypatch, FakeWindow(None)) == {"folder": None, "reason": "No folder chosen."}


def test_a_dialog_that_will_not_open_says_why(client, monkeypatch):
    body = pick(client, monkeypatch, FakeWindow(RuntimeError("no GUI toolkit")))
    assert body["folder"] is None and "no GUI toolkit" in body["reason"] and "type the folder path" in body["reason"]
