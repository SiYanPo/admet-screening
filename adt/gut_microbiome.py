# -*- coding: utf-8 -*-
"""肠道菌群代谢子模块（v4.19）：中药口服后的"第二套代谢系统"。

为什么单列一个模块（而不是复用 `bt --option`）：
  1. **Biosystem 必须可筛**：BioTransformer 的返回里每条转化都带 `biosystem`
     （实测取值如 "Gut microbial environment" / "Environmental microbial"），
     只有筛出菌群来源的产物才算菌群代谢物。混着人体 CYP 产物一起报，
     会把"肝代谢"说成"菌群代谢"——这是本领域最常见的误标。
  2. **反应标注不可信，必须做化学一致性 QC**：`reaction_type` 是**规则名**，不是对本次
     转化的机理描述，会串到别的底物类上。2026-11-04 实测（HGUT，原始 JSON 已落盘）：
       · 对乙酰氨基酚 → 产出一个**葡萄糖醛酸苷**，却标 `Decarboxylation of aromatic
         L-amino acid` + `enzyme=SULFOTRANSFERASE`（底物根本没有羧基）；
       · 槲皮素 → 4 个**葡糖醛酸苷**被标成同一句"脱羧"；另有 2 条被标
         `2-Hydroxylation of 1,4-disubstituted benzene` 而产物实际**少了一个 O**
         （Δm=−15.99，即脱羟基）——标签方向与化学方向相反；
       · 同一次 HGUT 查询里还有一条 `biosystem="Human"`（儿茶酚 O-甲基化）。
     结论：**产物的 smiles/inchikey 可用，reaction_type/enzymes 不可引用**；
     且 **biosystem 过滤不是可选项**（否则会把人体代谢算成菌群代谢）。
     本模块对每条转化跑质量差校验，不一致的标 `label_inconsistent`。
     4. **0 产物不是"无代谢"**：沿用 registry 的硬规则——0 产物必须先跑同 option
     阳性对照，对照 >0 而待测 =0 才判 out_of_domain。

实测锚点（2026-11-04 本机）：
  · option 取值来自 https://biotransformer.ca/queries/new 的 `<option value=...>`，
    共 12 个：CYP450 / ECBASED / PHASEII / **HGUT** / ENVMICRO / ALLHUMAN /
    SUPERBIO / MULTIBIO / ABIOTICBIO / Combined / Rule Based / CyProduct
  · acetaminophen + HGUT → 3 个唯一代谢物（阳性对照，见 POSITIVE_CONTROL）
  · quercetin + HGUT → 7 个唯一代谢物（3 条菌群转化 × 产物），且 7/7 条标注与质量差矛盾
  · 注册表已记录：cinnamoyl_glycoside 类在 ALLHUMAN（= 人体 + 菌群）下 0 产物
    → 本类菌群规则同样无覆盖，必须记 out_of_domain

配套数据库（只读回填，不预测）：
  MicrobeTCM / GutBugDB / MASI 都是**关系型数据库**，给的是"已知互作/已知代谢物"，
  不是预测。用 `ingest_microbe_db` 回填时必须标 `evidence_level="database_annotation"`、
  `predictive_value="none"`，**不得进 reliab 计票**。
"""

from __future__ import division

import io
import csv

__all__ = [
    "GUT_OPTION",
    "VALID_OPTIONS",
    "POSITIVE_CONTROL",
    "parse_response",
    "filter_biosystem",
    "reaction_label_check",
    "run_gut",
    "metabolite_rows",
    "ingest_microbe_db",
    "limits_statement",
]

GUT_OPTION = "HGUT"

# 来自 https://biotransformer.ca/queries/new 的 option 枚举（2026-11-04 实测）
VALID_OPTIONS = [
    "CYP450",
    "ECBASED",
    "PHASEII",
    "HGUT",
    "ENVMICRO",
    "ALLHUMAN",
    "SUPERBIO",
    "MULTIBIO",
    "ABIOTICBIO",
    "Combined",
    "Rule Based",
    "CyProduct",
]

POSITIVE_CONTROL = {
    "acetaminophen": dict(
        smiles="CC(=O)NC1=CC=C(O)C=C1",
        option=GUT_OPTION,
        expected_unique_metabolites=3,
        verified_at="2026-11-04",
        note="实测 3 个唯一代谢物；其中 1 条转化的 reaction_type "
        "标注错误（见 reaction_label_check 的由来）",
    ),
}

# 反应类型 -> (质量差符号, 期望 Δ质量, 说明)
_MASS_RULES = [
    ("decarboxyl", "<", 0.0, "脱羧必须丢 CO2（≈ −44.01 Da）"),
    ("carboxyl", "<", 0.0, ""),
    ("hydroxyl", ">", 0.0, "羟化必须加 O（≈ +15.99 Da）"),
    ("glucuronid", ">", 100.0, "葡糖醛酸化必须加 C6H8O6（≈ +176.03 Da）"),
    ("sulfat", ">", 50.0, "硫酸化必须加 SO3（≈ +79.96 Da）"),
    ("methyl", ">", 0.0, "甲基化必须加 CH2（≈ +14.02 Da）"),
    ("acetyl", ">", 30.0, "乙酰化必须加 C2H2O（≈ +42.01 Da）"),
    ("dehydrogen", "<", 0.0, "脱氢应减 H2（≈ −2.02 Da）"),
]


