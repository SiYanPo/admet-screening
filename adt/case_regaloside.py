# -*- coding: utf-8 -*-
"""方向B：Regaloside A vs B 的 17.5× 口服生物利用度差异 —— 框架区分能力的 case study。

⚠️ 2026-11-07 更正（外部核实后）：
  1) 原稿把差异写成"9×"，实为 F_B/F_A = 9.1/0.52 = **17.5×**。已全文改正。
  2) 原稿据此断言"框架把 A/B 差异定位到转运体/代谢层，方向一致"。该断言**超出证据**：
     Acta Chromatographica 2026（DOI 10.1556/1326.2026.01506）原文明确"口服后 A 的
     AUC 和 Cmax 反而 much higher 于 B"（且 A 的口服剂量只有 B 的一半），并且
     "B 的清除率显著更高、Vz 更大，导致血药浓度极低"。也就是说 A 的 0.52% 低 F
     来自**极低的全身清除率把 IV 参照抬高**，不是吸收差。
     因此本 case 唯一可声明的结论是"框架在被动层给出的『两者都不可区分』与实测不矛盾"，
     不得写成"框架成功定位了差异层"。详见 references 之外的
     `王百合苷AB_ADMET_PKPD/下一步实验执行报告.md` §2。

外部评审（2026-10-30）原话：
  "你现在的 14 个分子全部 'passive_closed'，这个结果是诚实的，但没有区分度。
   Regaloside A（0.52%）vs B（9.1%）提供了一个天然的正负对照：两者同属肉桂酰糖苷，
   被动渗透都受限，但 B 的口服暴露显著更高。……在论文中把这个 case 写成：'框架无法
   区分 A 和 B 的被动渗透（两者都 closed），但它正确地将 A 和 B 的差异定位到转运体/
   代谢层，而不是被动层'。"
  —— 该建议的后半句已被上述外部核实否证，不得再引用。

⚠️ 2026-11-11 补充（全文到位，方向不变、量级更新）：
  用户提供了全文 PDF；第 6 页 Table 3（A）/ Table 4（B）给出小鼠四剂量组实测 PK 参数。
  用 AUC(0-t) 剂量归一化逐位复现文献 F：A = 0.5225%（文献 0.52%）、
  B = 9.1107%（文献 9.1%），偏差 < 0.011 个百分点；i.v. AUC(0-∞) 的 A/B =
  65.1 / 80.7，复现正文「65–80 times higher」。
  实测点估计（取代此前 >35 / >45 的摘要级下界）：
    CL_B/CL_A = 63.6–81.3（i.v. 实测 63.6 / 75.6；口服恒等式 73.8–81.3）
    Vz_B/Vz_A = 106.7–130.7
    模型 CLint 比 1.69 → 低估 37.6–48.1 倍
  结论方向与本 case 一致：差异在清除/分布层，不在被动渗透层；本 case 的
  「框架在被动层无法区分 A/B」判定不变。数据与复跑脚本见
  `王百合苷AB_ADMET_PKPD/产物/文献PK实测/`。注意文献实测 F 与 PBPK 的
  100 mg / Fa=0.26 情景输出（12.0% / 9.3%）不是同一 estimand，不得互证。

本模块用**真实结构**（PubChem/供应商目录交叉核对，见 SOURCES）跑两条轴：
  1) glycoside_hydrolysis.classify —— 糖苷键类型 + 位阻位置 + 酯/乙酰化
  2) sar.diagnose        —— 被动渗透包络 + bbb_determinant_layer

并输出"框架能区分什么 / 不能区分什么"，以及可检验假设（不是结论）。

结构与实测（交叉核对后采用）：
  Regaloside A  C18H24O10  MW 400.38  CAS 114420-66-5
                1-O-β-D-吡喃葡萄糖基-3-O-对香豆酰甘油（甘油 C2 游离 OH）
  Regaloside B  C20H26O11  MW 442.41  CAS 114420-67-6
                (2S)-1-O-对香豆酰-2-O-β-D-吡喃葡萄糖基-3-O-乙酰甘油
  口服生物利用度：A 0.52% / B 9.1%（Acta Chromatographica 2026，DOI 10.1556/1326.2026.01506）

关键：两者的**糖苷键位置不同**——A 的糖在甘油 C1（伯碳，位阻小），B 的糖在甘油 C2
（仲碳，位阻大）。这是"同系物暴露差异"的一个可解释结构维度，也是本模块新增
`bond_position` 字段的直接动机。
"""

