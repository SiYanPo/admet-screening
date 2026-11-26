# -*- coding: utf-8 -*-
"""外源留出验证（post-cutoff external holdout）—— 黑 5 / B4 的可执行替代。

## 为什么用这个替代"OSF 前瞻预注册"
B4 要求"预注册时点**之后**发布的数据集"，本机无法完成：注册要账号、等待要时间。
但 B4 想排除的东西是明确的：**模型见过这些分子**。
可执行的等价措施是"**训练截止之后发表、且与训练集无近重复**的外部留出集"。
本脚本从 ChEMBL（当前库版本 ChEMBL_37，release 2026-05-01）取
**文献年份 ≥ 指定年**的 hERG IC50，再剔除与 TDC hERG 训练/测试集重复或近重复的分子，
用**只在 TDC 上训练过**的模型预测。

**报两个数，缺一不可**：
  ① `in_domain_reference`：train_val(523) 训练 → TDC test(132) 评估（同管道同超参）；
  ② `external`：train_val+test(655) 全量训练 → post-cutoff 评估。
②比①看到更多 TDC 数据，所以两者的 AUC 落差**不是**"训练量不足"，是骨架/分布差异。
只报②会被问"内部本来有多好"，只报①会被问"外部到底行不行"。

## 它与 B4 的差别（必须写在报告里，不得混同）
| 维度 | OSF 前瞻预注册 | 本脚本 |
|---|---|---|
| 时点 | 注册在前，数据在后 | 数据已存在，只是晚于训练集 |
| 抗选择性报告 | 强（分析计划锁定） | **弱**（我看到数据后才定阈值） |
| 抗数据泄漏 | 强 | 中（已剔除重复与近重复） |
据此，本脚本的结论只能表述为
"**post-cutoff 外源留出上的表现**"，**不得**表述为"前瞻验证通过"。

## 关键控制
- 剔除与 TDC hERG（train_val + test）**完全相同**的分子（canonical SMILES）；
- 再剔除与 TDC 任一分子 Tanimoto ≥ 0.9 的近重复（可关）；
- 标签定义与 TDC 对齐：pIC50 ≥ 5（IC50 ≤ 10 μM）记为 blocker；
- 同一分子多条活性取中位数，避免重复计权。

输出：out_ext/external/herg_holdout.json
"""
import argparse
import io
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rdkit import Chem, DataStructs, RDLogger                     # noqa: E402
from rdkit.Chem import AllChem                                     # noqa: E402
from sklearn.ensemble import RandomForestClassifier                # noqa: E402
from sklearn.metrics import roc_auc_score                          # noqa: E402

RDLogger.DisableLog("rdApp.*")

API = "https://www.ebi.ac.uk/chembl/api/data"
TARGET = "CHEMBL240"          # hERG
PIC50_CUT = 5.0               # IC50 ≤ 10 μM → blocker（与 TDC hERG 口径一致）


def _get(url, params, cache_path=None, timeout=60, retries=3):
    # 缓存优先：**先查缓存再 import requests**。
    # v4.4 修：旧版把 `import requests` 放在最前面，导致"完全离线但有缓存"的场景
    # （干净机、评审复现包）直接 ModuleNotFoundError——缓存形同虚设。
    if cache_path and os.path.exists(cache_path):
        return json.load(io.open(cache_path, encoding="utf-8"))
    import requests
    last = None
    for k in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            d = r.json()
            if cache_path:
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                with io.open(cache_path, "w", encoding="utf-8") as f:
                    f.write(json.dumps(d, ensure_ascii=False))
            return d
        except Exception as e:                                  # noqa: BLE001
            last = e
            time.sleep(3 * (k + 1))
    raise RuntimeError("ChEMBL 请求失败：%s (%s)" % (url, last))


LAST_FETCH_META = {}