def limits_statement():
    return (
        "菌群代谢是**规则引擎推测**，不是实测：BioTransformer 的 HGUT 模块只覆盖已知的"
        "微生物酶规则，对糖苷/多酚类的覆盖极差（本类 ALLHUMAN 实测 0 产物）；"
        "reaction_type/enzymes 字段存在实测标注错误，只可引用 smiles/inchikey；"
        "数据库回填（MicrobeTCM/GutBugDB）是文献级证据，不能当预测值投票。"
    )


def parse_response(d, compound_id=None):
    """BioTransformer 结果 JSON -> 转化记录列表（纯函数，便于离线测试）。

    返回 list[dict(substrate_smiles, product_smiles, product_inchikey, product_name,
                   reaction_type, enzymes, biosystem, compound_id)]
    """
    out = []
    for pred in d.get("predictions") or []:
        cid = compound_id or pred.get("identifier") or ""
        for bt in pred.get("biotransformations") or []:
            subs = bt.get("substrates") or [{}]
            sub = subs[0].get("smiles", "")
            for prod in bt.get("products") or []:
                out.append(
                    dict(
                        compound_id=cid,
                        substrate_smiles=sub,
                        product_smiles=prod.get("smiles", ""),
                        product_inchikey=prod.get("inchikey", ""),
                        product_name=prod.get("title", ""),
                        reaction_type=bt.get("reaction_type", ""),
                        enzymes=";".join(bt.get("metabolic_enzymes") or []),
                        biosystem=bt.get("biosystem", ""),
                    )
                )
    return out


def filter_biosystem(rows, want="gut"):
    """按 biosystem 过滤。want='gut' 匹配含 gut 的（大小写不敏感）。"""
    w = want.lower()
    return [r for r in rows if w in (r.get("biosystem") or "").lower()]


def reaction_label_check(substrate_smiles, product_smiles, reaction_type):
    """反应标注 vs 质量差的一致性检查。

    返回 dict(status=consistent|inconsistent|unknown, delta_mass, rule, reason)。
    这是**必要不充分**检查：质量对得上不代表反应对，但质量对不上一定是错的。
    """
    from rdkit import Chem, RDLogger
    from rdkit.Chem import Descriptors

    RDLogger.DisableLog("rdApp.*")
    s = Chem.MolFromSmiles(substrate_smiles) if substrate_smiles else None
    p = Chem.MolFromSmiles(product_smiles) if product_smiles else None
    if s is None or p is None:
        return dict(
            status="unknown", delta_mass=float("nan"), rule="", reason="SMILES 不可解析"
        )
    dm = Descriptors.ExactMolWt(p) - Descriptors.ExactMolWt(s)
    rt = (reaction_type or "").lower()
    for key, sign, thresh, why in _MASS_RULES:
        if key in rt:
            ok = (dm < thresh) if sign == "<" else (dm > thresh)
            return dict(
                status="consistent" if ok else "inconsistent",
                delta_mass=round(dm, 3),
                rule=key,
                reason=why if not ok else "质量差与反应类型相符",
            )
    return dict(
        status="unknown",
        delta_mass=round(dm, 3),
        rule="",
        reason="反应类型不在可校验清单内（只校验 8 类常见转化）",
    )