import csv
import io
import os

from . import glycoside_hydrolysis as GH
from . import sar as SAR

SOURCES = {
    "Regaloside_A": dict(
        cas="114420-66-5",
        formula="C18H24O10",
        mw=400.38,
        oral_f_percent=0.52,
        smiles="O(C[C@@H](COC(/C=C/C1=CC=C(O)C=C1)=O)O)[C@@H]2O[C@H](CO)[C@@H](O)[C@H](O)[C@H]2O",
        name_zh="1-O-β-D-吡喃葡萄糖基-3-O-对香豆酰甘油",
        src="AbMole M19006 / InvivoChem (CAS 114420-66-5)",
    ),
    "Regaloside_B": dict(
        cas="114420-67-6",
        formula="C20H26O11",
        mw=442.41,
        oral_f_percent=9.1,
        smiles="CC(=O)OC[C@@H](COC(=O)/C=C/c1ccc(O)cc1)O[C@@H]1O[C@H](CO)[C@@H](O)[C@H](O)[C@H]1O",
        name_zh="(2S)-1-O-对香豆酰-2-O-β-D-吡喃葡萄糖基-3-O-乙酰甘油",
        src="TargetMol/陶术 T4S0622 (CAS 114420-67-6)",
    ),
}

# 17.5× 差异的候选机制（每条都写成"可检验假设"，不是结论）
HYPOTHESES = [
    dict(
        id="H1",
        layer="水解",
        claim="B 的糖苷键在甘油 C2（仲碳，位阻大），模拟肠液水解半衰期应长于 A（伯碳）",
        test="SIF/SCF 孵育 0–24 h，LC-MS/MS 定量原型糖苷剩余率 → t½(B) / t½(A)",
    ),
    dict(
        id="H2",
        layer="被动渗透",
        claim="B 多一个乙酰基、少一个自由羟基（LogP 更高、HBD 更低），Caco-2 Papp(A→B) 应更高",
        test="Caco-2 Papp A>B 双向 + 外排比 ER",
    ),
    dict(
        id="H3",
        layer="外排",
        claim="若两者被动层都被 TPSA 关闭，则 A/B 差异必须由外排（P-gp/BCRP）或首过承载",
        test="± verapamil/ko143 的 ER 变化；门静脉 vs 外周血苷元/原型比",
    ),
    dict(
        id="H4",
        layer="首过",
        claim="A 的游离 C2-OH 使其更易被肠黏膜 II 相酶/糖苷酶处理，首过更高",
        test="肠微粒体 + 肝微粒体共孵育，比较原型与苷元清除",
    ),
]


def _desc(smiles):
    return SAR.compute_descriptors(smiles)


