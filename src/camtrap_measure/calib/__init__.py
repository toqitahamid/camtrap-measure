"""4-parameter ground-plane calibration, ported from the research repo.

Source: ../distance_estimation @ 6a6eed5741a7aedc5ae8accabd3b3600fb0ff845
(calib/data.py, model_a.py, model_b.py, qc.py + tests). Imports made relative,
`load_photo(path)` became `from_annotation(dict)` (rows come from Supabase, not
files), `cross_photo` and `report` left behind (CSV/overlay reporting only).
Fit math is byte-for-byte the research code — change it there first.
"""
