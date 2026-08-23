"""The native folder chooser, kept out of the API module so the engine still imports without a GUI toolkit.

pywebview can only raise a dialog from a window it owns, so `main.py` hands the window it created to
`window` here at start-up. There is no window when the engine runs with `--no-window` or when the page was
opened in an ordinary browser; then the page falls back to a typed path, which is why every refusal comes
back as a plain sentence the technician can act on rather than an error.
"""

from pathlib import Path

window = None  # set by main.py once the desktop window exists; None means "no native dialog here"


def pick_folder() -> tuple[str | None, str | None]:
    """Ask the desktop window for a folder → (absolute path, None), or (None, why not) when there is no
    window to ask, the user cancelled, or the toolkit refused."""
    if window is None:
        return None, "This page cannot open the folder chooser — type or paste the folder path instead."
    import webview  # imported late: needs a GUI toolkit, and the engine must import on a headless machine

    try:
        chosen = window.create_file_dialog(webview.FileDialog.FOLDER)
    except Exception as e:  # a toolkit that will not open the dialog must not take the app down
        return None, f"The folder chooser did not open ({type(e).__name__}: {e}) — type the folder path instead."
    if not chosen:
        return None, "No folder chosen."
    picked = chosen if isinstance(chosen, str) else chosen[0]  # the dialog answers with a sequence; older ones a bare path
    return str(Path(picked).expanduser().resolve()), None
