# -*- coding: utf-8 -*-
"""SAR 预筛轴：结构-通透性瓶颈诊断（深水区建议 2.1）。

核心命题（报告 2.1）：肉桂酰糖苷类的 BBB 穿透瓶颈是**糖苷极性负荷**，而非肉桂酰基的
亲脂性。框架此前只依赖外部源的 BBB 二元预测，没有把这一结构决定因素形式化为可裁决的
SAR 命题。本模块在 normalize 之后、web 之前作为一个**独立的 SAR pre-screen** 步骤运行：
对每个分子计算 TPSA / MW / HBD / HBA / XlogP，与一个 BBB+ / BBB− 参照集比较，输出
"结构-通透性瓶颈"诊断。

设计纪律：
  - 这是**结构预筛**（role=reference），不是外部源预测；产出清晰标注为"被动渗透预筛"，
    不进质量裁决、不当数值投票。
  - 参照集 SMILES 硬编码、描述符运行时用 RDKit 计算（真实值，非编造）；BBB 标签来自
    文献/综述级共识（每条含 src）。报告点名的 GCG 与 10-O-trans-p-methoxycinnamoylcatalpol
    以"文献报道描述符"形式纳入（src 标注，不参与 NN 距离计算，只用于包络对照）。
  - 瓶颈诊断用透明的文献包络规则（Pajouhesh & Lenz 2005 的 BBB 透入结构约束：
    TPSA ≤ 90 Å²、MW ≤ 450、HBD ≤ 3、HBA ≤ 8、−2 < LogP < 5），逐条列出被违反的约束。
"""

import os

from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors

RDLogger.DisableLog("rdApp.*")


# BBB+ / BBB− 参照集（SMILES 硬编码；描述符运行时计算）。标签为文献级共识。
# src 给出来源类别，便于评审核对。
REFERENCES = [
    # ---- BBB+（已知中枢穿透）----
    dict(
        name="caffeine",
        bbb="+",
        smiles="CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
        src="BBB+ 经典中枢兴奋剂（小分子、低极性）",
    ),
    dict(
        name="theophylline",
        bbb="+",
        smiles="Cn1c(C)nc2c1c(=O)[nH]c(=O)n2C",
        src="BBB+ 黄嘌呤类（临床入脑）",
    ),
    dict(
        name="nicotine",
        bbb="+",
        smiles="CN1CCCC1c1cccnc1",
        src="BBB+ 烟碱（小分子、亲脂）",
    ),
    dict(
        name="antipyrine",
        bbb="+",
        smiles="CC1=CC(=O)N(C2C1C(=O)N(N2C)C)C",
        src="BBB+ 经典脑渗透探针",
    ),
    dict(
        name="diphenhydramine",
        bbb="+",
        smiles="CN(C)CCOC(c1ccccc1)c1ccccc1",
        src="BBB+ 抗组胺（入脑致嗜睡）",
    ),
    # ---- BBB−（已知中枢不穿透）----
    dict(
        name="atenolol",
        bbb="-",
        smiles="CC(C)NCC(O)COc1ccc(cc1)CONC(N)=O",
        src="BBB− 经典极性β阻滞剂（HBD=3, TPSA≈85）",
    ),
    dict(
        name="ranitidine",
        bbb="-",
        smiles="Cc1nc(N)nc(NC(C=NCCSCN)C)cs1",
        src="BBB− 组胺 H2 拮抗剂（极性）",
    ),
    dict(
        name="cimetidine",
        bbb="-",
        smiles="Cc1nc(N)nc(NC(CSCN)CN(C)C)cs1",
        src="BBB− H2 拮抗剂（极性）",
    ),
    dict(
        name="glucose",
        bbb="-",
        smiles="OCC1OC(O)C(O)C(O)C1O",
        src="BBB− 单糖（无转运体介导不跨 BBB）",
    ),
    dict(
        name="sucrose",
        bbb="-",
        smiles="O=C1OC(CO)C(O)C(O)C1OCC1OC(O)C(O)C(O)C(O)C1O",
        src="BBB− 二糖",
    ),
]

