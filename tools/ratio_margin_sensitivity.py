# -*- coding: utf-8 -*-
"""ratio_margin（TOST 等效界）敏感性：由**已存的 bootstrap CI 直接重算判定**，不重训模型。

为什么这样做是正确且廉价的：
  `adt.mmp.analyze_regression()` 的判定只依赖三件事——R 的 95%CI 上下界、
  ratio_margin（界=1±margin）、以及符号一致率（insensitive 是否降级为 compressed）。
  这三样都已落在 `out_ext/tdc/p8_mmp_reg_*.json` 里。因此"换 margin 后结论会不会翻"
  是**纯代数**问题，重跑 RF/Ridge（每次 6+ 分钟）只会引入随机种子噪声，不增加信息。

判据与 `adt.mmp` 严格同源（此处逐条复刻，并在 selftest 里对照真值）：
  · hi < 1-m            → insensitive（若 sign_z>=3 再降级为 compressed）
  · lo > 1+m            → oversensitive
  · lo > 1-m 且 hi < 1+m → equivalent
  · 其余                → inconclusive

输出：out_sensitivity/ratio_margin_sensitivity.json
运行：python tools/ratio_margin_sensitivity.py
"""

from __future__ import annotations

import glob
import io
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out_sensitivity", "ratio_margin_sensitivity.json")
MARGINS = [0.3, 0.4, 0.5, 0.6, 0.7]
SIGN_Z_FLOOR = 3.0


def verdict(lo, hi, margin, sign_z=None):
    lo_ok, hi_ok = 1.0 - margin, 1.0 + margin
    if hi < lo_ok:
        v = "NOT_equivalent:insensitive"
        if sign_z is not None and sign_z >= SIGN_Z_FLOOR:
            v = "NOT_equivalent:compressed"
    elif lo > hi_ok:
        v = "NOT_equivalent:oversensitive"
    elif lo > lo_ok and hi < hi_ok:
        v = "equivalent"
    else:
        v = "inconclusive"
    return v


def sign_z(p, n):
    if not n:
        return None
    return (p * n - 0.5 * n) / (0.5 * math.sqrt(n))


def load_files():
    """优先读 m050.bak（margin=0.5 的历史产物，避免被重跑覆盖），否则读现文件。"""
    files = {}
    for p in glob.glob(
        os.path.join(ROOT, "out_ext", "tdc", "p8_mmp_reg_*.json.m050.bak")
    ) + glob.glob(os.path.join(ROOT, "out_ext", "tdc", "p8_mmp_reg_*.json")):
        base = os.path.basename(p).replace(".m050.bak", "")
        if base in files:
            continue
        files[base] = p
    return files


def main():
    rows = []
    files = load_files()
    for base, path in sorted(files.items()):
        d = json.load(io.open(path, encoding="utf-8"))
        ep = d.get("endpoint")
        for model, r in (d.get("results") or {}).items():
            ov = (r or {}).get("overall") or {}
            ci = ov.get("ratio_ci95")
            if not ci:
                continue
            p, n = r.get("sign_agreement"), r.get("sign_agreement_n")
            z = sign_z(p, n) if (p is not None and n) else None
            per = {}
            for m in MARGINS:
                per[str(m)] = verdict(ci[0], ci[1], m, z)
            uniq = set(per.values())
            rows.append(
                dict(
                    endpoint=ep,
                    model=model,
                    n_pairs=ov.get("n_pairs") or r.get("n_pairs"),
                    R=ov.get("displacement_ratio"),
                    ci95=ci,
                    sign_agreement=p,
                    sign_z=(round(z, 2) if z is not None else None),
                    verdict_by_margin=per,
                    flips=len(uniq) > 1,
                    n_distinct=len(uniq),
                )
            )

    out = dict(
        schema="adt-ratio-margin-sensitivity/1.0",
        method="判定由已存 bootstrap CI 代数重算（不重训模型）；判据与 adt.mmp.analyze_regression 同源",
        margins=MARGINS,
        bounds="equivalent iff CI ⊂ (1-m, 1+m)",
        n_cells=len(rows),
        n_flip=sum(1 for r in rows if r["flips"]),
        rows=rows,
    )
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(
        json.dumps(out, ensure_ascii=False, indent=1)
    )

    print(
        "%-32s %-10s %-22s %-10s %s"
        % ("endpoint", "model", "CI95", "R", "verdict by margin")
    )
    for r in rows:
        vs = " | ".join(
            "%s:%s" % (m, r["verdict_by_margin"][m].replace("NOT_equivalent:", "!"))
            for m in ("0.3", "0.4", "0.5", "0.6", "0.7")
        )
        print(
            "%-32s %-10s [%.3f,%.3f] %-10.3f %s"
            % (
                (r["endpoint"] or "?")[:32],
                r["model"][:10],
                r["ci95"][0],
                r["ci95"][1],
                r["R"] or float("nan"),
                vs,
            )
        )
    print("\n[cells] %d  [flip] %d  -> %s" % (len(rows), out["n_flip"], OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
