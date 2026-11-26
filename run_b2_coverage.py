# -*- coding: utf-8 -*-
"""B2：BBB 双层机制的转运体先验覆盖度（黑榜 B2 / O5-D2）。

输入：
  - out_ext/tdc_cache/admet_group/bbb_martins/test.csv  (406 个 BBB_Martins 测试分子：Drug_ID, Drug(SMILES), Y)
  - references/transporter_priors.yaml  (本 skill 现有转运体先验)

做法：
  1) 用 rdkit 对 406 个 SMILES 套用 yaml 里"真正做结构判定"的 chemotype SMARTS，
     统计每个 chemotype 命中数、以及命中任意已实现规则的分子数。
  2) 用 yaml 自己的 high_tpsa 规则（TPSA>140 => 被动渗透不足、转运体主导）作为
     "应被转运体机制解释的分子"的分母代理。
  3) 列出 canonical 人类 BBB 转运体集合（KEGG BRITE 02000 Transporters + 文献），
     与本 skill 实际有 moiety 规则的转运体对比，给出转运体级覆盖度。
  4) 输出：分子级覆盖率、转运体级覆盖率、以及"双层机制"表述是否应降级的判定。
"""
import argparse
import csv
import io
import json
import yaml
from collections import Counter
from pathlib import Path

from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors
RDLogger.DisableLog("rdApp.*")

SKILL = Path(__file__).resolve().parent
TEST_CSV = SKILL / "out_ext/tdc_cache/admet_group/bbb_martins/test.csv"
YAML_P = SKILL / "references/transporter_priors.yaml"
DEFAULT_OUT = SKILL / "out_ext/tdc/b2_coverage.json"


