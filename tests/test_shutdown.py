"""Closing the window must end the process.

The models hold a CUDA context worth gigabytes and the driver only hands it back when the process really
dies. On the dept's 8 GB card, shared with the desktop and a browser, a launcher that lingers is the
difference between the next run fitting and dying on an out-of-memory error (seen 2026-08-23).
"""

import camtrap_measure.main as main
from camtrap_measure import measure


RUNNING = {"status": "running", "cancel": False, "started": 0.0, "done": 0, "skipped": 0,
           "unreadable": 0, "total": 1, "elapsed_s": 0.0}


def test_closing_the_window_ends_the_process():
    codes = []
    main.shutdown(exit_process=codes.append)
    assert codes == [0]


def test_a_run_in_flight_is_stopped_before_the_process_goes(monkeypatch):
    """The photo in flight gets its moment to write its row — the same promise a cancel already makes."""
    run = {**RUNNING}
    monkeypatch.setattr(measure, "current", run)

    def stop_when_asked(_code):
        assert run["cancel"], "the run was left going"

    def fake_sleep(_s):  # the run's own thread would notice the flag; here nothing else is running
        run["status"] = "cancelled"

    monkeypatch.setattr(main.time, "sleep", fake_sleep)
    main.shutdown(exit_process=stop_when_asked)
    assert run["cancel"] and run["status"] == "cancelled"


def test_it_does_not_wait_for_ever_on_a_run_that_will_not_stop(monkeypatch):
    """A photo wedged in the GPU must not keep the window's process alive holding the card."""
    monkeypatch.setattr(measure, "current", {**RUNNING})
    naps = []
    monkeypatch.setattr(main.time, "sleep", naps.append)
    codes = []
    main.shutdown(exit_process=codes.append)
    assert codes == [0] and 0 < sum(naps) <= 3  # gave up after a couple of seconds and left anyway
