# -*- coding: utf-8 -*-
"""把"面板触发不了、只能靠测试覆盖"的命令接到**真实真值**上跑一遍。

背景（2026-11-19 面板实跑收尾）：覆盖率核算里有 8 条命令标 TEST_ONLY，
理由是"需要实测真值标签 / 需要同一分子的多源重复预测 / 需要网页人工导出"。
但本机其实已有三份真实数据，完全够用：

  A. `out_ext/truth_{train,test}.csv`（OpenADMET-ExpansionRx 官方切分，
     train 25 265 行 / test 10 738 行实测；9 个端点；2 282 个测试化合物）
  B. `out_ext/measurements_{baseline_morgan,baseline_rdkit}.csv`
     （同一批化合物上的两个真实模型源）+ `out_ext/reliability.csv`
  C. `out_ext/external/herg_holdout_{rows}.csv`（959 个 ChEMBL hERG 留出分子，
     含 pIC50 与二分类 y）+ `_legacy_rows.csv`（9 443 个训练分子）

于是把 8 条命令逐条改成真跑：
  conformal / conformal-class / ablate / decision-value / prospect /
  cross-class / pred-shift / benchmark

未纳入（并说明为什么）：
  * xeno-ingest —— 站点 Terms 明确"程序化访问需商业许可"，自动填表等于绕过许可，
    属于**许可边界**而非能力缺口（见 adt/adapters/xenosite.py 的说明）。

产出：real_legs/{in,out}/、real_legs/real_legs_summary.json、real_legs/REPORT.md
"""

import csv
import io
import json
import os
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# 以脚本方式运行时 sys.path[0] 是 tools/，`import adt` 会失败（本轮踩过）
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
OUT_EXT = os.path.join(ROOT, "out_ext")
WORK = r"D:/WorkBuddy/本地文件/2026-11-17-22-52-47"
PANEL_REL = os.path.join(WORK, "panel_run", "final", "out", "reliability.csv")
LEGS = os.path.join(WORK, "real_legs")
IND = os.path.join(LEGS, "in")
OUTD = os.path.join(LEGS, "out")

PY = sys.executable