def run():
    """对 A/B 跑两条轴，返回逐分子结果 + 差异表。"""
    out = {}
    for name, meta in SOURCES.items():
        gh = GH.classify(meta["smiles"], name)
        sa = SAR.diagnose(meta["smiles"], name)
        d = _desc(meta["smiles"])
        out[name] = dict(meta=meta, gh=gh, sar=sa, desc=d)
    # 差异表（A 为参照）
    a, b = out["Regaloside_A"], out["Regaloside_B"]
    diffs = []
    for key, label in [
        ("MW", "MW"),
        ("TPSA", "TPSA"),
        ("HBD", "HBD"),
        ("HBA", "HBA"),
        ("XlogP", "XlogP"),
    ]:
        va, vb = a["desc"].get(key), b["desc"].get(key)
        diffs.append(
            dict(
                field=label,
                A=va,
                B=vb,
                delta=(
                    round(vb - va, 3) if (va is not None and vb is not None) else None
                ),
            )
        )
    diffs.append(
        dict(
            field="bond_position",
            A=a["gh"]["bond_position"],
            B=b["gh"]["bond_position"],
            delta="",
        )
    )
    diffs.append(
        dict(
            field="n_ester_bonds",
            A=a["gh"]["n_ester_bonds"],
            B=b["gh"]["n_ester_bonds"],
            delta="",
        )
    )
    diffs.append(
        dict(
            field="acetylated",
            A=a["gh"]["acetylated"],
            B=b["gh"]["acetylated"],
            delta="",
        )
    )
    diffs.append(
        dict(
            field="intestinal_hydrolysis_risk",
            A=a["gh"]["intestinal_hydrolysis_risk"],
            B=b["gh"]["intestinal_hydrolysis_risk"],
            delta="",
        )
    )
    diffs.append(
        dict(
            field="aglycone_first_pass_risk",
            A=a["gh"]["aglycone_first_pass_risk"],
            B=b["gh"]["aglycone_first_pass_risk"],
            delta="",
        )
    )
    diffs.append(
        dict(
            field="passive_permeability_screen",
            A=a["sar"]["passive_permeability_screen"],
            B=b["sar"]["passive_permeability_screen"],
            delta="",
        )
    )
    diffs.append(
        dict(
            field="bbb_determinant_layer",
            A=a["sar"]["bbb_determinant_layer"],
            B=b["sar"]["bbb_determinant_layer"],
            delta="",
        )
    )

    # 判定：框架能区分什么 / 不能区分什么
    same_gh = (
        a["gh"]["intestinal_hydrolysis_risk"] == b["gh"]["intestinal_hydrolysis_risk"]
    )
    same_passive = (
        a["sar"]["passive_permeability_screen"]
        == b["sar"]["passive_permeability_screen"]
    )
    can = []
    if a["gh"]["bond_position"] != b["gh"]["bond_position"]:
        can.append(
            "糖苷键位阻位置：A=%s / B=%s（新增 bond_position 维度）"
            % (a["gh"]["bond_position"], b["gh"]["bond_position"])
        )
    if a["gh"]["acetylated"] != b["gh"]["acetylated"]:
        can.append(
            "乙酰化修饰：A=%s / B=%s（影响亲脂性与自由羟基）"
            % (a["gh"]["acetylated"], b["gh"]["acetylated"])
        )
    if a["gh"]["n_ester_bonds"] != b["gh"]["n_ester_bonds"]:
        can.append(
            "酯键数量：A=%d / B=%d"
            % (a["gh"]["n_ester_bonds"], b["gh"]["n_ester_bonds"])
        )
    if a["desc"].get("XlogP") is not None and b["desc"].get("XlogP") is not None:
        can.append(
            "计算亲脂性：XlogP A=%.2f → B=%.2f（Δ%.2f）"
            % (
                a["desc"]["XlogP"],
                b["desc"]["XlogP"],
                b["desc"]["XlogP"] - a["desc"]["XlogP"],
            )
        )
    cannot = []
    if same_gh:
        cannot.append(
            "肠道水解风险分级相同（都是 %s）——现有规则不足以直接判 A/B 差异，"
            "这正是评审预判的'有价值的限制'" % a["gh"]["intestinal_hydrolysis_risk"]
        )
    if same_passive:
        cannot.append(
            "被动渗透预筛相同（都是 %s）——框架无法在被动层区分 A/B，"
            "必须把差异定位到转运体/代谢层" % a["sar"]["passive_permeability_screen"]
        )

    verdict = (
        "框架无法在被动层区分 A 和 B（两者都 %s）。**但这不等于差异在转运体/代谢层。**"
        "外部核实（2026-11-07）指出：口服后 A 的 AUC/Cmax 反而高于 B（且 A 的口服剂量"
        "只有 B 的一半），A 的 F 只有 0.52%% 是因为它的全身清除率极低、把 IV 参照抬高，"
        "不是吸收差；B 则是清除率显著更高、Vz 更大，血药浓度极低。"
        "因此本 case 只能声明一件事：**框架在被动层给出的『两者都不可区分』与实测不矛盾**。"
        "任何『框架把差异正确定位到转运体/代谢层』的表述都超出证据，不得对外引用。"
        % a["sar"]["passive_permeability_screen"]
    )
    if same_gh:
        verdict += (
            " 诚实限制：当前的肠道水解**分级**对 A/B 相同，"
            "说明纯分级规则不足以区分两者；须用 bond_position/acetylation 这类"
            "细粒度描述符，或用 H1/H2 的实测来分辨。"
            "另注：F 是**剂量归一化**量（IV 与 PO 剂量在两组间都不同），"
            "F 比值 17.5× 不可直接解读为『B 的暴露高 17.5 倍』——实测恰恰相反。"
        )
    verdict += (
        " 2026-11-11 文献全文（PDF 第 6 页 Table 3/4，小鼠实测）确认并量化："
        "i.v. 实测 CL_B/CL_A = 63.6–81.3×、Vz_B/Vz_A = 106.7–130.7×，"
        "i.v. AUC(0-∞) 的 A/B = 65.1 / 80.7（复现正文『65–80 倍』）。"
        "差异在清除与分布层，不在被动渗透层；本 case 的被动层判定不变。"
        "旧的 >35 / >45 为下界留痕，已被点估计取代。"
    )
    return dict(
        per_molecule=out,
        diffs=diffs,
        can_distinguish=can,
        cannot_distinguish=cannot,
        verdict=verdict,
        hypotheses=HYPOTHESES,
    )