# 报告点名的结构高度相似参照（描述符取自检索文献，运行时不再由 RDKit 计算；
# 仅用于包络/量级对照，不参与最近邻距离匹配）。
LIT_BENCHMARKS = [
    dict(
        name="GCG(1-O-galloyl-6-O-cinnamoylglucose)",
        bbb="-",
        MW=462.4,
        TPSA=183.2,
        HBD=None,
        HBA=None,
        XlogP=None,
        src="DeepSeek 检索：高 TPSA + MW>400 → BBB 穿透低",
    ),
    dict(
        name="10-O-trans-p-methoxycinnamoylcatalpol",
        bbb="-",
        MW=522.5,
        TPSA=177.0,
        HBD=None,
        HBA=None,
        XlogP=-0.60,
        src="admetSAR 2：BBB 穿透阴性（86.7% 概率）+ Caco-2 阴性",
    ),
]

# BBB 透入结构包络（Pajouhesh & Lenz 2005；CNS-MPO 类约束的宽松版）
ENVELOPE = dict(
    TPSA_max=90.0, MW_max=450.0, HBD_max=3, HBA_max=8, logP_lo=-2.0, logP_hi=5.0
)


def compute_descriptors(smiles):
    """返回 dict(TPSA, MW, HBD, HBA, XlogP)。解析失败返回全 None。"""
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return dict(TPSA=None, MW=None, HBD=None, HBA=None, XlogP=None)
    return dict(
        TPSA=round(float(Descriptors.TPSA(mol)), 1),
        MW=round(float(Descriptors.MolWt(mol)), 1),
        HBD=int(Descriptors.NumHDonors(mol)),
        HBA=int(Descriptors.NumHAcceptors(mol)),
        XlogP=round(float(Descriptors.MolLogP(mol)), 2),
    )


def _ref_descriptors():
    """计算参照集描述符（缓存）。"""
    cache = []
    for r in REFERENCES:
        d = compute_descriptors(r["smiles"])
        d.update(name=r["name"], bbb=r["bbb"], src=r["src"])
        cache.append(d)
    return cache


def _nearest(query, refs):
    """在参照集里找最近邻（对 5 个描述符做 min-max 归一化后的欧氏距离）。"""
    keys = ["TPSA", "MW", "HBD", "HBA", "XlogP"]
    lo = {k: min(r[k] for r in refs) for k in keys}
    hi = {k: max(r[k] for r in refs) for k in keys}

    def norm(d):
        return [
            0.0 if hi[k] == lo[k] else (d[k] - lo[k]) / (hi[k] - lo[k]) for k in keys
        ]

    qn = norm(query)
    best, best_d = None, 1e9
    for r in refs:
        rn = norm(r)
        dd = sum((a - b) ** 2 for a, b in zip(qn, rn)) ** 0.5
        if dd < best_d:
            best_d, best = dd, r
    return best, round(best_d, 3)


def _bottlenecks(d):
    """逐条列违反的 BBB 包络约束，按严重度排序。"""
    hits = []
    if d["TPSA"] is not None and d["TPSA"] > ENVELOPE["TPSA_max"]:
        over = d["TPSA"] - ENVELOPE["TPSA_max"]
        hits.append(
            (
                "TPSA",
                "%.1f > %.0f Å²（超出 %.0f）" % (d["TPSA"], ENVELOPE["TPSA_max"], over),
                over / ENVELOPE["TPSA_max"],
            )
        )
    if d["MW"] is not None and d["MW"] > ENVELOPE["MW_max"]:
        over = d["MW"] - ENVELOPE["MW_max"]
        hits.append(
            (
                "MW",
                "%.1f > %.0f（超出 %.0f）" % (d["MW"], ENVELOPE["MW_max"], over),
                over / ENVELOPE["MW_max"],
            )
        )
    if d["HBD"] is not None and d["HBD"] > ENVELOPE["HBD_max"]:
        hits.append(
            (
                "HBD",
                "%d > %d" % (d["HBD"], ENVELOPE["HBD_max"]),
                (d["HBD"] - ENVELOPE["HBD_max"]),
            )
        )
    if d["HBA"] is not None and d["HBA"] > ENVELOPE["HBA_max"]:
        hits.append(
            (
                "HBA",
                "%d > %d" % (d["HBA"], ENVELOPE["HBA_max"]),
                (d["HBA"] - ENVELOPE["HBA_max"]),
            )
        )
    if d["XlogP"] is not None and not (
        ENVELOPE["logP_lo"] < d["XlogP"] < ENVELOPE["logP_hi"]
    ):
        hits.append(
            (
                "XlogP",
                "%.2f 越界(%.1f,%.1f)"
                % (d["XlogP"], ENVELOPE["logP_lo"], ENVELOPE["logP_hi"]),
                abs(d["XlogP"])
                / max(abs(ENVELOPE["logP_lo"]), abs(ENVELOPE["logP_hi"])),
            )
        )
    hits.sort(key=lambda x: -x[2])
    return [h[0:2] for h in hits]