def fetch_activities(min_year, max_pages, cache_dir, year_mode="local"):
    """取 ChEMBL hERG IC50 活动，并**在本地**按 `document_year` 做时间切分。

    ## 为什么必须本地过滤（v4.4 自查抓到的真实缺陷）

    首版把时间条件交给服务端：`document__year__gte=min_year`。**ChEMBL activity 端点
    并不保证应用该过滤**——实测 `>=2021` / `>=2022` / `>=2023` 三种取值返回的
    `total_count` **完全相同（19130）**，而落盘缓存里 `document_year` 从 1995 到 2025 都有，
    ≥2023 的只占 **9.6%**。

    后果很严重：称为 "post-cutoff 外源留出" 的那批分子（n=9443）**并不是 post-cutoff**，
    而是"ChEMBL_37 hERG IC50 全集（时间混合）"。这不是数字错，是**标签错**——
    而本包的整套认识论（红线 8：外源数字必须同句标注"非预注册前瞻"）就建立在这个标签上。

    故本函数改为：**服务端参数照发（无害），但一律在本地按 `document_year` 重新切一次**，
    并把 `requested_min_year / applied_min_year / n_before / n_after / year_source`
    写进 `LAST_FETCH_META`，由调用方落盘为证据。`year_mode="none"` 仅用于**复现旧数字**，
    任何对外材料不得使用。
    """
    acts = []
    offset = 0
    total = None
    for page in range(max_pages):
        params = {"target_chembl_id": TARGET, "standard_type": "IC50",
                  "document__year__gte": min_year, "limit": 1000,
                  "offset": offset}
        d = _get(API + "/activity.json", params,
                 os.path.join(cache_dir, "act_%d.json" % page))
        total = d["page_meta"]["total_count"]
        acts.extend(d["activities"])
        print("[ext] activities page %d: +%d (total=%d)"
              % (page, len(d["activities"]), total), flush=True)
        if len(acts) >= total or not d["activities"]:
            break
        offset += 1000

    n_before = len(acts)
    years = [a.get("document_year") for a in acts if isinstance(a.get("document_year"), int)]
    if year_mode == "local":
        kept = [a for a in acts
                if isinstance(a.get("document_year"), int)
                and a["document_year"] >= min_year]
        n_dropped_unknown = sum(1 for a in acts if not isinstance(a.get("document_year"), int))
        acts = kept
    else:
        n_dropped_unknown = 0
        if year_mode != "none":
            raise ValueError("year_mode 只能是 local / none，收到 %r" % (year_mode,))

    LAST_FETCH_META.clear()
    LAST_FETCH_META.update({
        "year_mode": year_mode,
        "requested_min_year": min_year,
        "applied_min_year": (min_year if year_mode == "local" else None),
        "year_source": "activity.document_year（本地过滤）" if year_mode == "local"
                       else "无（year_mode=none，仅用于复现旧数字）",
        "n_before_year_filter": n_before,
        "n_after_year_filter": len(acts),
        "n_dropped_year_unknown": n_dropped_unknown,
        "api_total_count": total,
        "server_side_filter_reliable": (len(acts) != n_before) or year_mode == "none",
        "cache_document_year_min": (min(years) if years else None),
        "cache_document_year_max": (max(years) if years else None),
        "caveat": ("ChEMBL activity 端点的 document__year__gte 实测**不可靠**"
                   "（>=2021/2022/2023 返回同一 total_count）；时间切分一律以本地过滤为准。"),
    })
    print("[ext] 年份过滤(%s)：%d → %d（丢弃无年份 %d）"
          % (year_mode, n_before, len(acts), n_dropped_unknown), flush=True)
    return acts, total


def to_molecules(ids, cache_dir, batch=25):
    """批量取 SMILES。返回 {chembl_id: smiles}。"""
    out = {}
    ids = sorted(ids)
    for i in range(0, len(ids), batch):
        chunk = ids[i:i + batch]
        params = {"molecule_chembl_id__in": ",".join(chunk), "limit": len(chunk)}
        key = os.path.join(cache_dir, "v2mol_%05d.json" % i)
        d = _get(API + "/molecule.json", params, key)
        for m in d.get("molecules", []):
            s = (m.get("molecule_structures") or {}).get("canonical_smiles")
            if s:
                out[m["molecule_chembl_id"]] = s
        print("[ext] molecules %d/%d" % (min(i + batch, len(ids)), len(ids)),
              flush=True)
    return out


