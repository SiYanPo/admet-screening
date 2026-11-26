# -*- coding: utf-8 -*-
"""阈值冻结审计（A8 / G12）：每个决定结论的阈值，来历、冻结状态、敏感性是否齐备。

## 审计三件事
1. **漂移检查**：`value_token` 必须逐字出现在 `where` 的每个文件里。
   这一步防的是"文档写 0.65、代码改成 0.60"——这种失配在人工 review 里几乎必漏，
   而它会让整套结论的语义悄悄改变。
2. **来历普查**：literature / calibrated / ad_hoc 各多少（U9 的 22 阈值普查就此可填）。
3. **敏感性缺口**：`provenance: ad_hoc` 且 `sensitivity` 为空 → 记 gap。
   ad_hoc 不是罪，**没有敏感性分析的 ad_hoc 才是**。

## 为什么这一项被评审重新置顶
框架里最容易发生"事后合理化"的地方不是结论，而是阈值：
只要允许在看到结果后把 0.65 改成 0.60，所有负结果都能被翻案。
post-cutoff 外源实验已经暴露过一次同类问题（阈值与口径是见数据后定的），
所以内部判据必须反过来做：**先冻结、再报数**。

## 用法
```bash
python -m adt.threshold_audit
python -m adt.threshold_audit --json out_ext/threshold_freeze_audit.json
```
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YAML_PATH = os.path.join(ROOT, "references", "THRESHOLD_REGISTRY.yaml")
CLASSES = ("literature", "calibrated", "ad_hoc")


def audit(path=None):
    import yaml

    p = path or YAML_PATH
    if not os.path.exists(p):
        return {
            "registry": p,
            "exists": False,
            "passed": False,
            "drift": [],
            "gaps": [{"why": "登记表不存在"}],
        }
    doc = yaml.safe_load(io.open(p, encoding="utf-8")) or {}
    items = doc.get("thresholds") or []

    drift, gaps, rows = [], [], []
    census = {c: 0 for c in CLASSES}
    n_frozen = 0
    for it in items:
        tid = it.get("id")
        tok = str(it.get("value_token"))
        where = it.get("where") or []
        cls = it.get("provenance")
        census[cls] = census.get(cls, 0) + 1
        frozen = bool(it.get("frozen"))
        n_frozen += 1 if frozen else 0
        missing_files, token_missing = [], []
        for w in where:
            wp = os.path.join(ROOT, w) if not os.path.isabs(w) else w
            if not os.path.exists(wp):
                missing_files.append(w)
                continue
            txt = io.open(wp, encoding="utf-8", errors="replace").read()
            if tok not in txt:
                token_missing.append(w)
        if missing_files or token_missing:
            drift.append(
                {
                    "id": tid,
                    "value_token": tok,
                    "missing_files": missing_files,
                    "token_not_found_in": token_missing,
                    "why": "登记值与代码字面量失配（阈值漂移）",
                }
            )
        if cls == "ad_hoc" and not (it.get("sensitivity") or "").strip():
            gaps.append(
                {
                    "id": tid,
                    "kind": "ad_hoc_without_sensitivity",
                    "why": "ad_hoc 阈值缺敏感性分析",
                }
            )
        if not frozen:
            gaps.append(
                {
                    "id": tid,
                    "kind": "not_frozen",
                    "why": "阈值未冻结（frozen=false）",
                    "note": it.get("note", "")[:120],
                }
            )
        if cls == "literature" and not (it.get("note") or "").strip():
            gaps.append(
                {
                    "id": tid,
                    "kind": "literature_without_citation",
                    "why": "标 literature 但未写引文",
                }
            )
        rows.append(
            {
                "id": tid,
                "name": it.get("name"),
                "value": it.get("value"),
                "provenance": cls,
                "frozen": frozen,
                "sensitivity": it.get("sensitivity"),
                "where": where,
            }
        )

    n_sens = sum(1 for it in items if (it.get("sensitivity") or "").strip())
    return {
        "registry": os.path.relpath(p, ROOT).replace("\\", "/"),
        "exists": True,
        "rule": (doc.get("meta") or {}).get("rule", ""),
        "n_thresholds": len(items),
        "n_frozen": n_frozen,
        "n_with_sensitivity": n_sens,
        "census": census,
        "drift": drift,
        "gaps": gaps,
        "rows": rows,
        # 漂移是阻断项；敏感性缺口是告警项（ad_hoc 允许存在，但必须被看见）
        "passed": len(drift) == 0,
        "warn": len([g for g in gaps if g["kind"] != "literature_without_citation"])
        > 0,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    a = ap.parse_args(argv)
    res = audit(a.registry)
    if a.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(a.json_out)), exist_ok=True)
        with io.open(a.json_out, "w", encoding="utf-8") as f:
            f.write(json.dumps(res, ensure_ascii=False, indent=2))
    print(
        "[thr] 阈值 %d 条：冻结 %d，带敏感性 %d；来历 %s"
        % (
            res["n_thresholds"],
            res["n_frozen"],
            res["n_with_sensitivity"],
            res["census"],
        )
    )
    for d in res["drift"]:
        print(
            "  ✗ 漂移 %-28s token=%r 未见于 %s"
            % (d["id"], d["value_token"], d["token_not_found_in"] or d["missing_files"])
        )
    for g in res["gaps"]:
        print("  ! %-10s %-28s %s" % (g["kind"], g["id"], g["why"]))
    print("[thr] passed=%s (漂移为阻断项；未冻结/缺口为告警项)" % res["passed"])
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
