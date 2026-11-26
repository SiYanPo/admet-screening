# -*- coding: utf-8 -*-
"""模块O：失效模式三层检测框架。"""
import sys
sys.path.insert(0, ".")

from adt import failure_layers as FL


def test_layer_mapping_covers_all_seven_modes():
    modes = ["unit_isomerism", "silent_empty_source", "pseudo_consensus",
             "single_group_verdict", "phys_range_violation",
             "domain_block_unwired", "version_drift"]
    for m in modes:
        assert m in FL.MODE_TO_LAYER, m
    assert FL.MODE_TO_LAYER["unit_isomerism"] == "contract"
    assert FL.MODE_TO_LAYER["pseudo_consensus"] == "adjudication"
    assert FL.MODE_TO_LAYER["domain_block_unwired"] == "architecture"


def test_group_and_summarize():
    hits = [
        dict(mode="unit_isomerism", compound_id="C1", endpoint="E", source="s",
             detail="x"),
        dict(mode="pseudo_consensus", compound_id="C2", endpoint="E", source="",
             detail="y"),
        dict(mode="version_drift", compound_id="C3", endpoint="E", source="s",
             detail="z"),
    ]
    g = FL.group(hits)
    assert len(g["contract"]) == 1 and len(g["adjudication"]) == 1
    assert len(g["architecture"]) == 1
    s = FL.summarize(hits, n_measurements=10)
    by = {r["layer"]: r for r in s["rows"]}
    assert by["contract"]["n_hits"] == 1
    assert by["contract"]["trigger_rate"] == 0.1
    assert s["total"]["n_hits"] == 3


def test_specificity_note_says_zero_is_not_specificity():
    s = FL.summarize([], n_measurements=100, curated=True)
    assert "不" in s["specificity_note"]
    assert "特异性" in s["specificity_note"]


def test_write_outputs(tmp_path):
    hits = [dict(mode="unit_isomerism", compound_id="C1", endpoint="E",
                 source="s", detail="x")]
    s = FL.summarize(hits, n_measurements=5)
    p1, p2, p3 = FL.write(str(tmp_path), hits, s)
    assert (tmp_path / "failure_layers.csv").exists()
    assert (tmp_path / "failure_layers_hits.csv").exists()
    txt = (tmp_path / "failure_layers_note.md").read_text(encoding="utf-8")
    assert "特异性约束" in txt


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
