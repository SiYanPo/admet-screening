# -*- coding: utf-8 -*-
"""工作包 A/C：结构变体提交清单 + 预测值位移。"""
import sys
sys.path.insert(0, ".")

from adt import ac_plan as AP
from adt import pred_displacement as PD

COMPS = [
    ("A", "O=C(/C=C/c1ccc(O)cc1)OC[C@@H](O)CO[C@@H]1O[C@H](CO)[C@@H](O)[C@H](O)[C@H]1O"),
    ("B", "CC(=O)OC[C@@H](COC(=O)/C=C/c1ccc(O)cc1)O[C@@H]1O[C@H](CO)[C@@H](O)[C@H](O)[C@H]1O"),
]


def test_original_is_never_noop():
    rows = AP.build(COMPS)
    orig = [r for r in rows if r["variant"] == "original"]
    assert len(orig) == 2
    assert all(r["noop"] == "N" for r in orig)      # 基线必须提交


def test_variants_generated_and_noop_flagged():
    rows = AP.build(COMPS, kinds=("original", "stereo_removed", "tautomer"))
    kinds = {r["variant"] for r in rows}
    assert {"original", "stereo_removed", "tautomer"} <= kinds
    # 去立体后 SMILES 必变 → 不是 noop
    sr = [r for r in rows if r["variant"] == "stereo_removed"]
    assert all(r["noop"] == "N" for r in sr)


def test_batches_skip_noop():
    rows = [dict(compound_id="X", variant="original", smiles="CCO", note="", noop="N"),
            dict(compound_id="X", variant="tautomer", smiles="CCO", note="", noop="Y"),
            dict(compound_id="Y", variant="original", smiles="CCC", note="", noop="N")]
    b = AP.to_batches(rows, size=5, skip_noop=True)
    flat = [r for bb in b for r in bb]
    assert len(flat) == 2                            # noop 被跳过


def test_controls_go_first():
    rows = AP.build(COMPS, include_controls=True)
    assert rows[0]["compound_id"].startswith("CTRL_")


def test_write_creates_batch_files(tmp_path):
    rows = AP.build(COMPS, include_controls=True)
    batches = AP.to_batches(rows, size=5)
    AP.write(str(tmp_path), rows, batches, dict(note="t"))
    assert (tmp_path / "ac_variants.csv").exists()
    assert (tmp_path / "batches" / "batch_01.txt").exists()


def _long(rows, d):
    import io, os
    p = os.path.join(str(d), "v.csv")
    with io.open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write("compound_id,variant,endpoint,value\n")
        for r in rows:
            fh.write(",".join(str(x) for x in r) + "\n")
    return p


def test_displacement_zero_for_identical_variant(tmp_path):
    p = _long([("A", "original", "hERG", 0.2),
               ("A", "stereo_removed", "hERG", 0.2)], tmp_path)
    rows = PD.load_long(p)
    disp = PD.displacement(rows)
    assert disp[0]["mean_abs_shift"] == 0.0
    assert disp[0]["nonzero_frac"] == 0.0


def test_displacement_and_ratio_vs_source(tmp_path):
    p = _long([("A", "original", "hERG", 0.20),
               ("A", "stereo_removed", "hERG", 0.42),
               ("B", "original", "hERG", 0.30),
               ("B", "stereo_removed", "hERG", 0.32)], tmp_path)
    rows = PD.load_long(p)
    disp = PD.displacement(rows)
    # |0.42-0.20|=0.22, |0.32-0.30|=0.02 → 均值 0.12
    assert abs(disp[0]["mean_abs_shift"] - 0.12) < 1e-6
    cmp_rows = PD.compare(disp, {"hERG": dict(mean_abs_diff=0.06, spearman=0.2)})
    assert abs(cmp_rows[0]["ratio_vs_source"] - 2.0) < 1e-6
    assert "Gate 0" in PD.verdict(cmp_rows)          # 比值>1 → Gate 0 必要


def test_verdict_without_source_reference():
    rows = [dict(endpoint="x", variant="v", n=1, mean_abs_shift=0.1,
                 max_abs_shift=0.1, nonzero_frac=1.0, source_shift=None,
                 ratio_vs_source=None)]
    assert "无法比较" in PD.verdict(rows)


# ---------------- 阈值翻转（评审点名：比平均位移更致命）----------------
def test_threshold_flips_counts_crossings(tmp_path):
    p = _long([("A", "original", "DILI", 0.68),
               ("A", "stereo_removed", "DILI", 0.14),     # 0.68→0.14 翻转
               ("B", "original", "DILI", 0.60),
               ("B", "stereo_removed", "DILI", 0.55)], tmp_path)  # 未翻（两侧都 >=0.5）
    rows = PD.load_long(p)
    counts, detail = PD.threshold_flips(rows)
    assert counts[("DILI", "stereo_removed")] == 1
    assert len(detail) == 1
    assert detail[0]["compound_id"] == "A"
    assert abs(detail[0]["delta"] - (-0.54)) < 1e-9


def test_threshold_flips_skips_continuous_endpoints(tmp_path):
    p = _long([("A", "original", "logP", 2.0),
               ("A", "stereo_removed", "logP", 0.1)], tmp_path)  # logP 不计翻转
    rows = PD.load_long(p)
    counts, detail = PD.threshold_flips(rows)
    assert counts == {} and detail == []


def test_flips_surface_in_note_and_csv(tmp_path):
    p = _long([("A", "original", "DILI", 0.68),
               ("A", "stereo_removed", "DILI", 0.14)], tmp_path)
    rows = PD.load_long(p)
    disp = PD.displacement(rows)
    counts, detail = PD.threshold_flips(rows)
    cmp_rows = PD.compare(disp, {"DILI": dict(mean_abs_diff=0.52)}, flip_check=counts)
    assert cmp_rows[0]["threshold_flips"] == 1
    PD.write(str(tmp_path), cmp_rows, flip_detail=detail)
    assert (tmp_path / "threshold_flips.csv").exists()
    txt = (tmp_path / "pred_displacement_note.md").read_text(encoding="utf-8")
    assert "阈值翻转明细" in txt


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
