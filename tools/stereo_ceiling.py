# -*- coding: utf-8 -*-
"""立体盲区证书：把"消旋体给不出手性结论"从一句免责声明变成可核对的数字。

### 问题
面板 30 个分子里有 4 个（华法林、普萘洛尔、特非那定、酮康唑）在 ChEMBL 锚定的
结构里**没有指定立体化学**（InChIKey 的立体层是 `UHFFFAOYSA` 而不是带手性的形式）。
这不等于"不存在手性"：它们各自有 1–2 个未指定手性中心，真实药物是单一对映体或
已知比例的外消旋体。框架此前只能笼统写"立体上限"，无法回答两个具体问题：

  1. 本框架的预测栈对 R/S **到底有没有区分力**？
  2. 如果没有，这个盲区**会不会改变裁决**？

### 做法
对每个含未指定手性中心的分子：
  * 用 RDKit `EnumerateStereoisomers` 枚举**全部**立体异构体（2^k，酮康唑 4 个）；
  * 每个异构体跑一遍完整的 2D 预测栈（logP / TPSA / MW / HBD / HBA / 可旋转键 /
    净电荷 / logD@7.4 / 电荷类别 / P-gp-BCRP 外排启发式）；
  * 报每个描述符在异构体间的 **max |Δ|**。

若全部为 0，则证明接口层面**结构性失明**——这不是"模型不够准"，是描述符根本不编码
手性（Crippen logP、TPSA、SMARTS 匹配都是 2D 拓扑量）。此时任何对映体特异结论
都只能来自实测，框架只能给"外消旋上限"。

### 与 pred-shift 的关系
`pred-shift` 用结构变体测"去立体"的预测位移，得到 logP 位移 0.000；
本工具从**枚举**方向得到同一结论（max|Δ|=0），两条独立路径互相印证。

产出：stereo_ceiling.csv / stereo_ceiling.md
"""

import csv
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rdkit import Chem, RDLogger  # noqa: E402
from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors  # noqa: E402
from rdkit.Chem.EnumerateStereoisomers import (  # noqa: E402
    EnumerateStereoisomers,
    StereoEnumerationOptions,
)

RDLogger.DisableLog("rdApp.*")

DESC = (
    "logP",
    "tpsa",
    "mw",
    "hbd",
    "hba",
    "rotb",
    "net_charge",
    "logd_7_4",
    "charge_class",
    "efflux_flag",
)


def _profile(smi):
    """单个立体异构体的 2D 画像。"""
    from adt import ionization as IZ
    from adt import efflux_heuristic as EF

    m = Chem.MolFromSmiles(smi)
    if m is None:
        return None
    d = dict(
        logP=round(Crippen.MolLogP(m), 6),
        tpsa=round(Descriptors.TPSA(m), 6),
        mw=round(Descriptors.MolWt(m), 4),
        hbd=rdMolDescriptors.CalcNumHBD(m),
        hba=rdMolDescriptors.CalcNumHBA(m),
        rotb=rdMolDescriptors.CalcNumRotatableBonds(m),
    )
    try:
        p = IZ.ionization_profile(smi)
        d["net_charge"] = round(float(p.get("net_charge") or 0.0), 6)
        # logD 不是 profile 的字段（profile 只给 logd_shift）；必须走
        # logd_from_logp(logP, profile) 才是与 CLI 同一条算式。
        ld = IZ.logd_from_logp(d["logP"], p)
        d["logd_7_4"] = (
            round(float(ld["logD"]), 6) if ld.get("logD") is not None else None
        )
        d["charge_class"] = p.get("charge_class") or ""
    except Exception:
        d["net_charge"], d["logd_7_4"], d["charge_class"] = None, None, ""
    try:
        ef = EF.pgp_bcrp_efflux_heuristic(smiles=smi)
        d["efflux_flag"] = ef.get("level") or ef.get("flag") or str(ef)[:20]
    except Exception:
        d["efflux_flag"] = ""
    return d


def _max_delta(profiles, key):
    vals = [p[key] for p in profiles if p and p.get(key) is not None]
    if len(vals) < 2:
        return None
    if isinstance(vals[0], str):
        return 0.0 if len(set(vals)) == 1 else float(len(set(vals)) - 1)
    return round(max(vals) - min(vals), 6)


