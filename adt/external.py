# -*- coding: utf-8 -*-
"""工作包 B/G：外部公开数据接入（NPASS 3.0 / OpenADMET-ExpansionRx）。

背景
----
评审意见要求"中等规模公开基准 + 前瞻性盲测"，但此前 skill 只给协议、不分发数据。
本模块把两个公开数据集转成 skill 的三张契约表，并随包分发**可再分发的 curated 子集**：

  assets/external/openadmet/   OpenADMET-ExpansionRx（CC-BY-4.0）
      expansion_data_train.csv  5,326 行 × 9 终点（早期项目数据）
      expansion_data_test.csv   2,282 行 × 9 终点（后期/盲测数据）
  assets/external/npass/       NPASS 3.0 curated 子集（学术免费；见 PROVENANCE）
      npass_adme_subset.csv     实测 ADME 记录（按端点归一的子集）
      npass_structures_subset.csv
      npass_toxicity_subset.csv

设计纪律
--------
- **不改变原值**：raw 里的 ">" / "<" 只记 censor 标记，数值照录；不替用户插补。
- **单位显式**：每个端点带 unit；下游 `benchmark` / `calibration` 只认这里写的单位。
- **阈值是分析选择**：OpenADMET 的 PASS/FAIL 阈值在 `openadmet_rules()` 里集中声明，
  文档必须写"这是框架用于二分类基准的操作阈值，不是监管阈值"。
- **基线预测**：`baseline` 用 train split 训练 RDKit 描述符 / Morgan 指纹 Ridge，
  预测 test split；产物 source=`baseline_rdkit` / `baseline_morgan`，**不是外部工具**。

跑法
----
  python -m adt.cli external --dataset openadmet --data-dir assets/external/openadmet \
      --split test --outdir out_ext
  python -m adt.cli baseline --train-meas out_ext/measurements_train.csv \
      --test-meas out_ext/measurements_test.csv \
      --train-compounds out_ext/compounds_train.csv \
      --test-compounds out_ext/compounds_test.csv --method both --outdir out_ext
"""

import csv
import io
import json
import os

from . import schema

# ---- OpenADMET 列 -> 规范端点 -------------------------------------------------
# (csv 列名, 端点 id, 单位, shape, pass, fail, phys_range, window)
OPENADMET_COLS = [
    ("LogD", "openadmet_logd", "logD", "window", None, None, [-3.0, 8.0], [0.0, 4.0]),
    ("KSOL", "openadmet_ksol", "uM", "up", 10.0, 10.0, [0.0, 1e6], None),
    (
        "HLM CLint",
        "openadmet_hlm_clint",
        "mL/min/kg",
        "down",
        30.0,
        30.0,
        [0.0, 1e6],
        None,
    ),
    (
        "MLM CLint",
        "openadmet_mlm_clint",
        "mL/min/kg",
        "down",
        30.0,
        30.0,
        [0.0, 1e6],
        None,
    ),
    (
        "Caco-2 Permeability Papp A>B",
        "openadmet_caco2_papp",
        "1e-6 cm/s",
        "up",
        1.0,
        1.0,
        [0.0, 100.0],
        None,
    ),
    (
        "Caco-2 Permeability Efflux",
        "openadmet_caco2_efflux",
        "ratio",
        "down",
        2.0,
        2.0,
        [0.0, 1e4],
        None,
    ),
    ("MPPB", "openadmet_mppb", "% unbound", "up", 1.0, 1.0, [0.0, 100.0], None),
    ("MBPB", "openadmet_mbpb", "% unbound", "up", 1.0, 1.0, [0.0, 100.0], None),
    ("MGMB", "openadmet_mgmb", "% unbound", "up", 1.0, 1.0, [0.0, 100.0], None),
]

OPENADMET_DOI = "10.5281/zenodo.21504733"
OPENADMET_URL = "https://zenodo.org/records/21504733"
OPENADMET_LICENSE = "CC-BY-4.0"


def _fnum(v):
    """解析数值；返回 (value, censor)。'<0.1' -> (0.1,'<')；'1,351.1' -> 1351.1。"""
    if v is None:
        return None, ""
    s = str(v).strip().replace(",", "")
    if not s:
        return None, ""
    cens = ""
    if s[0] in "<>":
        cens = s[0]
        s = s[1:].strip()
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        x = float(s)
        if x != x or abs(x) == float("inf"):
            return None, cens
        return x, cens
    except ValueError:
        return None, cens