def main():
    ap = argparse.ArgumentParser(
        description="B2：BBB 转运体先验覆盖度（分子级 + 转运体级），产出可核对 JSON")
    ap.add_argument("--test-csv", default=str(TEST_CSV),
                    help="BBB_Martins 测试分子表（列 Drug_ID,Drug,Y）")
    ap.add_argument("--priors", default=str(YAML_P),
                    help="transporter_priors.yaml")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="输出 JSON 路径")
    a = ap.parse_args()
    test_csv, priors_p, out_p = Path(a.test_csv), Path(a.priors), Path(a.out)

    rows = list(csv.DictReader(open(test_csv, encoding="utf-8-sig")))
    n = len(rows)
    print(f"BBB_Martins 测试集分子数: {n}")

    doc = yaml.safe_load(open(priors_p, encoding="utf-8"))
    chemotypes = doc.get("chemotypes", [])
    moiety_rules = doc.get("moiety_rules", [])

    # ---- 1) 已实现的结构判定规则（chemotype SMARTS）----
    smarts_list = []
    for c in chemotypes:
        s = c.get("smarts")
        if s:
            try:
                pat = Chem.MolFromSmarts(s)
                if pat is not None:
                    smarts_list.append((c["id"], s, pat))
                else:
                    print(f"  [WARN] 无效 SMARTS 跳过: {c['id']} ({s})")
            except Exception as e:
                print(f"  [WARN] SMARTS 解析失败: {c['id']} ({e})")

    chem_hits = Counter()
    tpsa_gt140 = 0
    mol_hit_any = 0
    oata2b1_proxy = 0  # 含糖/吡喃糖骨架（OATP2B1 已实现规则的最接近代理）
    per_mol_summary = []

    for r in rows:
        smi = r.get("Drug", "")
        m = Chem.MolFromSmiles(smi) if smi else None
        if m is None:
            per_mol_summary.append((r.get("Drug_ID", "?"), "PARSE_FAIL", []))
            continue
        tpsa = Descriptors.TPSA(m)
        if tpsa > 140:
            tpsa_gt140 += 1
        hit_ids = []
        for cid, s, pat in smarts_list:
            if m.HasSubstructMatch(pat):
                hit_ids.append(cid)
                chem_hits[cid] += 1
        if hit_ids:
            mol_hit_any += 1
        # OATP2B1 moiety 规则本质是"糖基"，用 glucopyranoside SMARTS 作代理判定
        if any(cid == "glucopyranoside" for cid in hit_ids):
            oata2b1_proxy += 1
        per_mol_summary.append((r.get("Drug_ID", "?"), round(tpsa, 1), hit_ids))

    print("\n=== A. 每个 chemotype SMARTS 在 406 分子中的命中数 ===")
    for cid, s, pat in smarts_list:
        print(f"  {cid:22s} {chem_hits[cid]:4d} / {n}   ({s})")

    print(f"\n=== B. 分子级覆盖度 ===")
    print(f"  分母(应被转运体解释): TPSA>140 的分子 = {tpsa_gt140} / {n} = {tpsa_gt140/n:.1%}")
    print(f"  分子命中任意 chemotype 规则: {mol_hit_any} / {n} = {mol_hit_any/n:.1%}")
    print(f"  含糖/吡喃糖骨架(OATP2B1 代理): {oata2b1_proxy} / {n} = {oata2b1_proxy/n:.1%}")
    if tpsa_gt140:
        cov = oata2b1_proxy / tpsa_gt140
        print(f"  => OATP2B1 先验能解释 '转运体主导' 分子的 {cov:.1%} (numerator={oata2b1_proxy}, denom={tpsa_gt140})")

    # ---- 2) 转运体级覆盖度 ----
    # canonical 人类 BBB 相关转运体（KEGG BRITE 02000 Transporters 分类 + 文献综述级）
    bbb_families = {
        "外排 (ABC)": ["ABCB1/P-gp", "ABCG2/BCRP", "ABCC1/MRP1", "ABCC2/MRP2",
                       "ABCC4/MRP4", "ABCC5/MRP5"],
        "摄取 (SLC, BBB)": ["OATP1A2/SLCO1A2", "OATP2B1/SLCO2B1", "OAT1/SLC22A12",
                            "OAT3/SLC22A8", "OCT1/SLC22A1", "OCT2/SLC22A2",
                            "ENT1/SLC29A1", "ENT2/SLC29A2", "LAT1/SLC7A5",
                            "GLUT1/SLC2A1", "MCT1/SLC16A1", "PEPT2/SLC15A2"],
    }
    all_t = [t for v in bbb_families.values() for t in v]

    # yaml 里"真正有 moiety 规则"的转运体
    implemented_moiety = sorted({mr.get("transporter") for mr in moiety_rules})
    # yaml 里 chemotype 关联提到的转运体（仅为 rationale，非结构判定）
    mentioned = set()
    for c in chemotypes:
        for t in c.get("transporters", []):
            mentioned.add(t.get("name"))

    print(f"\n=== C. 转运体级覆盖度 ===")
    print(f"  canonical BBB 转运体机制(家族数): {len(all_t)}")
    print(f"  yaml 有 moiety 规则(结构判定)的转运体: {implemented_moiety}")
    print(f"  yaml chemotype 文字提及的转运体: {sorted(mentioned)}")
    print(f"  => 转运体级覆盖率(有结构规则): {len([x for x in implemented_moiety if x])} / {len(all_t)}")

    print(f"\n=== D. 结论 ===")
    print(f"  分子级: OATP2B1 先验对 TPSA>140 的转运体主导分子解释力 ≈ {oata2b1_proxy}/{tpsa_gt140} ({ (oata2b1_proxy/tpsa_gt140 if tpsa_gt140 else 0):.1%})")
    print(f"  转运体级: 本 skill 仅在 OATP2B1(黄酮专属) 有结构判定规则, 对 P-gp/BCRP/OATP1A2/LAT1/GLUT1 等 BBB 主通道无 moiety 规则")
    print(f"  判定: 'BBB 双层机制' 当前表述应降级为 '仅覆盖 OATP2B1 分支(且限于黄酮类骨架)'")

    # ---- 3) 落盘（可核对产物；此前本脚本只打印、无产物，故从未能登记进脚本注册表）----
    payload = dict(
        n_molecules=n,
        chemotype_hits={cid: chem_hits[cid] for cid, _s, _p in smarts_list},
        molecule_level=dict(
            n_hit_any=mol_hit_any,
            frac_hit_any=round(mol_hit_any / n, 4) if n else None,
            n_tpsa_gt140=tpsa_gt140,
            frac_tpsa_gt140=round(tpsa_gt140 / n, 4) if n else None,
            n_oatp2b1_proxy=oata2b1_proxy,
            oatp2b1_explains_tpsa_gt140=(round(oata2b1_proxy / tpsa_gt140, 4)
                                         if tpsa_gt140 else None),
            # 文档引用的"分子级覆盖率 ≤7.1%"= n_hit_any / n 的上界口径；此处同时给出原始计数
            ceiling_frac=round(max(mol_hit_any, oata2b1_proxy) / n, 4) if n else None,
        ),
        transporter_level=dict(
            canonical=all_t,
            n_canonical=len(all_t),
            implemented_moiety=implemented_moiety,
            n_implemented=len([x for x in implemented_moiety if x]),
            referenced_without_moiety=sorted(
                {x for x in all_t if not any(x.split("/")[0] in (m or "")
                                             for m in implemented_moiety)}),
        ),
        verdict=("'BBB 双层机制' 应降级为 '仅覆盖 OATP2B1 分支（黄酮专属，对通用 CNS 集几乎不触发）'"),
        caveat=("分母为文献/KEGG BRITE 派生的保守代理（TPSA>140 代表转运体主导），"
                "非实验实测，故覆盖度是保守下界估计，不是金标准"),
    )
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with io.open(out_p, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"\n[run_b2_coverage] -> {out_p}")


if __name__ == "__main__":
    main()
