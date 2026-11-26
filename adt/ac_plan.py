# -*- coding: utf-8 -*-
"""工作包 A/C 的执行清单生成器：**结构变体提交计划**。

### 它解决什么

工作包 C 要求："原样 / 去立体 / 互变体分别调**真实源**，看**预测值**位移，
再与源间分歧比较"。这一步必须真的去调源，无法靠算描述符替代。

本模块只负责把"要提交什么"变成可执行清单：
- 对每个分子用 `perturbation.variants()` 生成 `original / stereo_removed / tautomer`
  （以及可选的 desalted / neutralized / stereo_flipped）；
- 标出 no-op 变体（去立体后 SMILES 没变、互变体与母体相同）——**no-op 不应浪费提交配额**；
- 按 `--batch-size` 切批（ADMETlab3 限流严，小批 + 间隔重试）；
- 生成控制分子（先跑一批验证链路通不通，再花配额跑真分子）。

### 与 C 的关系

本模块**不产生结论**，只产生清单。结论由 `pred_displacement` 在拿回真实源预测后计算：
`结构扰动位移` vs `源间位移` 的比值——比值 >1 说明结构噪声带来的预测波动**大于**两个源之间
本来就存在的分歧，那么"Gate 0 标准化"就是必要的（这正是评审要 C 回答的问题）。
"""

import csv
import io
import os

from . import perturbation as PT

# 控制分子：先跑这一批确认链路（都是研究充分、来源明确的小分子）
CONTROLS = [
    ("CTRL_caffeine", "CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "BBB+ 经典小分子"),
    ("CTRL_atenolol", "CC(C)NCC(O)COc1ccc(cc1)CONC(N)=O", "BBB− 极性β阻滞剂"),
    ("CTRL_midazolam", "Clc1ccc2c(c1)C(=NCc1ncccn1)N2C", "CYP3A4 底物"),
    ("CTRL_warfarin", "CC(=O)CC(c1ccccc1)c1c(O)c2ccccc2oc1=O", "高蛋白结合/窄治疗窗"),
]

DEFAULT_KINDS = ("original", "stereo_removed", "tautomer")


def load_compounds(path):
    """读 compounds.csv（compound_id + calc_smiles/input_smiles）。"""
    out = []
    with io.open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            cid = (r.get("compound_id") or "").strip()
            smi = (
                r.get("calc_smiles") or r.get("input_smiles") or r.get("smiles") or ""
            ).strip()
            if cid and smi:
                out.append((cid, smi))
    return out


def build(compounds, kinds=DEFAULT_KINDS, include_controls=False):
    """生成提交清单行：compound_id, variant, smiles, note, noop。

    重要：`original` **永远不是 no-op**——它是 C 的基线，必须提交，
    否则拿回来的是"有变体、没基线"，位移无从计算。
    只有**非原始变体**在 SMILES 与母体相同时才算 no-op（可省配额）。
    """
    rows = []
    # 控制分子放最前：先跑这一批确认链路通
    if include_controls:
        for cid, smi, note in CONTROLS:
            rows.append(
                dict(
                    compound_id=cid,
                    variant="original",
                    smiles=smi,
                    note="控制分子：" + note,
                    noop="N",
                )
            )
    for cid, smi in list(compounds):
        vs = PT.variants(smi)
        if "_error" in vs:
            rows.append(
                dict(
                    compound_id=cid,
                    variant="error",
                    smiles="",
                    note=vs["_error"][1],
                    noop="Y",
                )
            )
            continue
        base = vs.get("original", ("", ""))[0]
        for kind in kinds:
            s, note = vs.get(kind, ("", "未生成"))
            if not s:
                continue
            if kind == "original":
                noop = "N"  # 基线必须提交
            else:
                noop = "Y" if s == base else "N"
            rows.append(
                dict(compound_id=cid, variant=kind, smiles=s, note=note, noop=noop)
            )
    return rows


def to_batches(rows, size=5, skip_noop=True):
    """切批（默认跳过 no-op，省配额）。返回 [ [row,...], ... ]。"""
    use = [r for r in rows if not (skip_noop and r.get("noop") == "Y")]
    return [use[i : i + size] for i in range(0, len(use), size)]


def write(outdir, rows, batches, meta=None):
    os.makedirs(outdir, exist_ok=True)
    p1 = os.path.join(outdir, "ac_variants.csv")
    cols = ["compound_id", "variant", "smiles", "note", "noop"]
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    p2 = os.path.join(outdir, "ac_batches.csv")
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["batch", "slot", "compound_id", "variant", "smiles"],
            extrasaction="ignore",
        )
        w.writeheader()
        for bi, b in enumerate(batches, 1):
            for si, r in enumerate(b, 1):
                row = dict(r)
                row["batch"] = bi
                row["slot"] = si
                w.writerow(row)
    # 纯 SMILES 列表（每个 batch 一个文件，方便直接粘贴到网页批量框）
    bdir = os.path.join(outdir, "batches")
    os.makedirs(bdir, exist_ok=True)
    for bi, b in enumerate(batches, 1):
        with io.open(
            os.path.join(bdir, "batch_%02d.txt" % bi),
            "w",
            encoding="utf-8",
            newline="\n",
        ) as fh:
            fh.write("\n".join(r["smiles"] for r in b) + "\n")
    p3 = os.path.join(outdir, "ac_plan.md")
    n_noop = sum(1 for r in rows if r.get("noop") == "Y")
    L = ["# A/C 结构变体提交计划", ""]
    for k, v in (meta or {}).items():
        L.append("- %s: %s" % (k, v))
    L += [
        "",
        "- 清单行数: **%d**（其中 no-op %d 行，默认不提交）" % (len(rows), n_noop),
        "- 批次数: **%d**（每批 ≤%d）"
        % (len(batches), len(batches[0]) if batches else 0),
        "",
        "## 变体含义",
        "",
        "| 变体 | 含义 | 为什么对 C 有用 |",
        "|---|---|---|",
        "| `original` | 定稿结构（已标准化） | 基线预测 |",
        '| `stereo_removed` | 去掉全部手性/E-Z | 检验"立体信息丢失是否改变源预测" |',
        '| `tautomer` | RDKit 规范互变体 | 检验"互变异构态是否改变源预测" |',
        "",
        "## 怎么跑（ADMETlab3）",
        "",
        "1. 打开 https://admetlab3.scbdd.com/server/ ，选 **Batch** 模式；",
        "2. 先跑 `batches/batch_01.txt`（控制分子，4 个）**确认链路通**；",
        "3. 再逐批粘贴 `batch_02.txt` … `batch_NN.txt`（每批 5 个，批间休息 ≥30 s）；",
        "4. 每批导出 CSV，命名 `admetlab_batch02.csv` 等，放回同一目录；",
        "5. 回来后执行：",
        "",
        "```bash",
        "$PY -m adt.cli pred-shift --canonical <定稿预测宽表> \\",
        "    --variants <变体预测宽表> --source-shift <source_rho 产物> --outdir out",
        "```",
        "",
        "> 注意：ADMETlab3 的批量输出列名与单分子可能不同；若列名不一致，",
        "> 先用 `--endpoints` 显式指定要比较的端点。",
    ]
    with io.open(p3, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    return p1, p2, p3