def openadmet_rules():
    """OpenADMET 端点的二分类规则（**分析阈值，不是监管阈值**）。"""
    out = {}
    for _col, ep, unit, shape, p, f, phys, win in OPENADMET_COLS:
        rule = dict(
            shape=shape,
            unit=unit,
            phys_range=phys,
            role="quality",
            require_sources=2,
            threshold_source="analysis_choice",
        )
        if p is not None:
            rule["pass"] = p
        if f is not None:
            rule["fail"] = f
        if win is not None:
            rule["window"] = win
        out[ep] = rule
    return out


def _smiles_info(smi):
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, rdMolDescriptors

        m = Chem.MolFromSmiles(smi or "")
        if m is None:
            return dict(formula="", inchikey="", mw="")
        return dict(
            formula=rdMolDescriptors.CalcMolFormula(m),
            inchikey=Chem.MolToInchiKey(m),
            mw=round(Descriptors.MolWt(m), 3),
        )
    except Exception:
        return dict(formula="", inchikey="", mw="")


def read_openadmet(path):
    """读 OpenADMET CSV -> [{compound_id, smiles, endpoint, value, unit, censor}]。"""
    rows = []
    with io.open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            cid = (r.get("Molecule Name") or "").strip()
            smi = (r.get("SMILES") or "").strip()
            if not cid:
                continue
            for col, ep, unit, *_ in OPENADMET_COLS:
                v, cens = _fnum(r.get(col))
                if v is None:
                    continue
                rows.append(
                    dict(
                        compound_id=cid,
                        smiles=smi,
                        endpoint=ep,
                        value=v,
                        unit=unit,
                        censor=cens,
                    )
                )
    return rows


