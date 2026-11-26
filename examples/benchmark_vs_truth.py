# -*- coding: utf-8 -*-
"""E1/E2 基准框架：把"框架裁决"与"金标准"和"朴素基线"放在同一张表上比。

为什么需要它：评估报告指出——没有金标准，一切"裁决正确性"都是自述；
而审稿人一定会问"比多数投票好在哪"。本脚本把这两件事做成可执行的对照实验：

输入：
  --reliability  reliability.csv（本框架输出）
  --measurements measurements 长表（用于朴素基线）
  --truth        truth.csv，列：compound_id, endpoint, truth_value[, truth_class]
                 truth_class 可留空（此时用 rules 阈值把真值判成 PASS/FAIL）
  --rules        03_endpoint_rules.yaml

输出：
  benchmark.csv   逐条：(cid, ep, truth, framework_verdict, baseline_verdict, agree_*)
  控制台           两套方法的 准确率 / 混淆矩阵 / 只在框架下才判对的数量

**基线定义（naive mean-vote）**：同端点域内预测值取算术平均（不分组、不弃权、
不看饱和），再套同一套阈值——这正是本 skill 反对的做法，用作对照。

注意：truth.csv 里的真值必须是**实测**（domain_flag=measured 语义）。
本脚本不负责造真值；没有湿实验/文献实测数据时，跑出来的只是流程自检。
"""
import argparse
import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt.reliability import _judge, _match_rule, _median   # noqa: E402
from adt import schema                                      # noqa: E402


def _load_rules(path):
    import yaml
    d = yaml.safe_load(io.open(path, encoding="utf-8")) or {}
    return {e["id"]: e for e in d.get("endpoints", [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reliability", required=True)
    ap.add_argument("--measurements", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--rules", default="references/03_endpoint_rules.yaml")
    ap.add_argument("--out", default="benchmark.csv")
    a = ap.parse_args()

    rules = _load_rules(a.rules)
    rel = {(r["compound_id"], r["endpoint"]): r
           for r in csv.DictReader(io.open(a.reliability, encoding="utf-8-sig"))}
    meas = list(csv.DictReader(io.open(a.measurements, encoding="utf-8-sig")))
    truth = list(csv.DictReader(io.open(a.truth, encoding="utf-8-sig")))

    # 朴素基线：同端点域内预测值取算术平均（不分组、不弃权）
    agg = {}
    for m in meas:
        if m.get("domain_flag") not in ("predicted", "measured", "manual"):
            continue
        try:
            v = float(m.get("value"))
        except (TypeError, ValueError):
            continue
        agg.setdefault((m["compound_id"], m["endpoint"]), []).append(v)

    rows = []
    for t in truth:
        cid, ep = t["compound_id"], t["endpoint"]
        try:
            tv = float(t["truth_value"])
        except (TypeError, ValueError):
            continue
        rule = _match_rule(ep, rules)
        tclass = (t.get("truth_class") or "").strip().upper()
        truth_verdict = tclass if tclass in ("PASS", "FAIL") else (_judge(tv, rule) or "")

        fw = (rel.get((cid, ep)) or {}).get("verdict", "")
        vals = agg.get((cid, ep), [])
        base_verdict = _judge(sum(vals) / len(vals), rule) if vals else ""

        rows.append(dict(compound_id=cid, endpoint=ep, truth_value=tv,
                         truth_verdict=truth_verdict,
                         framework_verdict=fw, baseline_verdict=base_verdict,
                         framework_agree=("Y" if fw == truth_verdict else "N"),
                         baseline_agree=("Y" if base_verdict == truth_verdict else "N")))

    cols = ["compound_id", "endpoint", "truth_value", "truth_verdict",
            "framework_verdict", "baseline_verdict",
            "framework_agree", "baseline_agree"]
    with io.open(a.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    def score(key):
        y = sum(1 for r in rows if r[key] == "Y")
        return y, len(rows), (y / len(rows) if rows else 0.0)

    fy, n, fr = score("framework_agree")
    by, _, br = score("baseline_agree")
    only_fw = sum(1 for r in rows if r["framework_agree"] == "Y"
                  and r["baseline_agree"] != "Y")
    print("[benchmark] %d 条真值对照 -> %s" % (len(rows), a.out))
    print("[benchmark] 框架一致率 %d/%d = %.2f" % (fy, n, fr))
    print("[benchmark] 基线（均值投票）一致率 %d/%d = %.2f" % (by, n, br))
    print("[benchmark] 仅框架判对 %d 条，仅基线判对 %d 条"
          % (only_fw, by - (fy - only_fw)))
    if n < 30:
        print("[benchmark] ⚠ 对照条数 %d < 30：只能作流程自检，**不足以支撑统计结论**" % n)


if __name__ == "__main__":
    main()