def diagnose(smiles, name=""):
    """返回完整诊断 dict。"""
    d = compute_descriptors(smiles)
    if d["TPSA"] is None:
        # SMILES 解析失败：无法做结构预筛，明确标 uncertain 且不参与最近邻匹配
        return dict(
            name=name,
            smiles=smiles,
            TPSA=None,
            MW=None,
            HBD=None,
            HBA=None,
            XlogP=None,
            nearest_ref="",
            nearest_label="",
            nearest_distance=None,
            bottleneck=["descriptor_compute_failed"],
            passive_permeability_screen="uncertain",
            bbb_determinant_layer="undetermined → manual_check_required",
            summary="被动渗透预筛：描述符计算失败（SMILES 无效），无法评估；需人工核对结构",
            references_used=[
                r["name"] + "(BBB%s)" % r["bbb"] for r in _ref_descriptors()
            ],
            lit_benchmarks=[b["name"] for b in LIT_BENCHMARKS],
        )
    refs = _ref_descriptors()
    near, dist = _nearest(d, refs)
    bn = _bottlenecks(d)
    if not bn:
        screen = "plausible"
        screen_zh = "被动渗透预筛：在 BBB 包络内， plausible 入脑（仍需 P-gp 双层核查）"
        determinant = "passive_open → passive_permeability_decisive"
    else:
        # 瓶颈越严重、违反项越多 → 越 unlikely
        n_viol = len(bn)
        worst = bn[0][0]
        if worst == "TPSA" and (d["TPSA"] or 0) > 140:
            screen = "unlikely"
            screen_zh = "被动渗透预筛：unlikely（TPSA>140 Å² 主导，糖苷极性负荷决定）"
        elif n_viol >= 2:
            screen = "unlikely"
            screen_zh = "被动渗透预筛：unlikely（多重包络违反）"
        else:
            screen = "uncertain"
            screen_zh = "被动渗透预筛：uncertain（单条包络违反）"
        # 报告 2.1 增量：被动窗口失败 → 脑暴露决定权转移到转运体层
        determinant = "passive_closed → transporter_resolution_required"
    return dict(
        name=name,
        smiles=smiles,
        TPSA=d["TPSA"],
        MW=d["MW"],
        HBD=d["HBD"],
        HBA=d["HBA"],
        XlogP=d["XlogP"],
        nearest_ref=near["name"] if near else "",
        nearest_label=near["bbb"] if near else "",
        nearest_distance=dist,
        bottleneck=[b[0] + ":" + b[1] for b in bn],
        passive_permeability_screen=screen,
        bbb_determinant_layer=determinant,
        summary=screen_zh,
        references_used=[r["name"] + "(BBB%s)" % r["bbb"] for r in refs],
        lit_benchmarks=[b["name"] for b in LIT_BENCHMARKS],
    )


def screen_file(path, outdir=None):
    import csv

    rows = []
    with open(path, encoding="utf-8-sig") as fh:
        rdr = csv.DictReader(fh)
        for r in rdr:
            smi = r.get("calc_smiles") or r.get("input_smiles") or r.get("smiles") or ""
            cid = r.get("compound_id") or r.get("name") or ""
            res = diagnose(smi, name=cid)
            rows.append(
                dict(
                    compound_id=cid,
                    TPSA=res["TPSA"],
                    MW=res["MW"],
                    HBD=res["HBD"],
                    HBA=res["HBA"],
                    XlogP=res["XlogP"],
                    nearest_ref=res["nearest_ref"],
                    nearest_label=res["nearest_label"],
                    passive_permeability_screen=res["passive_permeability_screen"],
                    bbb_determinant_layer=res["bbb_determinant_layer"],
                    bottleneck="; ".join(res["bottleneck"]),
                    summary=res["summary"],
                )
            )
    if outdir:
        os.makedirs(outdir, exist_ok=True)
        op = os.path.join(outdir, "sar_screen.csv")
        with open(op, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        return rows, op
    return rows, None
