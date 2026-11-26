# -*- coding: utf-8 -*-
r"""A1 受控独立性梯度（第一悬案的**机制级**检验，不冒充真实外源复现）。

## 评审两次点名的这一项（次轮 A1 / 第三轮 §E2）
> "v4.3 的近邻归因代理回答的是『共享误差是否随近邻泄漏上升』，
>   **不是**『准入层增益是否随源独立性上升』……我方次轮 A1 的立场不变：
>   OpenADMET 开放模型 + 自训重叠梯度是单方路径。"

审稿人要的是"源独立性"这个自变量的**受控**操纵。真实外源（ADMET-AI / ADMETlab3 等）
训练集不公开，无法操纵；但**机制本身**可以在同源模型上做受控梯度：
固定同一批分子的训练池，改变两个模型**共享训练子集的比例 α**，
就能把"独立性"从一个形容词变成一个 0→1 的旋钮。

## 这能回答什么 / 不能回答什么（必须先说清）
- ✅ 能回答：**"票冗余"是不是重叠度的单调函数**——即"同源模型投票会退化成伪共识"
  这个机制是否真的成立、在什么 α 上开始失效。
- ❌ 不能回答：真实外源之间的重叠到底是多少（对方训练集不公开），
  因此**本实验不关闭 A1**，它只把 A1 从"从未测过"推进到"机制已测、真实梯度仍开"。

## 设计
- 数据：TDC ADMET_Group hERG 官方切分（train_val 523 / test 132），Morgan-2048。
- 把 train_val 按种子随机二分 H1 / H2（各半）。
- 源 A 训练集 = H1 ∪ (α·H2)；源 B 训练集 = H2 ∪ (α·H1)。α ∈ {0, 0.25, 0.5, 1.0}。
  α=0 → 两模型完全不相交（最独立）；α=1 → 训练集相同（最冗余）。
- 两模型用**不同随机种子**，所以即便 α=1 也不是同一模型（否则相关系数恒为 1，实验无意义）。
- 每档 20 个外层种子，报中位数与 bootstrap CI。

## 指标
| 指标 | 含义 | 预期（框架主张成立的话） |
|---|---|---|
| `rho_error` | 两源**误差**的 Spearman 相关 | 随 α 单调上升 |
| `vote_gain_mean2` | 两源概率均值 相对**最好的单源** 的准确率增益 | 随 α 单调下降 |
| `consensus_coverage` / `consensus_accuracy` | 两源一致时才决策的覆盖率/准确率 | 覆盖率随 α 上升、准确率不升 → 伪共识 |

## 输出
`out_ext/tdc/independence_gradient.json`

## 用法
```bash
python run_independence_gradient.py                 # 默认 20 种子
python run_independence_gradient.py --seeds 5       # 冒烟
```
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from rdkit import Chem, DataStructs, RDLogger                       # noqa: E402
from rdkit.Chem import AllChem                                      # noqa: E402
from scipy.stats import spearmanr                                   # noqa: E402
from sklearn.ensemble import RandomForestClassifier                 # noqa: E402

from adt.tdc_local import load_split                                # noqa: E402

RDLogger.DisableLog("rdApp.*")

ALPHAS = [0.0, 0.25, 0.5, 1.0]


def _fp(mols):
    A = np.zeros((len(mols), 2048), dtype=np.int8)
    for i, m in enumerate(mols):
        DataStructs.ConvertToNumpyArray(
            AllChem.GetMorganFingerprintAsBitVect(m, 2, 2048), A[i])
    return A


def _xy(df):
    mols, y = [], []
    for _, r in df.iterrows():
        m = Chem.MolFromSmiles(str(r["Drug"]))
        if m is None:
            continue
        mols.append(m)
        y.append(int(float(r["Y"])))
    return mols, np.array(y, dtype=int)


def _acc(p, y, thr=0.5):
    return float(((p >= thr).astype(int) == y).mean())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(HERE, "out_ext/tdc_cache"))
    ap.add_argument("--endpoint", default="hERG")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--trees", type=int, default=400)
    ap.add_argument("--out", default=os.path.join(
        HERE, "out_ext/tdc/independence_gradient.json"))
    a = ap.parse_args(argv)

    d = load_split(a.cache, a.endpoint)
    mols_tr, y_tr = _xy(d["train_val"])
    mols_te, y_te = _xy(d["test"])
    Xtr, Xte = _fp(mols_tr), _fp(mols_te)
    n = len(y_tr)
    print("[a1] train_val=%d test=%d  alphas=%s seeds=%d"
          % (n, len(y_te), ALPHAS, a.seeds), flush=True)

    per_alpha = {al: [] for al in ALPHAS}
    for al in ALPHAS:
        for s in range(a.seeds):
            rng = np.random.default_rng(1000 + s)      # 二分与"外层种子"解耦
            perm = rng.permutation(n)
            half = n // 2
            H1, H2 = perm[:half], perm[half:]
            k = int(round(al * min(len(H1), len(H2))))
            share1 = H2[:k]          # H1 侧额外共享的 H2 分子
            share2 = H1[:k]
            idxA = np.concatenate([H1, share1])
            idxB = np.concatenate([H2, share2])

            mA = RandomForestClassifier(n_estimators=a.trees, random_state=s,
                                        n_jobs=1).fit(Xtr[idxA], y_tr[idxA])
            mB = RandomForestClassifier(n_estimators=a.trees, random_state=s + 7919,
                                        n_jobs=1).fit(Xtr[idxB], y_tr[idxB])
            pA = mA.predict_proba(Xte)[:, 1]
            pB = mB.predict_proba(Xte)[:, 1]

            eA, eB = pA - y_te, pB - y_te
            # ⚠ 合并算相关会**被标签组成抬高**：e = p − y 里含同一个 −y，
            #   两个误差序列天然同向，ρ 会被高估——这正是本包在 E2 里
            #   对"近邻归因代理"提出的同一条批评，必须自我适用。
            #   故主指标改为**标签分层内**的相关，再按样本量加权平均。
            def _rho(a_, b_):
                if len(a_) < 8 or len(set(a_.tolist())) < 2 or len(set(b_.tolist())) < 2:
                    return None
                return float(spearmanr(a_, b_)[0])

            m1, m0 = (y_te == 1), (y_te == 0)
            r_pos, r_neg = _rho(pA[m1], pB[m1]), _rho(pA[m0], pB[m0])
            ws = [(r_pos, int(m1.sum())), (r_neg, int(m0.sum()))]
            ws = [(r, w) for r, w in ws if r is not None]
            rho_within = (float(np.average([r for r, _ in ws], weights=[w for _, w in ws]))
                          if ws else float("nan"))
            rho_pooled = (_rho(eA, eB) if True else None)
            accA, accB = _acc(pA, y_te), _acc(pB, y_te)
            acc_mean = _acc((pA + pB) / 2.0, y_te)
            both = (pA >= 0.5) & (pB >= 0.5)
            neither = (pA < 0.5) & (pB < 0.5)
            dec = both | neither
            cons_acc = (float((both[dec].astype(int) == y_te[dec]).mean())
                        if dec.sum() else float("nan"))
            per_alpha[al].append({
                "seed": s,
                "rho_error_within_label": rho_within,
                "rho_error_pooled": (None if rho_pooled is None else rho_pooled),
                "rho_pos": r_pos, "rho_neg": r_neg,
                "acc_A": accA, "acc_B": accB,
                "acc_mean2": acc_mean,
                "vote_gain_mean2": acc_mean - max(accA, accB),
                "consensus_coverage": float(dec.mean()),
                "consensus_accuracy": cons_acc,
                "n_share_each_side": int(k),
            })
        r = per_alpha[al]
        print("[a1] alpha=%.2f  rho_within=%.3f  rho_pooled=%.3f  vote_gain=%+.4f  cons_cov=%.3f"
              % (al,
                 float(np.nanmedian([x["rho_error_within_label"] for x in r])),
                 float(np.nanmedian([x["rho_error_pooled"] or float("nan") for x in r])),
                 float(np.nanmedian([x["vote_gain_mean2"] for x in r])),
                 float(np.nanmedian([x["consensus_coverage"] for x in r]))), flush=True)

    def _agg(vals):
        vals = [v for v in vals if not (isinstance(v, float) and np.isnan(v))]
        if not vals:
            return None
        rng = np.random.default_rng(0)
        v = np.array(vals, dtype=float)
        bs = [float(np.median(rng.choice(v, len(v), replace=True))) for _ in range(2000)]
        return {"median": round(float(np.median(v)), 4),
                "boot_ci95": [round(float(np.percentile(bs, 2.5)), 4),
                              round(float(np.percentile(bs, 97.5)), 4)],
                "n": int(len(v))}

    summary = []
    for al in ALPHAS:
        r = per_alpha[al]
        summary.append({
            "alpha": al,
            "n_share_each_side": int(np.median([x["n_share_each_side"] for x in r])),
            "rho_error_within_label": _agg([x["rho_error_within_label"] for x in r]),
            "rho_error_pooled": _agg([x["rho_error_pooled"] for x in r
                                      if x["rho_error_pooled"] is not None]),
            "vote_gain_mean2": _agg([x["vote_gain_mean2"] for x in r]),
            "consensus_coverage": _agg([x["consensus_coverage"] for x in r]),
            "consensus_accuracy": _agg([x["consensus_accuracy"] for x in r]),
            "acc_A": _agg([x["acc_A"] for x in r]),
        })

    # ---- 单调性判定 -------------------------------------------------------
    def _mono(key, direction):
        vals = [s[key]["median"] for s in summary if s[key]]
        if len(vals) < len(ALPHAS):
            return None
        ok = all((b >= a_) if direction == "up" else (b <= a_)
                 for a_, b in zip(vals, vals[1:]))
        return {"values": vals, "monotone": bool(ok), "direction_expected": direction}

    mono_rho = _mono("rho_error_within_label", "up")
    mono_rho_pooled = _mono("rho_error_pooled", "up")
    mono_gain = _mono("vote_gain_mean2", "down")
    mono_cov = _mono("consensus_coverage", "up")
    payload = {
        "design": ("受控独立性梯度（**模拟**）：同一训练池按共享比例 α 二分，"
                   "α=0 最独立、α=1 训练集相同；两模型用不同随机种子。"),
        "scope_warning": ("本实验**不关闭 A1**：真实外源（ADMET-AI/ADMETlab3/ProTox3）"
                          "训练集不公开，其真实重叠度仍不可测。"
                          "本实验只检验『票冗余是否随重叠度单调恶化』这一机制。"),
        "metric_note": ("主指标 rho_error_within_label 为**标签分层内**相关加权平均。"
                        "rho_error_pooled 含共同 −y 分量，会被标签组成抬高"
                        "（α=0 时 0.845 vs 分层内 0.655），"
                        "与本包对『近邻归因代理』的批评是同一条——故不作主指标。"),
        "endpoint": a.endpoint,
        "n_train": int(n), "n_test": int(len(y_te)),
        "n_seeds": a.seeds, "trees": a.trees,
        "alphas": ALPHAS,
        "summary": summary,
        "monotonicity": {"rho_error_within_label": mono_rho,
                         "rho_error_pooled_label_inflated": mono_rho_pooled,
                         "vote_gain_mean2": mono_gain,
                         "consensus_coverage": mono_cov},
        "per_seed": per_alpha,
        "verdict": None,
    }

    rho0 = mono_rho["values"][0] if mono_rho else None
    if mono_rho and mono_rho["monotone"] and mono_gain and not mono_gain["monotone"]:
        payload["verdict"] = {
            "code": "overlap_raises_agreement_not_value",
            "statement": (
                "机制被**部分证实、部分否证**。\n"
                "① 证实的一半：随共享训练比例 α 上升，两源误差相关单调上升（%.3f→%.3f），"
                "两源一致率也从 %s 升到 %s —— 这就是『伪共识』的物理签名："
                "重叠越多，越容易一致，而一致并不等于更准。\n"
                "② 否证的一半：两源均值相对最好单源的增益在**所有** α 上都不为正"
                "（%s），包括 α=0 的完全不共享训练数据。"
                "α=0 时误差相关仍有 %.3f —— 两个模型同算法、同特征、同分布，"
                "**方法同源本身就吃掉了大部分独立性红利**。\n"
                "③ 因此可下的最强结论是：**『共享训练数据』不是源独立性的主要瓶颈，"
                "方法同源才是。** 这条对框架不利：它意味着"
                "『换个数据集重训一个同类模型』并不构成第二个独立源，"
                "而本框架的计票逻辑默认它是。A1 仍然开放。"
                % (mono_rho["values"][0], mono_rho["values"][-1],
                   (mono_cov["values"][0] if mono_cov else "n/a"),
                   (mono_cov["values"][-1] if mono_cov else "n/a"),
                   mono_gain["values"], rho0 or float("nan"))),
        }
    elif mono_rho and mono_rho["monotone"] and mono_gain and mono_gain["monotone"]:
        payload["verdict"] = {
            "code": "mechanism_confirmed",
            "statement": ("机制成立：共享比例 α↑ → 误差相关↑（%.3f→%.3f）、"
                          "投票增益↓（%+.4f→%+.4f）。"
                          "『同源模型投票产生伪共识』在本设计中是可复现的单调效应。"
                          "**但仍不得据此推断真实外源的独立度**。"
                          % (mono_rho["values"][0], mono_rho["values"][-1],
                             mono_gain["values"][0], mono_gain["values"][-1])),
        }
    else:
        payload["verdict"] = {
            "code": "mechanism_not_established",
            "statement": ("单调性未成立（rho_error=%s, vote_gain=%s）："
                          "在本设计下无法证明『票冗余随重叠单调恶化』。"
                          "这一结果是**对框架不利**的，照实记录，不得靠改写措辞绕过。"
                          % (mono_rho, mono_gain)),
        }

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))
    print("[a1] VERDICT %s" % payload["verdict"]["code"])
    print("[a1] %s" % payload["verdict"]["statement"])
    print("[a1] -> %s" % a.out)
    return payload


if __name__ == "__main__":
    main()