def run_gut(
    compounds,
    option=GUT_OPTION,
    steps=1,
    verbose=True,
    control=True,
    dump_dir=None,
    poll_timeout=None,
):
    """真实调用 BioTransformer 菌群模块。

    compounds: [dict(compound_id, smiles)]
    dump_dir: 给了就把每个分子的原始 JSON 落盘（<dump_dir>/bt_raw_<cid>.json）。
              **审计必需**：reaction_type 的标注一致性判断必须能回看原始响应，
              否则"标注错误"这类结论无法复核。
    poll_timeout: 单分子轮询上限（秒）。None=适配器默认（240）。
              HGUT 对多羟基糖苷（实测黄芩苷）会长时间停在 In Progress，
              必须能单独放宽；默认值不许悄悄改，否则跨批复现性丢失。
    返回 (transformation_rows, qc)：qc 含阳性对照结果、逐分子产物数、**逐分子失败清单**。
    单个分子超时/网络失败**不中断整批**（v4.21.1 修复：此前第一个分子超时即
    整批 SystemExit，9 个分子一个结果都留不下）；只有"全部失败"才向上抛。
    """
    from .adapters.biotransformer import BioTransformerAdapter

    if option not in VALID_OPTIONS:
        raise ValueError(
            "option=%r 不在 BioTransformer 枚举内：%s" % (option, VALID_OPTIONS)
        )
    kw = {}
    if poll_timeout:
        kw["poll_timeout"] = int(poll_timeout)
    ad = BioTransformerAdapter(options=[option], steps=steps, verbose=verbose, **kw)
    qc = dict(
        option=option,
        control={},
        out_of_domain=[],
        n_products={},
        failed=[],
        poll_timeout_s=int(kw.get("poll_timeout", 240)),
    )
    if control:
        ctl = ad.control(option=option, controls=tuple(POSITIVE_CONTROL.keys()))
        qc["control"] = ctl
        exp = POSITIVE_CONTROL["acetaminophen"]["expected_unique_metabolites"]
        got = ctl.get("acetaminophen")
        qc["control_pass"] = got == exp
    rows = []
    for c in compounds:
        cid = c["compound_id"]
        smi = c.get("calc_smiles") or c.get("smiles")
        try:
            qid = ad.submit(cid, smi, option, steps=steps)
            d = ad.poll(qid)
        except Exception as e:  # noqa: BLE001
            # 失败 ≠ 无代谢：记进 failed，继续下一个，最后由 CLI 单独报
            qc["failed"].append(
                dict(compound_id=cid, stage="submit/poll", reason=str(e)[:240])
            )
            qc["n_products"][cid] = None
            if verbose:
                print("[gut-micro] %s 失败（不是'无代谢'）：%s" % (cid, str(e)[:120]))
            continue
        n = int(d.get("number_of_unique_metabolites") or 0)
        qc["n_products"][cid] = n
        if dump_dir:
            import os as _os
            import json as _json

            if not _os.path.isdir(dump_dir):
                _os.makedirs(dump_dir, exist_ok=True)
            p = _os.path.join(dump_dir, "bt_raw_%s.json" % cid)
            with io.open(p, "w", encoding="utf-8") as fh:
                fh.write(_json.dumps(d, ensure_ascii=False, indent=2))
            qc.setdefault("raw_dumps", []).append(p)
        parsed = parse_response(d, compound_id=cid)
        gut = filter_biosystem(parsed, "gut")
        if n == 0:
            # 对照 >0 而待测 =0 -> out_of_domain（不是"无代谢"）
            qc["out_of_domain"].append(
                dict(
                    compound_id=cid,
                    n=0,
                    reason="0 产物；阳性对照 %s -> 若对照>0，本分子判 out_of_domain"
                    % (qc["control"] or "未跑"),
                )
            )
        rows.extend(gut)
    n_ok = len(
        [c for c in compounds if qc["n_products"].get(c["compound_id"]) is not None]
    )
    if compounds and n_ok == 0 and qc["failed"]:
        # 整批零成功 = 网络/服务侧问题，不能静默返回空表冒充"无代谢"
        raise RuntimeError(
            "全部 %d 个分子均失败（首个原因：%s）"
            % (len(qc["failed"]), qc["failed"][0]["reason"])
        )
    qc["n_ok"] = n_ok
    qc["n_failed"] = len(qc["failed"])
    return rows, qc


def metabolite_rows(
    rows,
    source="biotransformer",
    source_version="3.0",
    provenance_url="https://biotransformer.ca",
):
    """转成 metabolites.csv 契约行；附带反应标注 QC 列。"""
    out = []
    for r in rows:
        chk = reaction_label_check(
            r.get("substrate_smiles"), r.get("product_smiles"), r.get("reaction_type")
        )
        out.append(
            dict(
                compound_id=r.get("compound_id", ""),
                metabolite_smiles=r.get("product_smiles", ""),
                metabolite_inchikey=r.get("product_inchikey", ""),
                name=r.get("product_name", ""),
                reaction_type=r.get("reaction_type", ""),
                enzymes=r.get("enzymes", ""),
                biosystem=r.get("biosystem", "") or "gut_microbial",
                source=source,
                source_version=source_version,
                provenance_url=provenance_url,
                label_check=chk["status"],
                label_delta_mass=chk["delta_mass"],
                label_reason=chk["reason"],
                predictive_value="rule_engine",
            )
        )
    return out


def ingest_microbe_db(path, source="microbetcm", notice=""):
    """回填 MicrobeTCM / GutBugDB / MASI 的查询结果。

    必需列：compound_id + (microbe | metabolite_smiles)。
    全部标 evidence_level=database_annotation、predictive_value=none。
    """
    rows, problems = [], []
    with io.open(path, encoding="utf-8-sig") as fh:
        rd = csv.DictReader(fh)
        for i, r in enumerate(rd, 1):
            cid = (r.get("compound_id") or "").strip()
            if not cid:
                problems.append("row %d: 缺 compound_id" % i)
                continue
            if not (r.get("microbe") or r.get("metabolite_smiles")):
                problems.append("row %d: microbe 与 metabolite_smiles 至少给一个" % i)
                continue
            rows.append(
                dict(
                    compound_id=cid,
                    microbe=(r.get("microbe") or "").strip(),
                    interaction=(r.get("interaction") or "").strip(),
                    metabolite_smiles=(r.get("metabolite_smiles") or "").strip(),
                    evidence=(r.get("evidence") or "").strip(),
                    doi=(r.get("doi") or "").strip(),
                    source=source,
                    evidence_level="database_annotation",
                    predictive_value="none",
                    note=notice or "文献/数据库注解，不是预测；不得进 reliab 计票",
                )
            )
    return rows, problems