def rd(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def wr(p, rows, cols=None):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    cols = cols or list(rows[0].keys())
    with io.open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return p


def run(name, argv, timeout=1800):
    """跑一条 CLI 命令，回传退出码与输出尾部。"""
    os.makedirs(os.path.join(OUTD, name), exist_ok=True)
    cmd = [PY, "-m", "adt.cli"] + argv
    print("\n$ " + " ".join(cmd))
    try:
        p = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        tail = (p.stdout or "") + (p.stderr or "")
        print(tail[-2500:])
        return dict(step=name, rc=p.returncode, tail=tail[-4000:])
    except subprocess.TimeoutExpired:
        return dict(step=name, rc=-9, tail="timeout after %ss" % timeout)


# --------------------------------------------------------------- A. hERG 二分类
def build_herg():
    """在 legacy（9 443）上训两个模型，预测 holdout（959）——真实二分类端点。

    conformal-class 要的是 P(class=1) 与 0/1 真值，且要求校准/评测不相交
    （C07 的 hash 切分在内部完成，这里只需给全量 pairs）。
    """
    import numpy as np
    from rdkit import Chem, RDLogger
    from rdkit.Chem import AllChem, Descriptors
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import RandomForestClassifier

    RDLogger.DisableLog("rdApp.*")
    tr = rd(os.path.join(OUT_EXT, "external", "_legacy_rows.csv"))
    te = rd(os.path.join(OUT_EXT, "external", "herg_holdout_rows.csv"))

    def morg(smi):
        m = Chem.MolFromSmiles(smi)
        if m is None:
            return None
        fp = AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)
        return np.array(fp, dtype=np.float32)

    def desc(smi):
        m = Chem.MolFromSmiles(smi)
        if m is None:
            return None
        out = []
        for nm in (
            "MolWt",
            "MolLogP",
            "TPSA",
            "NumHDonors",
            "NumHAcceptors",
            "NumRotatableBonds",
            "RingCount",
            "NumAromaticRings",
            "FractionCSP3",
            "HeavyAtomCount",
            "NHOHCount",
            "NOCount",
        ):
            try:
                out.append(float(getattr(Descriptors, nm)(m)))
            except Exception:
                out.append(0.0)
        return np.array(out, dtype=np.float32)

    Xtr_m, ytr, Xte_m, ids = [], [], [], []
    for r in tr:
        v = morg(r["smiles"])
        if v is None:
            continue
        Xtr_m.append(v)
        ytr.append(int(float(r["y"])))
    for r in te:
        v = morg(r["smiles"])
        if v is None:
            continue
        Xte_m.append(v)
        ids.append(r["chembl_id"])
    Xtr_m, Xte_m, ytr = np.array(Xtr_m), np.array(Xte_m), np.array(ytr)
    print("[herg] morgan train=%s test=%s" % (Xtr_m.shape, Xte_m.shape))

    clf = RandomForestClassifier(
        n_estimators=300, min_samples_leaf=2, n_jobs=-1, random_state=0
    )
    clf.fit(Xtr_m, ytr)
    p_morg = clf.predict_proba(Xte_m)[:, 1]

    Xtr_d, Xte_d, ytr_d = [], [], []
    for r in tr:
        v = desc(r["smiles"])
        if v is None:
            continue
        Xtr_d.append(v)
        ytr_d.append(int(float(r["y"])))
    for r in te:
        v = desc(r["smiles"])
        if v is not None:
            Xte_d.append(v)
    Xtr_d, Xte_d = np.array(Xtr_d), np.array(Xte_d)
    rid = Ridge(alpha=1.0)
    rid.fit(Xtr_d, np.array(ytr_d, dtype=float))
    p_desc = np.clip(rid.predict(Xte_d), 0.0, 1.0)

    preds = []
    for cid, p1, p2 in zip(ids, p_morg, p_desc):
        for src, pv in (("rf_morgan_legacy", p1), ("ridge_desc_legacy", p2)):
            preds.append(
                dict(
                    compound_id=cid,
                    endpoint="herg_external",
                    value="%.6f" % pv,
                    unit="probability",
                    source=src,
                    source_version="1.0",
                    retrieved_at="2026-11-19T00:00:00",
                    domain_flag="predicted",
                    uncertainty="",
                    provenance_url="local:out_ext/external/_legacy_rows.csv",
                    note="trained on legacy 9443, applied to holdout 959",
                )
            )
    p1 = wr(os.path.join(IND, "herg_pred.csv"), preds)

    truth = []
    for r in te:
        y = int(float(r["y"]))
        truth.append(
            dict(
                compound_id=r["chembl_id"],
                endpoint="herg_external",
                truth_value=y,
                truth_class="PASS" if y == 0 else "FAIL",
                source="ChEMBL-hERG-holdout",
                assay="pIC50>=6 -> blocker (y=1)",
                provenance_url="local:out_ext/external/herg_holdout_rows.csv",
                note="y=1 blocker",
            )
        )
    p2 = wr(os.path.join(IND, "herg_truth.csv"), truth)
    return p1, p2


# -------------------------------------------------- B. pred-shift 的真实变体
def build_variants():
    """用 ac_variants.csv 的真实结构变体（stereo_removed / tautomer）算位移。

    端点取 logP（与 source_rho_by_endpoint.csv 的 logP 同名，可直接比值）、
    logD@7.4、净电荷、TPSA。这样"结构扰动引起的位移"和"模型间分歧"是同一量纲，
    比值才有意义。
    """
    import numpy as np
    from rdkit import Chem, RDLogger
    from rdkit.Chem import Crippen, Descriptors
    from adt import ionization as IZ

    RDLogger.DisableLog("rdApp.*")
    src_p = os.path.join(OUTD, "acplan", "ac_variants.csv")
    if not os.path.exists(src_p):
        src_p = os.path.join(ROOT, "run6", "acplan", "ac_variants.csv")
    src = rd(src_p)
    rows = []
    for r in src:
        smi = r["smiles"]
        m = Chem.MolFromSmiles(smi)
        if m is None:
            print("[variants] skip bad smiles %s" % r["compound_id"])
            continue
        vals = {
            "logP": Crippen.MolLogP(m),
            "tpsa": Descriptors.TPSA(m),
        }
        try:
            prof = IZ.ionization_profile(smi)
            for k, v in (
                ("logD74", prof.get("logd_7_4")),
                ("net_charge", prof.get("net_charge")),
            ):
                if v is not None:
                    vals[k] = float(v)
        except Exception as exc:
            print("[variants] ionization failed %s: %s" % (r["compound_id"], exc))
        for ep, v in vals.items():
            rows.append(
                dict(
                    compound_id=r["compound_id"],
                    variant=r["variant"],
                    endpoint=ep,
                    value="%.5f" % float(v),
                    noop=(r.get("noop") or "N"),
                )
            )
    p = wr(os.path.join(IND, "pred_shift_variants.csv"), rows)
    print(
        "[variants] %d 行（%d 化合物 × %d 变体）"
        % (
            len(rows),
            len({x["compound_id"] for x in rows}),
            len({x["variant"] for x in rows}),
        )
    )
    return p