def main():
    argv = sys.argv[1:]
    cpath = (
        argv[argv.index("--compounds") + 1]
        if "--compounds" in argv
        else r"D:/WorkBuddy/本地文件/2026-11-17-22-52-47/panel_run/final/out/compounds.csv"
    )
    outdir = (
        argv[argv.index("--outdir") + 1]
        if "--outdir" in argv
        else r"D:/WorkBuddy/本地文件/2026-11-17-22-52-47/real_legs/out/stereo"
    )
    os.makedirs(outdir, exist_ok=True)

    with io.open(cpath, encoding="utf-8-sig") as fh:
        comps = list(csv.DictReader(fh))

    rows, detail = [], []
    for c in comps:
        smi = c.get("calc_smiles") or c.get("input_smiles")
        m = Chem.MolFromSmiles(smi) if smi else None
        if m is None:
            continue
        cent = Chem.FindMolChiralCenters(
            m, includeUnassigned=True, useLegacyImplementation=False
        )
        unassigned = [i for i, t in cent if t == "?"]
        if not unassigned:
            continue
        opts = StereoEnumerationOptions(onlyUnassigned=True, unique=True, maxIsomers=32)
        isos = list(EnumerateStereoisomers(m, options=opts))
        smis = [Chem.MolToSmiles(x) for x in isos]
        profs = [_profile(s) for s in smis]
        deltas = {k: _max_delta(profs, k) for k in DESC}
        numeric = [
            v
            for k, v in deltas.items()
            if isinstance(v, (int, float)) and k != "efflux_flag"
        ]
        rows.append(
            dict(
                compound_id=c["compound_id"],
                inchikey=c.get("inchikey", ""),
                n_unassigned_centers=len(unassigned),
                unassigned_atoms=";".join(str(i) for i in unassigned),
                n_stereoisomers=len(smis),
                max_abs_delta_overall=(round(max(numeric), 6) if numeric else ""),
                **{("delta_" + k): ("" if v is None else v) for k, v in deltas.items()},
                verdict=(
                    "stereo_blind"
                    if (numeric and max(numeric) == 0)
                    else "stereo_sensitive"
                ),
            )
        )
        for s2, p2 in zip(smis, profs):
            detail.append(
                dict(
                    compound_id=c["compound_id"],
                    smiles=s2,
                    logP=p2["logP"],
                    tpsa=p2["tpsa"],
                    net_charge=p2["net_charge"],
                    logd_7_4=p2["logd_7_4"],
                    charge_class=p2["charge_class"],
                )
            )

    p1 = os.path.join(outdir, "stereo_ceiling.csv")
    with io.open(p1, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    p2 = os.path.join(outdir, "stereo_isomers.csv")
    with io.open(p2, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(detail[0].keys()))
        w.writeheader()
        w.writerows(detail)

    blind = [r for r in rows if r["verdict"] == "stereo_blind"]
    md = [
        "# 立体盲区证书（由 `tools/stereo_ceiling.py` 生成）",
        "",
        "判据：对每个含**未指定手性中心**的分子，枚举全部立体异构体，跑完整 2D",
        "预测栈；若异构体间所有描述符的 max|Δ| = 0，则该分子在本框架内",
        "**结构性失明**（描述符不编码手性），结论只能作为外消旋上限。",
        "",
        "| 分子 | 未指定中心 | 立体异构体数 | max|Δ|（全部描述符） | 判定 |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        md.append(
            "| %s | %d | %d | %s | %s |"
            % (
                r["compound_id"],
                r["n_unassigned_centers"],
                r["n_stereoisomers"],
                r["max_abs_delta_overall"],
                r["verdict"],
            )
        )
    md += ["", "## 结论", ""]
    if blind and len(blind) == len(rows):
        md.append(
            "**%d/%d 个分子全部结构性失明**：异构体间的 logP、TPSA、净电荷、"
            "logD@7.4 完全一致（max|Δ| = 0）。" % (len(blind), len(rows))
        )
        md.append("")
        md.append(
            "这不是模型精度问题：Crippen logP、TPSA、SMARTS 匹配都是 2D 拓扑量，"
            "**根本不接收手性信息**。因此："
        )
        md.append("")
        md.append("1. 任何对映体特异结论（哪一个更强、哪一个更毒）**只能来自实测**；")
        md.append(
            "2. 本框架对这些分子给出的一切数值，其含义是「外消旋体/未指定立体"
            "结构的平均上限」，不是某个对映体的值；"
        )
        md.append(
            "3. 与 `pred-shift` 的「去立体」变体位移 0.000 互相印证——"
            "两条独立路径（结构扰动 / 立体枚举）得到同一结论。"
        )
    else:
        md.append("存在异构体间描述符不一致的分子，见上表 `stereo_sensitive` 行。")
    p3 = os.path.join(outdir, "stereo_ceiling.md")
    with io.open(p3, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")

    print("[stereo] %d 个含未指定中心的分子 -> %s" % (len(rows), p1))
    for r in rows:
        print(
            "   %-16s 中心=%d 异构体=%d max|Δ|=%s %s"
            % (
                r["compound_id"],
                r["n_unassigned_centers"],
                r["n_stereoisomers"],
                r["max_abs_delta_overall"],
                r["verdict"],
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