def write(result, outdir):
    os.makedirs(outdir, exist_ok=True)
    p1 = os.path.join(outdir, "regaloside_AB_comparison.csv")
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["field", "A", "B", "delta"], extrasaction="ignore"
        )
        w.writeheader()
        for r in result["diffs"]:
            w.writerow(r)
    p2 = os.path.join(outdir, "regaloside_AB_hypotheses.csv")
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["id", "layer", "claim", "test"], extrasaction="ignore"
        )
        w.writeheader()
        for r in result["hypotheses"]:
            w.writerow(r)
    p3 = os.path.join(outdir, "regaloside_AB_case.md")
    L = [
        "# Regaloside A vs B：17.5× 口服生物利用度差异的 case study（方向B）",
        "",
        "> ⚠️ 2026-11-07 更正：F 比值 = 9.1/0.52 = 17.5×（原稿误写 9×）。"
        "外部核实（DOI 10.1556/1326.2026.01506）明确：口服后 A 的 AUC/Cmax **高于** B，"
        "A 的低 F 来自其极低清除率抬高的 IV 参照，不是吸收差。"
        "本 case 不得再用于论证『框架把差异定位到转运体/代谢层』。",
        "> 2026-11-11 全文到位：i.v. 实测 CL_B/CL_A = 63.6–81.3×、"
        "Vz_B/Vz_A = 106.7–130.7×（Table 3/4，已逐格核对原页）；"
        "下界 >35 / >45 由点估计取代，结论方向不变。",
        "",
    ]
    for name, v in result["per_molecule"].items():
        m = v["meta"]
        L.append("## %s — %s" % (name, m["name_zh"]))
        L.append(
            "- CAS %s；%s；MW %.2f；口服 F = %.2f%%"
            % (m["cas"], m["formula"], m["mw"], m["oral_f_percent"])
        )
        L.append("- 结构式来源：%s" % m["src"])
        L.append(
            "- 糖苷轴：键型=%s，位阻位置=%s，酯键数=%d，乙酰化=%s，"
            "水解风险=%s，苷元首过风险=%s"
            % (
                v["gh"]["glycoside_bond_type"],
                v["gh"]["bond_position"],
                v["gh"]["n_ester_bonds"],
                v["gh"]["acetylated"],
                v["gh"]["intestinal_hydrolysis_risk"],
                v["gh"]["aglycone_first_pass_risk"],
            )
        )
        L.append(
            "- 被动轴：TPSA=%s，MW=%s，HBD=%s，HBA=%s，XlogP=%s → %s；%s"
            % (
                v["desc"].get("TPSA"),
                v["desc"].get("MW"),
                v["desc"].get("HBD"),
                v["desc"].get("HBA"),
                v["desc"].get("XlogP"),
                v["sar"]["passive_permeability_screen"],
                v["sar"]["bbb_determinant_layer"],
            )
        )
        L.append("")
    L += ["## 判定", "", result["verdict"], "", "### 框架能区分", ""]
    for c in result["can_distinguish"]:
        L.append("- " + c)
    L += ["", "### 框架不能区分（诚实限制）", ""]
    for c in result["cannot_distinguish"]:
        L.append("- " + c)
    L += [
        "",
        "### 可检验假设（不是结论）",
        "",
        "| ID | 层 | 假设 | 验证 |",
        "|---|---|---|---|",
    ]
    for h in result["hypotheses"]:
        L.append("| %s | %s | %s | %s |" % (h["id"], h["layer"], h["claim"], h["test"]))
    with io.open(p3, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    return p1, p2, p3