def main():
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    os.makedirs(IND, exist_ok=True)
    os.makedirs(OUTD, exist_ok=True)
    res = []

    def want(name):
        return (only is None) or (name in only)

    tr_test = os.path.join(OUT_EXT, "truth_test.csv")
    morgan = os.path.join(OUT_EXT, "measurements_baseline_morgan.csv")
    rdkit_p = os.path.join(OUT_EXT, "measurements_baseline_rdkit.csv")
    merged = os.path.join(OUT_EXT, "measurements_merged.csv")
    rel_ext = os.path.join(OUT_EXT, "reliability.csv")
    rules = os.path.join(OUT_EXT, "external_rules.yaml")
    reg = os.path.join(ROOT, "references", "02_source_registry.yaml")

    # --- 1. benchmark（真实 OpenADMET，morgan 单源） ---
    if want("benchmark"):
        res.append(
            run(
                "benchmark",
                [
                    "benchmark",
                    "--predictions",
                    morgan,
                    "--truth",
                    tr_test,
                    # 必须给 --rules：否则 benchmark 不知道端点方向（up=越大越好 /
                    # down=越小越好 / window=非单调），9 个端点里 5 个 AUROC 会整体翻反
                    # （实测：无规则平均 0.382，给规则后 0.730）
                    "--rules",
                    rules,
                    "--outdir",
                    os.path.join(OUTD, "benchmark"),
                ],
            )
        )

    # --- 1b. baseline（真实 train/test 两组已标注长表） ---
    if want("baseline"):
        res.append(
            run(
                "baseline",
                [
                    "baseline",
                    "--train-meas",
                    os.path.join(OUT_EXT, "measurements_train.csv"),
                    "--test-meas",
                    os.path.join(OUT_EXT, "measurements_test.csv"),
                    "--train-compounds",
                    os.path.join(OUT_EXT, "compounds_train.csv"),
                    "--test-compounds",
                    os.path.join(OUT_EXT, "compounds_test.csv"),
                    "--method",
                    "both",
                    "--rules",
                    rules,
                    "--outdir",
                    os.path.join(OUTD, "baseline"),
                ],
            )
        )

    # --- 2. conformal（真实连续端点 logD） ---
    if want("conformal"):
        res.append(
            run(
                "conformal",
                [
                    "conformal",
                    "--predictions",
                    morgan,
                    "--truth",
                    tr_test,
                    "--endpoint",
                    "openadmet_logd",
                    "--alpha",
                    "0.2",
                    "--min-n",
                    "20",
                    "--outdir",
                    os.path.join(OUTD, "conformal"),
                ],
            )
        )

    # --- 3. conformal-class（真实 hERG 二分类留出） ---
    try:
        if not want("conformal_class"):
            raise StopIteration
        hp, ht = build_herg()
        res.append(
            run(
                "conformal_class",
                [
                    "conformal-class",
                    "--predictions",
                    hp,
                    "--truth",
                    ht,
                    "--endpoint",
                    "herg_external",
                    "--alpha",
                    "0.1",
                    "--outdir",
                    os.path.join(OUTD, "conformal_class"),
                ],
            )
        )
    except StopIteration:
        pass
    except Exception:
        traceback.print_exc()
        res.append(
            dict(step="conformal_class", rc=1, tail=traceback.format_exc()[-1500:])
        )

    # --- 4. ablate（真实多源 + 真实真值） ---
    if want("ablate"):
        res.append(
            run(
                "ablate",
                [
                    "ablate",
                    "--sources",
                    "%s=baseline_morgan:fingerprint_ml,%s=baseline_rdkit:descriptor_ml"
                    % (morgan, rdkit_p),
                    "--truth",
                    tr_test,
                    "--rules",
                    rules,
                    "--outdir",
                    os.path.join(OUTD, "ablate"),
                ],
            )
        )

    # --- 5. decision-value（真实 reliability + 真实真值） ---
    if want("decision_value"):
        res.append(
            run(
                "decision_value",
                [
                    "decision-value",
                    "--reliability",
                    rel_ext,
                    "--truth",
                    tr_test,
                    "--measurements",
                    merged,
                    "--rules",
                    rules,
                    "--budget",
                    "200",
                    "--cost-fp",
                    "5",
                    "--p-convert",
                    "0.6",
                    "--outdir",
                    os.path.join(OUTD, "decision_value"),
                ],
            )
        )

    # --- 6. prospect（时序留出：train 学 → test 裁） ---
    if want("prospect"):
        res.append(
            run(
                "prospect",
                [
                    "prospect",
                    "--measurements",
                    merged,
                    "--truth",
                    tr_test,
                    "--rules",
                    rules,
                    "--registry",
                    reg,
                    "--baseline",
                    "both",
                    "--early",
                    "OpenADMET train split 25265 行实测（早期）",
                    "--outdir",
                    os.path.join(OUTD, "prospect"),
                ],
            )
        )

    # --- 7. cross-class（两个真实化学空间） ---
    labs = "openadmet_druglike"
    rels = [rel_ext]
    if os.path.exists(PANEL_REL):
        rels.append(PANEL_REL)
        labs += ",panel_mixed30"
    if want("cross_class"):
        res.append(
            run(
                "cross_class",
                ["cross-class", "--reliability"]
                + rels
                + [
                    "--labels",
                    labs,
                    "--expected-high",
                    "panel_mixed30",
                    "--expected-low",
                    "openadmet_druglike",
                    "--prediction-note",
                    "预测：面板含高极性糖苷/多酚/大分子，域外源与单组端点更多，"
                    "弃权率应显著高于药物样 OpenADMET 空间",
                    "--outdir",
                    os.path.join(OUTD, "cross_class"),
                ],
            )
        )

    # --- 8. pred-shift（真实结构变体 vs 真实源间分歧） ---
    try:
        if not want("pred_shift"):
            raise StopIteration
        vp = build_variants()
        res.append(
            run(
                "pred_shift",
                [
                    "pred-shift",
                    "--variants",
                    vp,
                    "--source-shift",
                    os.path.join(ROOT, "run6", "srho", "source_rho_by_endpoint.csv"),
                    "--flip-threshold",
                    "0.5",
                    "--note",
                    "变体=acplan 的真实结构扰动（去立体/互变异构）；"
                    "源间参照=run6/srho 的两模型分歧",
                    "--outdir",
                    os.path.join(OUTD, "pred_shift"),
                ],
            )
        )
    except StopIteration:
        pass
    except Exception:
        traceback.print_exc()
        res.append(dict(step="pred_shift", rc=1, tail=traceback.format_exc()[-1500:]))

    # 合并写：`--only` 单跑一步时不能把之前的记录抹掉（面板跑批踩过同一个坑）
    sp = os.path.join(LEGS, "real_legs_summary.json")
    merged = {}
    if os.path.exists(sp):
        try:
            for r in json.load(io.open(sp, encoding="utf-8")):
                merged[r["step"]] = r
        except Exception:
            merged = {}
    for r in res:
        merged[r["step"]] = r
    with io.open(sp, "w", encoding="utf-8") as fh:
        json.dump(list(merged.values()), fh, ensure_ascii=False, indent=1)

    print("\n===== 汇总 =====")
    for r in res:
        print("  %-18s rc=%s" % (r["step"], r["rc"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