def _write_csv(path, cols, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def write_openadmet(data_dir, outdir, split="test"):
    """把某个 split 写成 compounds/measurements/truth + rules + meta。"""
    from .reliability import _judge

    src = os.path.join(data_dir, "expansion_data_%s.csv" % split)
    if not os.path.exists(src):
        raise SystemExit("找不到 %s" % src)
    rows = read_openadmet(src)
    rules = openadmet_rules()

    # compounds（按首次出现顺序）
    seen = {}
    for r in rows:
        if r["compound_id"] not in seen:
            info = _smiles_info(r["smiles"])
            seen[r["compound_id"]] = dict(
                compound_id=r["compound_id"],
                input_smiles=r["smiles"],
                calc_smiles=r["smiles"],
                state_flag="unchanged",
                formula=info["formula"],
                inchikey=info["inchikey"],
                mw=info["mw"],
                note="OpenADMET-ExpansionRx %s" % split,
            )
    comps = list(seen.values())

    meas = []
    truth = []
    for r in rows:
        note = ("censor=%s" % r["censor"]) if r["censor"] else ""
        meas.append(
            dict(
                compound_id=r["compound_id"],
                endpoint=r["endpoint"],
                value=round(r["value"], 6),
                unit=r["unit"],
                source="openadmet_expansionrx",
                source_version="2026-01",
                retrieved_at=schema.now(),
                domain_flag="measured",
                uncertainty="",
                provenance_url=OPENADMET_URL,
                note=note,
            )
        )
        rd = rules.get(r["endpoint"]) or {}
        cls = _judge(r["value"], rd) or "UNDETERMINED"
        truth.append(
            dict(
                compound_id=r["compound_id"],
                endpoint=r["endpoint"],
                truth_value=round(r["value"], 6),
                truth_class=cls,
                source="OpenADMET-ExpansionRx",
                assay="ExpansionRx in vitro (%s)" % split,
                provenance_url=OPENADMET_URL,
                note=("unit=%s; %s" % (r["unit"], note)).strip("; "),
            )
        )

    os.makedirs(outdir, exist_ok=True)
    p_c = os.path.join(outdir, "compounds_%s.csv" % split)
    p_m = os.path.join(outdir, "measurements_%s.csv" % split)
    p_t = os.path.join(outdir, "truth_%s.csv" % split)
    p_r = os.path.join(outdir, "external_rules.yaml")
    schema.write_compounds(p_c, comps)
    schema.write_measurements_checked(p_m, meas)
    _write_csv(
        p_t,
        [
            "compound_id",
            "endpoint",
            "truth_value",
            "truth_class",
            "source",
            "assay",
            "provenance_url",
            "note",
        ],
        truth,
    )
    try:
        import yaml

        with io.open(p_r, "w", encoding="utf-8") as fh:
            yaml.safe_dump(
                {
                    "version": 1,
                    "threshold_source": "analysis_choice",
                    "endpoints": [dict(id=k, **v) for k, v in rules.items()],
                },
                fh,
                allow_unicode=True,
                sort_keys=False,
            )
    except Exception:
        p_r = ""
    meta = dict(
        dataset="openadmet_expansionrx",
        split=split,
        n_compounds=len(comps),
        n_measurements=len(meas),
        n_truth=len(truth),
        doi=OPENADMET_DOI,
        url=OPENADMET_URL,
        license=OPENADMET_LICENSE,
        note="PASS/FAIL 阈值为框架分析选择，不是监管阈值",
    )
    with io.open(
        os.path.join(outdir, "external_meta_%s.json" % split), "w", encoding="utf-8"
    ) as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    return dict(compounds=p_c, measurements=p_m, truth=p_t, rules=p_r, meta=meta)


# ---- 基线预测器（RDKit 描述符 / Morgan 指纹 + Ridge） ----------------------
def _descriptor_matrix(smiles):
    import numpy as np
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors

    out = []
    for smi in smiles:
        m = Chem.MolFromSmiles(smi or "")
        if m is None:
            out.append([0.0] * 12)
            continue
        out.append(
            [
                Descriptors.MolWt(m),
                Descriptors.MolLogP(m),
                Descriptors.TPSA(m),
                rdMolDescriptors.CalcNumHBD(m),
                rdMolDescriptors.CalcNumHBA(m),
                rdMolDescriptors.CalcNumRotatableBonds(m),
                rdMolDescriptors.CalcNumRings(m),
                rdMolDescriptors.CalcFractionCSP3(m),
                m.GetNumHeavyAtoms(),
                rdMolDescriptors.CalcNumAromaticRings(m),
                rdMolDescriptors.CalcNumAliphaticRings(m),
                Descriptors.BalabanJ(m),
            ]
        )
    X = np.asarray(out, dtype=float)
    X[~np.isfinite(X)] = 0.0
    return X


def _morgan_matrix(smiles, n_bits=2048, radius=2):
    import numpy as np
    from rdkit import Chem
    from rdkit.Chem import AllChem

    out = []
    for smi in smiles:
        m = Chem.MolFromSmiles(smi or "")
        if m is None:
            out.append([0] * n_bits)
            continue
        fp = AllChem.GetMorganFingerprintAsBitVect(m, radius, nBits=n_bits)
        arr = np.zeros((n_bits,), dtype=float)
        for i in fp.GetOnBits():
            arr[i] = 1.0
        out.append(arr.tolist())
    return np.asarray(out, dtype=float)


def oriented_score(value, rule):
    """把原始预测值转成"风险分数"（越高 = 越可能 FAIL）。

    benchmark 的正类是 FAIL/有毒；但部分端点是"越高越好"（KSOL、Caco-2 Papp、
    % unbound），原始预测值与风险方向相反。**不翻转会让 AUROC 系统性 <0.5**
    （实测 RDKit 基线 Caco-2 Papp 0.272、KSOL 0.305、MGMB 0.196）。
    """
    shape = (rule or {}).get("shape", "down")
    v = float(value)
    if shape == "up":
        return -v
    if shape == "window":
        lo, hi = (rule or {}).get("window", [-1e9, 1e9])
        if v < lo:
            return lo - v
        if v > hi:
            return v - hi
        return 0.0
    return v


def _read_long(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _compound_smiles(path):
    out = {}
    with io.open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            out[r["compound_id"]] = r.get("calc_smiles") or r.get("smiles") or ""
    return out


def fit_predict(
    train_meas,
    test_meas,
    train_compounds,
    test_compounds,
    method="rdkit",
    min_train=20,
    alpha=1.0,
):
    """对每个端点训练 Ridge，返回 test 预测行（长表）。

    性能：描述符/指纹矩阵**每 split 只算一次**，再按端点切片；
    否则 9 个端点会把同一批 SMILES 重复解析 9 次（实测会超时）。
    """
    import numpy as np
    from sklearn.linear_model import Ridge

    train = _read_long(train_meas)
    test = _read_long(test_meas)
    tr_smi = _compound_smiles(train_compounds)
    te_smi = _compound_smiles(test_compounds)

    by_ep_train = {}
    for r in train:
        v = _fnum(r.get("value"))[0]
        if v is None or r.get("compound_id") not in tr_smi:
            continue
        by_ep_train.setdefault(r["endpoint"], []).append(
            (r["compound_id"], v, r.get("unit", ""))
        )
    test_cids = sorted({r["compound_id"] for r in test if r["compound_id"] in te_smi})
    train_cids = sorted({r["compound_id"] for r in train if r["compound_id"] in tr_smi})
    if not test_cids or not train_cids:
        return []

    # 一次性矩阵
    smi_tr_all = [tr_smi[c] for c in train_cids]
    smi_te_all = [te_smi[c] for c in test_cids]
    if method == "morgan":
        Xtr_all = _morgan_matrix(smi_tr_all)
        Xte_all = _morgan_matrix(smi_te_all)
    else:
        Xtr_all = _descriptor_matrix(smi_tr_all)
        Xte_all = _descriptor_matrix(smi_te_all)
    idx_tr = {c: i for i, c in enumerate(train_cids)}

    out = []
    for ep, recs in sorted(by_ep_train.items()):
        if len(recs) < min_train:
            continue
        rows_idx, y = [], []
        for cid, v, _u in recs:
            if cid in idx_tr:
                rows_idx.append(idx_tr[cid])
                y.append(v)
        if len(y) < min_train:
            continue
        Xtr = Xtr_all[rows_idx]
        y = np.asarray(y, dtype=float)
        model = Ridge(alpha=alpha)
        model.fit(Xtr, y)
        pred = model.predict(Xte_all)
        unit = recs[0][2]
        for cid, p in zip(test_cids, pred):
            out.append(
                dict(
                    compound_id=cid,
                    endpoint=ep,
                    value=round(float(p), 6),
                    unit=unit,
                    source="baseline_%s" % method,
                    source_version="1.0",
                    retrieved_at=schema.now(),
                    domain_flag="predicted",
                    uncertainty="",
                    provenance_url="",
                    note="Ridge trained on train split n=%d" % len(y),
                )
            )
    return out


def write_baseline(
    train_meas,
    test_meas,
    train_compounds,
    test_compounds,
    outdir,
    method="rdkit",
    rules=None,
):
    rows = fit_predict(
        train_meas, test_meas, train_compounds, test_compounds, method=method
    )
    if not rows:
        raise SystemExit("[baseline] 没有可训练的端点（检查 split/端点重叠）")
    p = os.path.join(outdir, "measurements_baseline_%s.csv" % method)
    schema.write_measurements_checked(p, rows)
    # 风险方向对齐版：benchmark/selective 用这一份
    rules = rules or openadmet_rules()
    risk = []
    for r in rows:
        s = oriented_score(r["value"], rules.get(r["endpoint"]))
        rr = dict(r)
        rr["value"] = round(s, 6)
        rr["unit"] = "risk_score"
        rr["note"] = ((r.get("note") or "") + " | oriented risk score").strip(" |")
        risk.append(rr)
    p2 = os.path.join(outdir, "measurements_baseline_%s_risk.csv" % method)
    schema.write_measurements_checked(p2, risk)
    return p, p2, len(rows)


def _npass_rules_clean():
    """_judge 只认 pass/fail 键，这里做一次显式构造。"""
    return {
        "npass_ld50_rat": dict(
            shape="up",
            unit="mg/kg",
            **{"pass": 300.0, "fail": 300.0},
            phys_range=[0.0, 1e6],
            role="quality",
            require_sources=2,
            threshold_source="analysis_choice",
        ),
        "npass_ppb_bound": dict(
            shape="down",
            unit="%",
            **{"pass": 90.0, "fail": 90.0},
            phys_range=[0.0, 100.0],
            role="reference",
        ),
        "npass_logd": dict(
            shape="window",
            unit="logD",
            window=[0.0, 4.0],
            phys_range=[-5.0, 10.0],
            role="reference",
        ),
        "npass_clearance": dict(
            shape="down",
            unit="uL/min",
            **{"pass": 100.0, "fail": 100.0},
            phys_range=[0.0, 1e6],
            role="reference",
        ),
    }


def write_npass(data_dir, outdir):
    """NPASS curated 子集 -> compounds/measurements/truth（LD50 70/30 确定性切分）。"""
    import hashlib
    from .reliability import _judge

    p_ld = os.path.join(data_dir, "npass_tox_ld50_rat.csv")
    if not os.path.exists(p_ld):
        raise SystemExit("找不到 %s（先运行 examples/extract_npass.py）" % p_ld)
    rows = list(csv.DictReader(io.open(p_ld, encoding="utf-8-sig")))
    rules = _npass_rules_clean()

    comps = {}
    for r in rows:
        smi = (r.get("smiles") or "").strip()
        if not smi:
            continue
        info = _smiles_info(smi)
        comps[r["np_id"]] = dict(
            compound_id=r["np_id"],
            input_smiles=smi,
            calc_smiles=smi,
            state_flag="unchanged",
            formula=info["formula"],
            inchikey=info["inchikey"] or r.get("inchikey", ""),
            mw=info["mw"],
            note="NPASS 3.0 curated LD50 subset",
        )

    def is_train(np_id):
        h = int(hashlib.md5(np_id.encode("utf-8")).hexdigest(), 16)
        return (h % 10) < 7

    os.makedirs(outdir, exist_ok=True)
    counts = {}
    for split, want_train in (("train", True), ("test", False)):
        sel = [
            r
            for r in rows
            if r["np_id"] in comps and is_train(r["np_id"]) == want_train
        ]
        meas, truth = [], []
        for r in sel:
            v = _fnum(r.get("ld50_median_mg_kg"))[0]
            if v is None:
                continue
            note = "n_records=%s; min=%s; max=%s" % (
                r.get("n_records", ""),
                r.get("ld50_min", ""),
                r.get("ld50_max", ""),
            )
            meas.append(
                dict(
                    compound_id=r["np_id"],
                    endpoint="npass_ld50_rat",
                    value=round(v, 6),
                    unit="mg/kg",
                    source="npass3",
                    source_version="3.0",
                    retrieved_at=schema.now(),
                    domain_flag="measured",
                    uncertainty="",
                    provenance_url="https://bidd.group/NPASS/index.php",
                    note=note,
                )
            )
            cls = _judge(v, rules["npass_ld50_rat"]) or "UNDETERMINED"
            truth.append(
                dict(
                    compound_id=r["np_id"],
                    endpoint="npass_ld50_rat",
                    truth_value=round(v, 6),
                    truth_class=cls,
                    source="NPASS 3.0",
                    assay="Rattus norvegicus LD50 (mg/kg), median per compound",
                    provenance_url="https://bidd.group/NPASS/index.php",
                    note=note,
                )
            )
        csel = [comps[r["np_id"]] for r in sel if r["np_id"] in comps]
        pc = os.path.join(outdir, "compounds_%s.csv" % split)
        pm = os.path.join(outdir, "measurements_%s.csv" % split)
        pt = os.path.join(outdir, "truth_%s.csv" % split)
        schema.write_compounds(pc, csel)
        schema.write_measurements_checked(pm, meas)
        _write_csv(
            pt,
            [
                "compound_id",
                "endpoint",
                "truth_value",
                "truth_class",
                "source",
                "assay",
                "provenance_url",
                "note",
            ],
            truth,
        )
        counts[split] = dict(
            compounds=len(csel), measurements=len(meas), truth=len(truth)
        )

    # ADME 子集（参照端点，不进 LD50 基准）
    p_adme = os.path.join(data_dir, "npass_adme_subset.csv")
    adme_rows = (
        list(csv.DictReader(io.open(p_adme, encoding="utf-8-sig")))
        if os.path.exists(p_adme)
        else []
    )
    adme_meas = []
    for r in adme_rows:
        v = _fnum(r.get("value"))[0]
        if v is None or not r.get("smiles"):
            continue
        adme_meas.append(
            dict(
                compound_id=r["np_id"],
                endpoint=r["endpoint"],
                value=round(v, 6),
                unit=r.get("unit", ""),
                source="npass3",
                source_version="3.0",
                retrieved_at=schema.now(),
                domain_flag="measured",
                uncertainty="",
                provenance_url="https://bidd.group/NPASS/index.php",
                note="activity_type=%s; organism=%s"
                % (r.get("activity_type", ""), r.get("organism", "")),
            )
        )
    p_am = os.path.join(outdir, "measurements_adme.csv")
    if adme_meas:
        schema.write_measurements_checked(p_am, adme_meas)

    p_r = os.path.join(outdir, "npass_rules.yaml")
    try:
        import yaml

        with io.open(p_r, "w", encoding="utf-8") as fh:
            yaml.safe_dump(
                {
                    "version": 1,
                    "threshold_source": "analysis_choice",
                    "endpoints": [dict(id=k, **v) for k, v in rules.items()],
                },
                fh,
                allow_unicode=True,
                sort_keys=False,
            )
    except Exception:
        p_r = ""

    meta = dict(
        dataset="NPASS 3.0 curated",
        source_url="https://bidd.group/NPASS/index.php",
        license_note="academic/non-commercial; cite Lin et al. NAR 2026",
        split_rule="md5(np_id)%10<7 -> train",
        counts=counts,
        n_adme=len(adme_meas),
        threshold="LD50 300 mg/kg (analysis choice)",
    )
    with io.open(
        os.path.join(outdir, "external_meta_npass.json"), "w", encoding="utf-8"
    ) as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    return dict(
        compounds=os.path.join(outdir, "compounds_test.csv"),
        measurements=os.path.join(outdir, "measurements_test.csv"),
        truth=os.path.join(outdir, "truth_test.csv"),
        rules=p_r,
        meta=meta,
    )
