# -*- coding: utf-8 -*-
"""P6 去污染回归测试：Tanimoto 近重复剔除 + 三档敏感性（合成数据，不依赖真实前瞻数据）。

说明：用 RDKit 规范后等价的 SMILES（如苯的 Kekulé 式与芳香式）构造 Tanimoto=1.0 的
近重复对，保证断言确定性；真实"训练污染 36.65%"场景的两版对照数值需真实前瞻数据闭环。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import decontamination


def test_remove_similar_drops_equivalent_encodings():
    # 苯的两种写法规范后等价 → Tanimoto=1.0，0.7 档必剔除其一
    smis = ["c1ccccc1", "C1=CC=CC=C1", "CCO", "CN1C=NC2=C1C(=O)N(C)C(=O)N2C"]
    r = decontamination.remove_similar(smis, threshold=0.7)
    assert r["n_total"] == 4
    assert r["n_dropped"] == 1, r
    assert "c1ccccc1" in r["kept"]  # 先入者保留
    print("P6 0.7档 保留%d 剔除%d" % (r["n_kept"], r["n_dropped"]))


def test_three_gear_monotonic():
    # 含等价编码重复对 + 若干不同分子：三档下重复对均被剔除
    smis = ["c1ccccc1", "C1=CC=CC=C1", "CCO", "CCO",
            "CN1C=NC2=C1C(=O)N(C)C(=O)N2C", "CC(=O)Oc1ccccc1C(=O)O"]
    rows = decontamination.decontamination_report(smis, gears=(0.6, 0.7, 0.8))
    assert len(rows) == 3
    for row in rows:
        assert row["n_kept"] + row["n_dropped"] == row["n_total"]
        assert 0.0 <= row["drop_rate"] <= 1.0
        # 等价编码对 Tanimoto=1.0，在 0.6/0.7/0.8 三档均被剔除 → 剔除率不随档位上升而下降
        assert row["n_dropped"] == 2, row
    # 宽松档(0.6)剔除率 ≥ 严格档(0.8)（单调性）
    assert rows[0]["drop_rate"] >= rows[-1]["drop_rate"], rows
    print("P6 三档:", [(r["threshold"], r["n_kept"], r["n_dropped"], r["drop_rate"]) for r in rows])


if __name__ == "__main__":
    test_remove_similar_drops_equivalent_encodings()
    test_three_gear_monotonic()
    print("P6 去污染测试全部通过")
