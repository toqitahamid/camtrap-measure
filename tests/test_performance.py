"""What makes a run fast, and what would silently make it slow again.

Every one of these is a fix for something measured on the dept's RTX 2060 SUPER on 2026-08-23, where a
photo took 33 seconds and the same run repeated took 3. None of them changes what the app computes by
more than the method already moves between repeat runs, and each is one careless edit away from coming
back — so each is nailed down here. The numbers themselves are in CONTEXT.md and reproducible with
`uv run python scripts/profile_run.py`.
"""

from pathlib import Path

import pytest

from camtrap_measure import distance, inference

ROOT = Path(__file__).resolve().parent.parent


def test_the_density_estimate_is_chunked_and_gives_the_same_answer():
    """RoMa's own kde builds the whole 40000x40000 distance matrix — 3.2 GB, several times over, which
    is more than the card has. Chunked it is the same sum, so the published inlier gate still holds."""
    torch = pytest.importorskip("torch")
    kde = pytest.importorskip("romatch.utils.kde").kde
    torch.manual_seed(0)
    for n, chunk in ((1000, 4096), (5000, 1024), (4097, 4096)):
        x = torch.rand(n, 4)
        assert torch.equal(kde(x.clone()), distance.kde_chunked(x.clone(), chunk=chunk))


def test_the_chunked_density_is_what_roma_actually_calls():
    """romatch.models.matcher imported the name at module load, so patching the module it came from
    would change nothing at all."""
    pytest.importorskip("torch")
    matcher = pytest.importorskip("romatch.models.matcher")
    distance.use_chunked_kde()
    assert matcher.kde is distance.kde_chunked


def test_emulated_bfloat16_does_not_count_as_supported():
    """torch.cuda.is_bf16_supported() says True on cards that only emulate bf16, and the emulation is
    slower than fp32: 122 ms against 25 ms for fp16 on the dept card. The app was choosing it."""
    src = (ROOT / "src" / "camtrap_measure" / "distance.py").read_text(encoding="utf-8")
    assert "including_emulation=False" in src
    # the bare call is the bug: fast fidelity must reach the precision through the helper, never from it
    assert "fidelity == RESEARCH or native_bf16(torch)" in src


def test_a_small_card_gets_the_smaller_warp_and_a_big_one_keeps_the_research_default():
    """Only under fast fidelity. At 864 one photo needs 6.3 GB — more than Windows leaves free on an 8 GB
    card, and the driver serves the rest from system memory, where the same photo takes ten times as
    long. The published pipeline keeps 864 whatever the card, and pays for it."""
    class Card:
        def __init__(self, gb):
            self.total_memory = int(gb * 2**30)

    class FakeTorch:
        def __init__(self, gb):
            self.cuda = type("cuda", (), {"get_device_properties": staticmethod(lambda i: Card(gb))})

    d = object.__new__(distance.Distance)
    d.fidelity = distance.FAST
    for gb, expected in ((8, distance.UPSAMPLE_RES_TIGHT), (12, distance.UPSAMPLE_RES),
                         (24, distance.UPSAMPLE_RES)):
        d.device, d.torch = "cuda", FakeTorch(gb)
        assert d._upsample_res() == expected, gb
    d.device = "cpu"
    assert d._upsample_res() == distance.UPSAMPLE_RES  # nothing to fit into; keep what the research ran
    d.device, d.fidelity = "cuda", distance.RESEARCH
    assert d._upsample_res() == distance.UPSAMPLE_RES  # a small card does not get to change the published setting


def test_the_batch_probe_gives_its_memory_back():
    """The probe's largest successful trial stayed in the allocator's cache — 2.9 GB held and unused,
    which is exactly the headroom the run then lacked."""
    src = (ROOT / "src" / "camtrap_measure" / "inference.py").read_text(encoding="utf-8")
    after_probe = src.split("self.batch = self._probe_batch()")[1].split("else:")[0]
    assert "torch.cuda.empty_cache()" in after_probe


def test_the_status_line_can_name_the_card():
    """"Is it really using the GPU" must be answerable from the app's own window, not from nvidia-smi."""
    assert "gpu" in inference.state and "precision" in inference.state
    src = (ROOT / "src" / "camtrap_measure" / "inference.py").read_text(encoding="utf-8")
    assert "get_device_properties(0)" in src and "CPU only" in src


# --- which settings a run used, and that it is never a silent choice ------------------------------

def test_the_published_pipeline_is_what_runs_unless_someone_asks_otherwise(monkeypatch, tmp_path):
    """The app exists to put the paper's numbers in front of a technician. A number that is nearly the
    paper's is worth less than a slow one that is, so speed is opt-in and never the default."""
    from camtrap_measure import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.delenv("CAMTRAP_FIDELITY", raising=False)
    assert inference.fidelity() == distance.RESEARCH

    store.save_config({"fidelity": distance.FAST})
    assert inference.fidelity() == distance.FAST          # config.json: the installed machine's setting
    monkeypatch.setenv("CAMTRAP_FIDELITY", distance.RESEARCH)
    assert inference.fidelity() == distance.RESEARCH      # the environment wins, for one run

    monkeypatch.setenv("CAMTRAP_FIDELITY", "quick")
    assert inference.fidelity() == distance.RESEARCH      # a typo must not quietly change the numbers


def test_changing_the_settings_re_measures_instead_of_mixing_two_kinds_of_metres():
    """Fidelity counts the way a relabel counts: different settings, different number. Two of them in one
    folder with nothing on screen to tell them apart is the failure being prevented."""
    from camtrap_measure import measure

    cal = {"image_name": "IMG_0004.JPG", "updated_at": "2026-08-01T00:00:00"}
    done = {"method": "md", "fidelity": distance.RESEARCH, "calibration_image": "IMG_0004.JPG",
            "calibration_version": "2026-08-01T00:00:00"}
    assert measure.current_answer(done, cal, "md", distance.RESEARCH)
    assert not measure.current_answer(done, cal, "md", distance.FAST)
    assert not measure.current_answer({**done, "fidelity": None}, cal, "md", distance.RESEARCH)  # measured before 19


def test_the_export_says_which_settings_made_each_number():
    from camtrap_measure import report

    assert "fidelity" in report.COLUMNS
    assert "research = the published pipeline" in report.DOC
