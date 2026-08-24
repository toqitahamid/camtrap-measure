"""A run loads the models in stages, and gives the card back when it is finished.

Five models do not fit on an 8 GB card beside a Windows desktop, and they never had to: the detector
answers "is there an animal here" for every photo, and only then do the distance models look at the few
photos that had one. Holding all of them at once was costing the headroom that decides whether a run
executes on the GPU or out of system memory (CONTEXT, 2026-08-23).

The consequences are easy to undo by accident — an eager load in `__init__`, a forgotten `release`, a
result that no longer says which photo it belongs to — so each is nailed down here.
"""

from pathlib import Path

import pytest

from camtrap_measure import inference

from tests.test_measure import folder, jpeg, results, run

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "src" / "camtrap_measure" / "inference.py").read_text(encoding="utf-8")


def test_constructing_the_backend_loads_no_model():
    """The window opens without waiting for 6 GB of weights, and an idle app holds no VRAM. Every model
    is behind a loader that runs on first use."""
    body = SRC.split("class Real:")[1].split("def _card_warning")[0]
    assert "load_detector(" not in body and "SpeciesNetClassifier(" not in body
    assert "distance.Distance(" not in body
    assert "self._detect = None" in body and "self._dist = None" in body


def test_the_detector_leaves_the_card_before_the_distance_models_arrive():
    """The whole point: peak memory is one stage, not the sum of two."""
    call = SRC.split("def __call__")[1]
    before_stage_two = call.split("self.measuring()")[0]
    assert "self.release(detect=True, measure=False)" in before_stage_two


def test_a_folder_with_no_animals_never_loads_the_distance_models():
    """Most of a real season is empty frames. They cost the detector and nothing else."""
    call = SRC.split("def __call__")[1]
    assert "if not found:\n            return" in call
    assert call.index("if not found:") < call.index("dist = self.measuring()")


def test_releasing_asks_for_the_memory_back_rather_than_hoping():
    """Dropping the reference frees nothing on its own: Python may hold the graph in a cycle, and torch
    keeps freed blocks in a cache no other program can reach."""
    body = SRC.split("def release(")[1].split("@property")[0]
    assert "gc.collect()" in body and "torch.cuda.empty_cache()" in body


def test_a_finished_run_hands_the_card_back(synced, tmp_path, monkeypatch):
    freed = []

    class Backend:
        loaded, batch = ["finding animals"], 16

        def __call__(self, paths, calibration, method, **_):
            yield from inference.fake(paths, calibration, method)

        def release(self, detect=True, measure=True):
            freed.append((detect, measure))
            self.loaded = []

    monkeypatch.setattr(inference, "backend", Backend())
    assert run(synced, folder(tmp_path))["status"] == "done"
    assert freed == [(True, True)]  # both stages, once, when the run ended


def test_the_card_is_handed_back_even_when_the_run_fails(synced, tmp_path, monkeypatch):
    """A crashed run is exactly when the memory must not be left held."""
    freed = []

    class Backend:
        loaded, batch = [], None

        def __call__(self, paths, calibration, method, **_):
            raise RuntimeError("CUDA out of memory")
            yield

        def release(self, detect=True, measure=True):
            freed.append((detect, measure))

    monkeypatch.setattr(inference, "backend", Backend())
    assert run(synced, folder(tmp_path))["status"] == "error"
    assert freed == [(True, True)]


def test_results_are_recorded_by_the_photo_they_name_not_the_order_they_arrive(synced, tmp_path, monkeypatch):
    """Stage one finishes empty frames while stage two is still to come, so answers come back out of
    order. Zipping them against the photo list would file every number under the wrong photo."""
    def backwards(paths, calibration, method, **_):
        yield from reversed(list(inference.fake(paths, calibration, method)))

    monkeypatch.setattr(inference, "backend", backwards)
    names = [f"IMG_{i}.JPG" for i in range(4)]
    d = folder(tmp_path, photos={n: jpeg("2026:05:01 08:00:00") for n in names})
    assert run(synced, d)["status"] == "done"
    for row in results(synced):
        expected = next(inference.fake([Path(row["path"])], {}, "md"))
        assert row["distance_m"] == pytest.approx(expected.detections[row["idx"]].distance_m)


def test_the_run_says_which_stage_it_is_in(synced, tmp_path, monkeypatch):
    """"Nothing is happening" and "it is looking through 400 photos for animals before it measures any"
    look identical without this."""
    seen = []

    def phased(paths, calibration, method, progress=None, **_):
        progress("finding animals", 0, len(paths))
        seen.append("asked")
        yield from inference.fake(paths, calibration, method)

    monkeypatch.setattr(inference, "backend", phased)
    st = run(synced, folder(tmp_path))
    assert seen == ["asked"] and st["status"] == "done"
    assert st["phase"] == "finished"  # and the models are gone with it


def test_the_status_line_reports_what_is_actually_resident(monkeypatch):
    """`state` is written once at warmup; what holds VRAM changes with every run."""
    class Backend:
        loaded, batch = ["measuring distances"], 32

    monkeypatch.setattr(inference, "backend", Backend())
    assert inference.live() == {"loaded": ["measuring distances"], "batch": 32}
    monkeypatch.setattr(inference, "backend", inference.fake)
    assert inference.live() == {"loaded": [], "batch": None}  # the fake holds nothing


def test_skip_and_measure_agree_about_which_photos_need_work(synced, tmp_path, monkeypatch):
    """A second whole-folder run measures nothing again — the staging must not have lost the skip rule."""
    d = folder(tmp_path, photos={f"IMG_{i}.JPG": jpeg("2026:05:01 08:00:00") for i in range(3)})
    assert run(synced, d)["skipped"] == 0
    assert run(synced, d)["skipped"] == 3
