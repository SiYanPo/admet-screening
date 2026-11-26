# -*- coding: utf-8 -*-
"""Ames 双方法层：release_error_rate 差值的**配对 bootstrap** CI（P2.4 / 解 D3）。

## 为什么需要这个脚本

材料里写"放行错误率 0.2685 → 0.177，降 9.2 个百分点"（`references/POSITIONING.md` §4b），
但**没有区间**。审稿人的第一个问题必然是"这个 9.2pp 的 95% CI 是多少、含不含 0"。
本脚本把这件事算完，并把结果落成可被 G10 校验的产物。

## 数据来源与重建假设（必须明示）

`out_ext/tdc/ames_alerts.json` 只有两臂的**聚合计数**，没有逐分子记录：
  - 统计模型单独：放行 581，其中真致突变 156 → 0.2685
  - 统计 + 专家规则：放行 226，其中真致突变 40 → 0.177
两法放行集是**嵌套**的（加规则只会让更多分子不放行），因此可重建四格：

| 细胞 | 含义 | 计数 |
|---|---|---|
| A | 两法都放行 & 真致突变 | 40 |
| B | 两法都放行 & 非突变 | 226 − 40 = 186 |
| C | 仅统计法放行 & 真致突变 | 156 − 40 = 116 |
| D | 仅统计法放行 & 非突变 | (581 − 226) − 116 = 239 |

**假设**：嵌套性成立（由 ICH M7 规则层语义保证：规则层只能把 PASS 降级，不能升级）。
若该假设不成立，四格重建无效——脚本会把该假设写进产物 `assumption` 字段。

运行：python run_ames_release_ci.py
产物：out_ext/tdc/ames_release_ci.json
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adt.stats_ci import (newcombe_diff_ci, paired_bootstrap_diff_ci,
                          wilson_ci)

SRC = "out_ext/tdc/ames_alerts.json"
OUT = "out_ext/tdc/ames_release_ci.json"


def main():
    d = json.load(io.open(SRC, encoding="utf-8"))
    two = d["two_method_ich_m7"]
    one = d["stat_only_counterfactual"]

    n_two = int(two["n_pass_class5_direction"])
    k_two = int(two["released_mutagens"])
    n_one = int(one["n_pass"])
    k_one = int(one["released_mutagens"])

    cells = [
        (k_two, dict(stat=1, two=1, mut=1)),              # A
        (n_two - k_two, dict(stat=1, two=1, mut=0)),      # B
        (k_one - k_two, dict(stat=1, two=0, mut=1)),      # C
        ((n_one - n_two) - (k_one - k_two), dict(stat=1, two=0, mut=0)),  # D
    ]

    def _diff(counts_payloads):
        a = b = c = e = 0
        for cnt, p in counts_payloads:
            if p["two"] == 1 and p["mut"] == 1:
                a += cnt
            elif p["two"] == 1 and p["mut"] == 0:
                b += cnt
            elif p["two"] == 0 and p["mut"] == 1:
                c += cnt
            else:
                e += cnt
        r_one = (a + c) / (a + b + c + e)
        r_two = a / (a + b)
        return r_one - r_two

    boot = paired_bootstrap_diff_ci(cells, _diff, n_boot=10000)
    newc = newcombe_diff_ci(k_one, n_one, k_two, n_two)

    res = dict(
        endpoint="ames",
        source_artifact=SRC,
        n_total=int(d["n_test"]),
        arms=dict(
            stat_only=dict(n_released=n_one, released_mutagens=k_one,
                           rate=round(k_one / n_one, 4),
                           wilson95=[round(wilson_ci(k_one, n_one)["lo"], 4),
                                     round(wilson_ci(k_one, n_one)["hi"], 4)]),
            two_method=dict(n_released=n_two, released_mutagens=k_two,
                            rate=round(k_two / n_two, 4),
                            wilson95=[round(wilson_ci(k_two, n_two)["lo"], 4),
                                      round(wilson_ci(k_two, n_two)["hi"], 4)]),
        ),
        cells=dict(A_both_mut=k_two, B_both_nonmut=n_two - k_two,
                   C_stat_only_mut=k_one - k_two,
                   D_stat_only_nonmut=(n_one - n_two) - (k_one - k_two)),
        diff_paired_bootstrap=dict(
            diff=round(boot["diff"], 4) if boot.get("diff") is not None else None,
            ci95=[round(boot["lo"], 4), round(boot["hi"], 4)]
            if boot.get("lo") is not None else None,
            n_boot=boot.get("n_boot"), method=boot.get("method"),
            excludes_zero=(boot.get("lo") is not None and
                           (boot["lo"] > 0 or boot["hi"] < 0))),
        diff_newcombe_independent=dict(
            diff=round(newc["diff"], 4) if newc.get("diff") is not None else None,
            ci95=[round(newc["lo"], 4), round(newc["hi"], 4)]
            if newc.get("lo") is not None else None,
            method=newc.get("method"),
            note="忽略配对相关性的保守近似；与配对 bootstrap 并列给出，二者不应差别过大"),
        assumption=("两法放行集嵌套（专家规则层只能把 PASS 降级、不能升级）。"
                    "四格由聚合计数重建，非逐分子记录；若该假设失效则本 CI 无效。"),
        interpretation=("若配对 CI 不含 0，则『放行错误率下降』可写为带区间的陈述；"
                        "若含 0，则只能写『点估计更低，但未达可检测差异』——"
                        "按红线 6，后者不得用『略优/显著优于』等无区间比较词。"),
    )
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, "w", encoding="utf-8").write(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n")
    print("[ames-ci] 统计模型 %.4f [%.3f, %.3f] / 双方法 %.4f [%.3f, %.3f]"
          % (res["arms"]["stat_only"]["rate"], *res["arms"]["stat_only"]["wilson95"],
             res["arms"]["two_method"]["rate"], *res["arms"]["two_method"]["wilson95"]))
    print("[ames-ci] 差值 %.4f，配对 bootstrap 95%%CI [%.4f, %.4f]，不含 0 = %s"
          % (res["diff_paired_bootstrap"]["diff"],
             *res["diff_paired_bootstrap"]["ci95"],
             res["diff_paired_bootstrap"]["excludes_zero"]))
    print("[ames-ci] 交叉核对（Newcombe 独立近似）：%.4f [%.4f, %.4f]"
          % (res["diff_newcombe_independent"]["diff"],
             *res["diff_newcombe_independent"]["ci95"]))
    print("[ames-ci] -> %s" % OUT)


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print("用法：%s（无参数；读 %s 写 %s）" % (__file__, SRC, OUT))
        raise SystemExit(0)
    main()
