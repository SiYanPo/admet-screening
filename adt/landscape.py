# -*- coding: utf-8 -*-
"""工作包 K：可靠性方法的生态位（分工表）的机器可读输出。

评审原话："在论文中主动划定本框架不解决的问题——与其他可靠性策略的分工表。
这个表本身就是对审稿人'你和 X 有什么区别'的预先封堵。"

K 不是计算模块，而是**写作/定位交付**；本模块把 `references/reliability_landscape.yaml`
渲染成 CSV/Markdown，保证论文里的表与 skill 的立场始终一致（避免手改漂移）。
"""

import csv
import io
import os


def load(path):
    import yaml

    with io.open(path, encoding="utf-8") as fh:
        d = yaml.safe_load(fh) or {}
    return d.get("thesis", ""), list(d.get("rows") or [])


def markdown(thesis, rows):
    lines = [
        "intro: %s" % thesis,
        "",
        "| 策略 | 它解决什么 | 它不解决什么 | 与本框架的关系 |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            "| %s | %s | %s | %s |"
            % (
                r.get("strategy", ""),
                r.get("solves", ""),
                r.get("does_not_solve", ""),
                r.get("relation", ""),
            )
        )
    return "\n".join(lines) + "\n"


def write(outdir, thesis, rows):
    os.makedirs(outdir, exist_ok=True)
    p1 = os.path.join(outdir, "reliability_landscape.csv")
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["strategy", "solves", "does_not_solve", "relation"]
        )
        w.writeheader()
        w.writerows(rows)
    p2 = os.path.join(outdir, "reliability_landscape.md")
    with io.open(p2, "w", encoding="utf-8") as fh:
        fh.write(markdown(thesis, rows))
    return p1, p2
