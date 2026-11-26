# -*- coding: utf-8 -*-
"""模块O：失效模式的三层检测框架（把"案例记录"形式化为"带统计约束的检测器"）。

外部评审（2026-10-30）原话：
  "把 7 类失效模式组织成一个分层检测框架——第一层是'契约级'（unit_isomerism、
   silent_empty_source，在数据加载和 schema 校验时拦截），第二层是'裁决级'
   （pseudo_consensus、single_group_verdict，在计票前拦截），第三层是'架构级'
   （domain_block_unwired、version_drift，在 registry 和适配器层面拦截）。这个分层
   本身就是可发表的可靠性工程结构，与'准入先于组合'总纲一一对应：
   契约级准入 → 裁决级准入 → 架构级准入。"

本模块**不重新实现检测逻辑**，而是复用 `adt.failure_modes.detect()`，把命中按层归组，
并显式计算一个常被忽略的量：**在 curated 数据上的特异性约束**。
"干净数据 0 触发"不等于"0 误报"——如果检测器从未在干净数据上被挑战，其特异性没有被
估计。产物里必须写清这一点，否则等于把"未测"当"没有"。
"""

import csv
import io
import os

# 三层：契约 → 裁决 → 架构（顺序即"准入先于组合"的执行顺序）
LAYERS = {
    "contract": {
        "label": "契约级（数据加载/schema 校验时拦截）",
        "modes": ["unit_isomerism", "silent_empty_source"],
        "gate": "准入层第一关：口径与完整性",
    },
    "adjudication": {
        "label": "裁决级（计票前拦截）",
        "modes": ["pseudo_consensus", "single_group_verdict", "phys_range_violation"],
        "gate": "准入层第二关：独立性与物理有效性",
    },
    "architecture": {
        "label": "架构级（registry/适配器层拦截）",
        "modes": ["domain_block_unwired", "version_drift"],
        "gate": "准入层第三关：源资格与可追溯性",
    },
}

MODE_TO_LAYER = {}
for _layer, _spec in LAYERS.items():
    for _m in _spec["modes"]:
        MODE_TO_LAYER[_m] = _layer


def group(hits):
    """把 detect() 的命中分组到三层。返回 {layer: [hits]}。"""
    out = {k: [] for k in LAYERS}
    for h in hits or []:
        layer = MODE_TO_LAYER.get(h.get("mode"), "architecture")
        out[layer].append(h)
    return out


def summarize(hits, n_measurements=0, n_records=0, curated=False):
    """按层汇总触发数 / 触发率 / 覆盖的模式 / 特异性约束说明。"""
    grouped = group(hits)
    rows = []
    for layer, spec in LAYERS.items():
        hs = grouped[layer]
        modes_hit = sorted({h.get("mode") for h in hs})
        denom = n_measurements or 1
        rows.append(
            dict(
                layer=layer,
                label=spec["label"],
                gate=spec["gate"],
                n_hits=len(hs),
                trigger_rate=(
                    round(len(hs) / float(denom), 6) if n_measurements else None
                ),
                n_modes_hit=len(modes_hit),
                modes_hit=";".join(modes_hit),
                modes_defined=len(spec["modes"]),
            )
        )
    total = dict(
        n_hits=len(hits or []), n_measurements=n_measurements, n_records=n_records
    )
    # 特异性约束（诚实边界）
    if curated and not hits:
        spec_note = (
            "在 curated 数据上 0 触发：这**只**说明干净数据里没有可检测的违例，"
            "**不**等于检测器特异性已估计。特异性需要'已知干净 + 已知脏'的配对"
            "标签才能算；本产物只报告触发率，不伪造 FPR。"
        )
    elif curated:
        spec_note = (
            "在 curated 数据上仍有 %d 条触发：先判定是 curated 数据本身存在该问题"
            "（有价值的发现），还是检测器过敏（需收紧）。" % len(hits)
        )
    else:
        spec_note = (
            "非 curated 面板：触发率是'机制存在性 + 频率'的联合估计，"
            "不能直接当作真实 workflow 的失效频率（见工作包 J 的限定）。"
        )
    return dict(rows=rows, total=total, specificity_note=spec_note)


def write(outdir, hits, summary):
    os.makedirs(outdir, exist_ok=True)
    p1 = os.path.join(outdir, "failure_layers.csv")
    cols = [
        "layer",
        "label",
        "gate",
        "n_hits",
        "trigger_rate",
        "n_modes_hit",
        "modes_hit",
        "modes_defined",
    ]
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in summary["rows"]:
            w.writerow(r)
    p2 = os.path.join(outdir, "failure_layers_hits.csv")
    cols2 = ["layer", "mode", "compound_id", "endpoint", "source", "detail"]
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols2, extrasaction="ignore")
        w.writeheader()
        for h in hits or []:
            row = dict(h)
            row["layer"] = MODE_TO_LAYER.get(h.get("mode"), "architecture")
            w.writerow(row)
    p3 = os.path.join(outdir, "failure_layers_note.md")
    lines = [
        "# 失效模式三层检测（模块O）",
        "",
        "- 总命中: %(n_hits)d / 测量行 %(n_measurements)d / 裁决记录 %(n_records)d"
        % summary["total"],
        "",
        "| 层 | 定义模式数 | 命中模式数 | 命中数 | 触发率 |",
        "|---|---|---|---|---|",
    ]
    for r in summary["rows"]:
        lines.append(
            "| %s | %d | %d | %d | %s |"
            % (
                r["label"],
                r["modes_defined"],
                r["n_modes_hit"],
                r["n_hits"],
                r["trigger_rate"],
            )
        )
    lines += [
        "",
        "**特异性约束（必须随论文一起报告）**",
        "",
        summary["specificity_note"],
    ]
    with io.open(p3, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return p1, p2, p3
