"""T10 packaging on the committed SYNTHETIC artifacts (no training)."""

import json

from ml.eval.check_artifacts import check_files
from ml.eval.package import REQUIRED_FILES, SPECS, dataset_hash, file_hash, model_card


def test_crlf_and_lf_hash_the_same(tmp_path) -> None:
    (tmp_path / "a.csv").write_bytes(b"x,y\r\n1,2\r\n")
    (tmp_path / "b.csv").write_bytes(b"x,y\n1,2\n")
    assert file_hash(tmp_path / "a.csv") == file_hash(tmp_path / "b.csv")
    h = dataset_hash(("a.csv",), tmp_path)
    assert h["synthetic"] and len(h["combined_sha256"]) == 64


def test_every_artifact_is_complete_and_matches_the_data() -> None:
    assert {s.name for s in SPECS} == {"occupancy_forecast", "attrition", "pulse", "workload"}
    for spec in SPECS:
        for f in REQUIRED_FILES:
            assert (spec.directory / f).exists(), f"{spec.name}: {f} missing"
    assert all(ok for _, ok, _ in check_files())


def test_model_cards_report_baselines_and_honesty() -> None:
    for spec in SPECS:
        metrics = json.loads((spec.directory / "metrics.json").read_text("utf-8"))
        hashes = json.loads((spec.directory / "dataset_hash.json").read_text("utf-8"))
        card = model_card(spec, metrics, hashes)
        assert "SYNTHETIC" in card and "Planted-drivers honesty note" in card
        assert "baseline" in card.lower() or "naive" in card.lower() or "rules" in card
        for section in ("## Intended use", "## Data", "## Metrics vs baseline", "## Limitations"):
            assert section in card