def tdc_set(cache, name="hERG"):
    """TDC hERG 切分，返回 (train_val, test) 两组 (mols, y)。

    走 `adt.tdc_local`：优先官方 `tdc` 包，未安装则读本地缓存 CSV
    （缓存已在 out_ext/tdc_cache/admet_group/herg/ 下，无需联网）。

    **为什么不合并**：本脚本要报两个数——
      ① 域内参照：train_val 训练 → TDC test 评估；
      ② 外源：train_val+test 全量训练 → post-cutoff 评估。
    合并成一组就没法给①了，而"外源掉了多少"必须有个同管道的域内基准。
    """
    from adt.tdc_local import load_split
    d = load_split(cache, name)

    def _xy(df):
        mols, ys = [], []
        for _, r in df.iterrows():
            m = Chem.MolFromSmiles(str(r["Drug"]))
            if m is None:
                continue
            mols.append(m)
            ys.append(int(float(r["Y"])))
        return mols, np.array(ys, dtype=int)

    return _xy(d["train_val"]), _xy(d["test"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-year", type=int, default=2023, dest="min_year")
    ap.add_argument("--max-pages", type=int, default=20, dest="max_pages")
    ap.add_argument("--cache", default="out_ext/tdc_cache")
    ap.add_argument("--near-dup", type=float, default=0.9, dest="near_dup")
    ap.add_argument("--out", default="out_ext/external/herg_holdout.json")
    ap.add_argument("--year-mode", choices=("local", "none"), default="local",
                    dest="year_mode",
                    help="local=本地按 document_year 切分（默认，唯一可用于对外材料）")
    a = ap.parse_args(argv)
    cache_dir = "out_ext/external/cache"

    acts, total = fetch_activities(a.min_year, a.max_pages, cache_dir,
                                   year_mode=a.year_mode)

    # 活性记录本身自带 canonical_smiles，**不必**再走 molecule 批量查询。
    # （v4.2 的 to_molecules 用 molecule_chembl_id__in 批量取，返回 0 条：
    #  该过滤器的确切拼写依赖 API 版本，实测不可靠。此处直接用活性记录字段。）
    per_mol, smi = {}, {}
    n_cens, n_invalid, n_nosmi = 0, 0, 0
    for x in acts:
        cid = x.get("molecule_chembl_id")
        p = x.get("pchembl_value")
        s = x.get("canonical_smiles")
        if not cid:
            continue
        if x.get("standard_relation") not in (None, "="):
            n_cens += 1                       # 删失值（> / <）不进中位数
            continue
        if x.get("data_validity_comment"):
            n_invalid += 1                    # ChEMBL 自标的数据质量问题
            continue
        if not s:
            n_nosmi += 1
            continue
        if p in (None, ""):
            continue
        try:
            p = float(p)
        except (TypeError, ValueError):
            continue
        per_mol.setdefault(cid, []).append(p)
        smi[cid] = s
    print("[ext] 有 pChEMBL 值的分子：%d（活性记录 %d / 库中总计 %d；"
          "剔除删失 %d、无效 %d、无 SMILES %d）"
          % (len(per_mol), len(acts), total, n_cens, n_invalid, n_nosmi),
          flush=True)

    (mols_trv, y_trv), (mols_tst, y_tst) = tdc_set(a.cache)
    tdc_mols = mols_trv + mols_tst
    tdc_y = np.concatenate([y_trv, y_tst])
    tdc_smis = {Chem.MolToSmiles(m) for m in tdc_mols}
    tdc_fps = [AllChem.GetMorganFingerprintAsBitVect(m, 2, 2048) for m in tdc_mols]

    rows, dropped_exact, dropped_near = [], 0, 0
    for cid, ps in per_mol.items():
        s = smi.get(cid)
        if not s:
            continue
        m = Chem.MolFromSmiles(s)
        if m is None:
            continue
        can = Chem.MolToSmiles(m)
        if can in tdc_smis:
            dropped_exact += 1
            continue
        fp = AllChem.GetMorganFingerprintAsBitVect(m, 2, 2048)
        sims = DataStructs.BulkTanimotoSimilarity(fp, tdc_fps)
        if sims and max(sims) >= a.near_dup:
            dropped_near += 1
            continue
        med = float(np.median(ps))
        rows.append({"chembl_id": cid, "smiles": can, "pic50": med,
                     "y": int(med >= PIC50_CUT), "max_tdc_tanimoto": max(sims or [0])})
    print("[ext] 外源留出集：n=%d（剔除完全相同 %d、近重复 %d）"
          % (len(rows), dropped_exact, dropped_near), flush=True)
    if len(rows) < 50:
        raise SystemExit("外源留出集过小（n=%d），不足以评估" % len(rows))

    mols_ext = [Chem.MolFromSmiles(r["smiles"]) for r in rows]
    y_ext = np.array([r["y"] for r in rows])

    def _fp_matrix(ms):
        A = np.zeros((len(ms), 2048), dtype=np.int8)
        for i, m in enumerate(ms):
            DataStructs.ConvertToNumpyArray(
                AllChem.GetMorganFingerprintAsBitVect(m, 2, 2048), A[i])
        return A

    Xtrv = _fp_matrix(mols_trv)          # 域内参照：只用 train_val 训练
    Xtst = _fp_matrix(mols_tst)
    Xex = _fp_matrix(mols_ext)

    # ① 域内参照：train_val → test（同管道、同超参）
    ref = RandomForestClassifier(n_estimators=400, random_state=0, n_jobs=1)
    ref.fit(Xtrv, y_trv)
    p_ref = ref.predict_proba(Xtst)[:, 1]

    # ② 外源：train_val+test 全量训练 → post-cutoff
    #    **故意用更多的 TDC 数据**：如果外源仍然掉，掉得就不是"训练不足"。
    clf = RandomForestClassifier(n_estimators=400, random_state=0, n_jobs=1)
    clf.fit(np.vstack([Xtrv, Xtst]),
            np.concatenate([y_trv, y_tst]))
    p_ext = clf.predict_proba(Xex)[:, 1]
    pred = (p_ext >= 0.5).astype(int)

    def _m(y, p):
        tp = int(np.sum((y == 1) & (p == 1)))
        fn = int(np.sum((y == 1) & (p == 0)))
        tn = int(np.sum((y == 0) & (p == 0)))
        fp_ = int(np.sum((y == 0) & (p == 1)))
        return {"n": int(len(y)),
                "sensitivity": round(tp / (tp + fn), 3) if (tp + fn) else None,
                "specificity": round(tn / (tn + fp_), 3) if (tn + fp_) else None,
                "accuracy": round((tp + tn) / len(y), 3),
                "prevalence": round(float(y.mean()), 3)}

    payload = {
        "design": ("时间留出外源集（**不是**前瞻预注册，见脚本头表）；"
                   "时间切分一律以**本地** document_year 过滤为准"
                   "（服务端 document__year__gte 实测不生效，见 fetch_activities docstring）"),
        "source": {"api": API, "target": TARGET, "min_document_year": a.min_year,
                   "pchembl_cutoff": PIC50_CUT, "near_dup_exclusion": a.near_dup,
                   "year_mode": a.year_mode,
                   "year_filter": dict(getattr(sys.modules[__name__], "LAST_FETCH_META", {}))},
        "n_activities_seen": len(acts), "n_activities_total_available": total,
        "n_dropped_censored": n_cens,
        "n_dropped_invalid": n_invalid,
        "n_dropped_no_smiles": n_nosmi,
        "n_dropped_exact_duplicate": dropped_exact,
        "n_dropped_near_duplicate": dropped_near,
        "external": _m(y_ext, pred),
        "external_auc": (round(float(roc_auc_score(y_ext, p_ext)), 3)
                         if len(set(y_ext.tolist())) > 1 else None),
        "median_max_tanimoto_to_tdc": round(
            float(np.median([r["max_tdc_tanimoto"] for r in rows])), 3),
        "in_domain_reference": {
            "design": "train_val 训练 → TDC test 评估（同管道、同超参）",
            "n_train": int(len(y_trv)), "n_test": int(len(y_tst)),
            "metrics": _m(y_tst, (p_ref >= 0.5).astype(int)),
            "auc": (round(float(roc_auc_score(y_tst, p_ref)), 3)
                    if len(set(y_tst.tolist())) > 1 else None),
            "note": ("外源模型（②）用了 train_val+test **全部** TDC 数据训练，"
                     "比本参照模型（①）看到更多数据。因此 AUC 的落差"
                     "**不是**训练量不足造成的，是分布/骨架差异。"),
        },
        "caveat": ("阈值与分析口径在看到本数据后才确定，故不具前瞻性；"
                   "结论只能写'时间留出外源集上的表现'。"
                   "**禁止**把它写成 post-cutoff 前瞻/前瞻验证——本文件的时间切分是"
                   "按文献发表年做的**回溯式**切分。"),
    }

    # ---- 判别力 vs 阈值：把两件事拆开 ------------------------------------
    # 0.5 是训练集先验（TDC hERG 阳性 ~82%）下的工作点。外源集先验不同
    # （实测 ~68%），0.5 就不再是"平衡点"，直接用它会得到"几乎全判阳性"的
    # 假象——那是先验漂移，不是模型退化的新证据。所以必须另报两件事：
    #   ① 无阈值的判别力（AUC + bootstrap CI）；
    #   ② 先验匹配阈值（取 p 的 1−prevalence 分位）下的混淆矩阵。
    # 只有①才是"模型会不会排序"，②才是"这个阈值能不能搬"。
    if len(set(y_ext.tolist())) > 1:
        rng = np.random.default_rng(0)
        aucs = []
        for _ in range(1000):
            idx = rng.integers(0, len(y_ext), len(y_ext))
            yy = y_ext[idx]
            if len(set(yy.tolist())) < 2:
                continue
            aucs.append(roc_auc_score(yy, p_ext[idx]))
        payload["external_auc_ci95"] = [round(float(np.percentile(aucs, 2.5)), 3),
                                         round(float(np.percentile(aucs, 97.5)), 3)]

        prev = float(y_ext.mean())
        thr_matched = float(np.quantile(p_ext, 1.0 - prev))
        payload["prior_shift"] = {
            "train_positive_rate": round(float(np.mean(np.concatenate([y_trv, y_tst]))), 3),
            "external_positive_rate": round(prev, 3),
            "threshold_used": 0.5,
            "threshold_prior_matched": round(thr_matched, 3),
            "at_0.5": _m(y_ext, pred),
            "at_prior_matched": _m(y_ext, (p_ext >= thr_matched).astype(int)),
            "always_positive_accuracy": round(prev, 3),
            "note": None,   # 由数据决定，见下
        }
        ps = payload["prior_shift"]
        big_shift = abs(ps["train_positive_rate"] - prev) > 0.10
        if big_shift:
            ps["note"] = ("先验漂移 >0.10，0.5 阈值已不是平衡工作点；"
                          "此处的'几乎全判阳性'部分来自先验，不能全算模型退化。")
        else:
            ps["note"] = ("先验漂移 ≤0.10（%.3f → %.3f），'几乎全判阳性'**不能**归因于先验；"
                          "且换先验匹配阈值后 accuracy 反而更低 → 瓶颈是判别力本身，"
                          "不是阈值搬运。"
                          % (ps["train_positive_rate"], prev))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps(payload["external"], ensure_ascii=False), flush=True)
    print("[ext] AUC = %s  CI=%s"
          % (payload["external_auc"], payload.get("external_auc_ci95")), flush=True)
    if "prior_shift" in payload:
        ps = payload["prior_shift"]
        print("[ext] 先验漂移：train +%.3f → ext +%.3f；阈值 0.5 与先验匹配 %.3f"
              % (ps["train_positive_rate"], ps["external_positive_rate"],
                 ps["threshold_prior_matched"]), flush=True)
        print("[ext]   0.5:  %s" % json.dumps(ps["at_0.5"], ensure_ascii=False),
              flush=True)
        print("[ext]   匹配: %s"
              % json.dumps(ps["at_prior_matched"], ensure_ascii=False), flush=True)
    print("[ext] -> %s" % a.out, flush=True)


if __name__ == "__main__":
    main()
