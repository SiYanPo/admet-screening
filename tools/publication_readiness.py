# -*- coding: utf-8 -*-
"""投稿就绪度审计：把"能不能投高分刊"从主观判断变成可复核的检查表。

设计原则
--------
1. **每条检查都读真实文件**，读不到就是 GAP，不做"应该没问题"的推断。
2. 权重与期刊档位的映射写在 `TIER_RULES` 里，可被审稿人质疑、可被修改，
   而不是藏在某段散文里。
3. 输出同时给"现在能投什么"与"要投 X 档还差哪几条"，避免"很接近了"这种空话。

运行：python tools/publication_readiness.py [--json out.json]
退出码：0 = 无 blocker GAP；2 = 存在 blocker GAP（不阻止阅读，便于 CI 用）
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 期刊档位规则：某档要求这些 check id 全部 PASS
TIER_RULES = [
    (
        "IF≥10（Nat 子刊 / Nat Commun / Sci Adv 级）",
        [
            "A1_prereg_anchor",
            "A2_prospective_window",
            "B2_external_holdout",
            "B3_wetlab_anchor",
            "C3_metric_completeness",
            "E3_sota_baseline",
            "C2_ci_reported",
        ],
    ),
    (
        "IF 6–9（J Cheminform / Digital Discovery / Brief Bioinform）",
        [
            "A2_prospective_window",
            "B1_estimand_cards",
            "C2_ci_reported",
            "D1_container",
            "D2_one_command_verify",
            "E1_stage1_draft",
        ],
    ),
    (
        "IF 4–6（JCIM / Mol Inform / J Comput Aided Mol Des）",
        [
            "B1_estimand_cards",
            "D3_lock",
            "E1_stage1_draft",
        ],
    ),
]


def _p(*parts):
    return os.path.join(ROOT, *parts)


def _read(path):
    try:
        return io.open(path, encoding="utf-8", errors="replace").read()
    except Exception:  # noqa: BLE001
        return ""


def _item(cid, name, status, weight, evidence, action=""):
    return dict(
        id=cid,
        name=name,
        status=status,
        weight=weight,
        evidence=evidence,
        action=action,
    )


# ---------------------------------------------------------------- A 诚信
def check_A1():
    log = _p("prereg", "prereg.jsonl")
    if not os.path.isfile(log):
        return _item(
            "A1_prereg_anchor",
            "预注册第三方锚定（claim_allowed）",
            "GAP",
            3,
            "prereg/prereg.jsonl 不存在",
            "OSF 恢复后 osf_register2.py + tools/prereg_anchor_stage1.py",
        )
    from adt.prereg import Prereg

    st = Prereg(log).anchor_status()
    if st.get("claim_allowed"):
        return _item(
            "A1_prereg_anchor",
            "预注册第三方锚定（claim_allowed）",
            "PASS",
            3,
            "registry=%s url=%s" % (st.get("registry"), st.get("url")),
        )
    return _item(
        "A1_prereg_anchor",
        "预注册第三方锚定（claim_allowed）",
        "GAP",
        3,
        "anchored=%s post_hoc=%s" % (st.get("anchored"), st.get("post_hoc_anchor")),
        "材料只能写『待锚定』；不得声称已预注册",
    )


def check_A2():
    log = _p("prereg", "prereg.jsonl")
    win = None
    if os.path.isfile(log):
        from adt.prereg import Prereg

        win = Prereg(log).temporal_window_declared()
    if win:
        return _item(
            "A2_prospective_window",
            "前瞻数据时间窗（min(data_ts)>anchor）",
            "PASS",
            3,
            json.dumps(win, ensure_ascii=False)[:160],
        )
    return _item(
        "A2_prospective_window",
        "前瞻数据时间窗（min(data_ts)>anchor）",
        "GAP",
        3,
        "链上无 prospective_data_window 声明（能力已实现：Prereg.temporal_validity）",
        "register_criteria(..., prospective_data_window={...}) 后跑 prereg-status --data-timestamps",
    )


def check_A3():
    """失败即结论：预注册文本里必须有"负结果照发"的可执行条款。

    判定不靠单一字面量（历史上同一概念有"失败即结论/失败判据/negative result"多种写法），
    而看三件事是否同时成立：①有失败判据；②明确负结果仍发表；③禁止事后换端点/加样本。
    """
    txt = _read(_p("PREREG_STAGE1_PACKAGE.md")) + _read(
        _p("references", "PREREG_ANCHORING_CHECKLIST.md")
    )
    c1 = ("失败判据" in txt) or ("failure criteria" in txt.lower())
    c2 = ("负结果" in txt) or ("negative result" in txt.lower())
    c3 = (
        ("端点替换" in txt)
        or ("sample top-up" in txt.lower())
        or ("不做事后加样" in txt)
    )
    ok = c1 and c2 and c3
    return _item(
        "A3_failure_clause",
        "失败即结论条款已登记",
        "PASS" if ok else "GAP",
        2,
        "失败判据=%s 负结果照发=%s 禁止事后调参=%s" % (c1, c2, c3),
        "" if ok else "在预注册文本补齐三条",
    )


# ---------------------------------------------------------------- B 数据
def check_B1():
    card = _p("references", "ENDPOINT_ESTIMAND_CARDS.yaml")
    txt = _read(card)
    if not txt:
        return _item(
            "B1_estimand_cards", "端点 estimand 绑定卡（≥3 端点）", "GAP", 3, "卡缺失"
        )
    try:
        import yaml

        doc = yaml.safe_load(txt) or {}
        eps = doc.get("endpoints") or {}
        n = len(eps)
        bad = [
            k
            for k, v in eps.items()
            if str((v or {}).get("estimand_status", "")).upper().startswith("NOT")
        ]
        status = "PASS" if n >= 3 else "GAP"
        return _item(
            "B1_estimand_cards",
            "端点 estimand 绑定卡（≥3 端点）",
            status,
            3,
            "%d 端点；未绑定/部分：%s" % (n, bad or "无"),
            "" if status == "PASS" else "补端点卡",
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            "B1_estimand_cards",
            "端点 estimand 绑定卡（≥3 端点）",
            "GAP",
            3,
            "解析失败 %r" % exc,
        )


def check_B2():
    """独立外部 holdout 必须有**数据产物**，不能拿"纪律文档"充数。

    历史上出现过把 strategy 文档当成证据的先例（见 07_case_lessons C51），
    故此处只认 .csv/.json/.parquet/.npz 之类可被重新计算的产物。
    """
    exts = (".csv", ".json", ".parquet", ".npz", ".tsv")
    cands = [
        p
        for p in glob.glob(_p("out_ext", "**", "*holdout*"), recursive=True)
        + glob.glob(_p("out_ext", "**", "*external*"), recursive=True)
        + glob.glob(_p("out_ext", "external", "**", "*"), recursive=True)
        + glob.glob(_p("assets", "external", "**", "*"), recursive=True)
        if p.lower().endswith(exts)
    ]
    # assets/external 是"外部数据集"，但不等于"独立 holdout"；要求名字里带 holdout/blind
    strong = [
        p
        for p in cands
        if any(
            tok in os.path.basename(p).lower()
            for tok in ("holdout", "blind", "independent", "dilirank")
        )
    ]
    if strong:
        return _item(
            "B2_external_holdout",
            "独立外部队列（未参与开发）",
            "PASS",
            3,
            os.path.relpath(strong[0], ROOT),
        )
    return _item(
        "B2_external_holdout",
        "独立外部队列（未参与开发）",
        "GAP",
        3,
        "无 holdout/blind/independent 数据产物（out_ext/tdc 同族重采样不算独立队列；纪律文档也不算）",
        "需第三方数据集（不同实验室/分布）+ 冻结预测输出 + 明确不参与调参的声明",
    )


def check_B3():
    txt = _read(_p("references", "ENDPOINT_ESTIMAND_CARDS.yaml"))
    bound = re.findall(r"estimand_status:\s*\"?(bound|BOUND)", txt)
    wet = ("膜片钳" in txt) or ("IC50" in txt) or ("体外实测" in txt)
    # 有湿实验描述不等于有湿实验数据；用"是否有实测产物"判定
    wet_files = glob.glob(_p("out_ext", "**", "*patch*"), recursive=True) + glob.glob(
        _p("inputs", "**", "*wetlab*"), recursive=True
    )
    ok = bool(bound) and bool(wet_files)
    return _item(
        "B3_wetlab_anchor",
        "至少一个端点的湿实验金标准",
        "PASS" if ok else "GAP",
        3,
        "estimand_status=bound 条目 %d；湿实验产物 %d 个"
        % (len(bound), len(wet_files)),
        "" if ok else "需湿实验（膜片钳 IC50 等）或与实验组合作，纯 in-silico 无法闭合",
    )


def check_B4():
    p = _p("DATA_MANIFEST.json")
    if not os.path.isfile(p):
        return _item(
            "B4_data_manifest",
            "数据清单（SHA256+来源+许可）",
            "GAP",
            2,
            "缺 DATA_MANIFEST.json",
        )
    try:
        d = json.load(io.open(p, encoding="utf-8"))
        files = d.get("files") or d.get("assets") or []
        n = len(files) if isinstance(files, list) else len(files)
        return _item(
            "B4_data_manifest",
            "数据清单（SHA256+来源+许可）",
            "PASS" if n else "GAP",
            2,
            "%d 条资产" % n,
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            "B4_data_manifest",
            "数据清单（SHA256+来源+许可）",
            "GAP",
            2,
            "解析失败 %r" % exc,
        )


# ---------------------------------------------------------------- C 统计
def check_C1():
    try:
        from adt import paired_stats

        has = all(hasattr(paired_stats, f) for f in ("delong", "mcnemar"))
        holm = any("holm" in n.lower() for n in dir(paired_stats))
        ok = has and holm
    except Exception:  # noqa: BLE001
        ok = False
    return _item(
        "C1_paired_stats",
        "配对统计（DeLong/McNemar/Holm）",
        "PASS" if ok else "GAP",
        2,
        "adt/paired_stats.py 函数齐备=%s" % ok,
    )


def check_C2():
    """主结果是否带区间：在 JSON 结构里找 CI 字段（不是全文搜字符串）。

    `out_keystone_v43/results.json` 的每行带 ci95（20 seeds × 策略 × 端点），
    之前的实现只找 "lower"/"lo" 字面量，把它误判成 GAP —— 这类"检查器自身的假阴性"
    和假阳性一样有害，故改为结构判定。
    """
    CI_KEYS = {
        "boot_ci95",
        "ci95",
        "ci_low",
        "ci_high",
        "ci_lo",
        "ci_hi",
        "lower",
        "upper",
        "ci95_low",
        "ci95_high",
        "ratio_ci95",
    }
    hits = []
    for p in glob.glob(_p("out_keystone_v43", "**", "*.json"), recursive=True):
        keys = set()

        def walk(o, acc):
            if isinstance(o, dict):
                for k, v in o.items():
                    acc.add(str(k).lower())
                    walk(v, acc)
            elif isinstance(o, list):
                for v in o[:60]:
                    walk(v, acc)

        try:
            walk(json.load(io.open(p, encoding="utf-8")), keys)
        except Exception:  # noqa: BLE001
            continue
        if keys & CI_KEYS:
            hits.append(os.path.relpath(p, ROOT))
    if hits:
        return _item(
            "C2_ci_reported", "主结果带 bootstrap CI", "PASS", 3, "、".join(hits[:2])
        )
    return _item(
        "C2_ci_reported",
        "主结果带 bootstrap CI",
        "GAP",
        3,
        "结构化结果里未见 CI 字段",
        "对每个策略×端点补 B=10000 配对 bootstrap",
    )


def check_C3():
    txt = _read(_p("adt", "benchmark.py")).lower()
    need = ["auroc", "auprc", "mcc", "ece", "brier"]
    missing = [m for m in need if m not in txt]
    ok = not missing
    return _item(
        "C3_metric_completeness",
        "指标齐备（AUROC/AUPRC/MCC/ECE/Brier）",
        "PASS" if ok else "GAP",
        3,
        "缺：%s" % (missing or "无"),
        "" if ok else "补 %s" % missing,
    )


def check_C4():
    """阈值敏感性：只认 knn / ratio-margin 两类真产物，不把审计报告自身当证据。"""
    want = ("knn_threshold_sensitivity.json", "ratio_margin_sensitivity.json")
    sens = [
        p
        for p in glob.glob(_p("out_sensitivity", "*.json"))
        if os.path.basename(p) in want
    ]
    return _item(
        "C4_threshold_sensitivity",
        "阈值敏感性已实测",
        "PASS" if len(sens) >= 2 else "GAP",
        2,
        "、".join(os.path.basename(x) for x in sens) or "无",
        (
            ""
            if len(sens) >= 2
            else "跑 adt.knn_sensitivity 与 tools/ratio_margin_sensitivity.py"
        ),
    )


# ---------------------------------------------------------------- D 复现
def check_D1():
    p = _p("DOCKER_DIGEST")
    if not os.path.isfile(p):
        return _item("D1_container", "容器 digest", "GAP", 2, "缺 DOCKER_DIGEST")
    try:
        d = json.load(io.open(p, encoding="utf-8"))
        img = (d.get("image") or {}).get("image_id")
    except Exception:  # noqa: BLE001
        img = None
    return _item(
        "D1_container", "容器 digest", "PASS" if img else "GAP", 2, str(img)[:40]
    )


def check_D2():
    cands = [_p("tools", "verify_all.py"), _p("bootstrap.py")]
    hit = [c for c in cands if os.path.isfile(c)]
    return _item(
        "D2_one_command_verify",
        "一条命令复现（verify_all/bootstrap）",
        "PASS" if hit else "GAP",
        2,
        "、".join(os.path.basename(h) for h in hit) or "无",
    )


def check_D3():
    ok = os.path.isfile(_p("requirements.lock"))
    return _item(
        "D3_lock",
        "精确依赖锁",
        "PASS" if ok else "GAP",
        1,
        "requirements.lock" if ok else "缺失",
    )


# ---------------------------------------------------------------- E 稿件
def check_E1():
    hits = sorted(glob.glob(_p("PAPER_STAGE1*.md")))
    return _item(
        "E1_stage1_draft",
        "Stage 1 稿（引言+假设+方法）",
        "PASS" if hits else "GAP",
        2,
        os.path.basename(hits[-1]) if hits else "无",
    )


def check_E3():
    scan = _read(_p("references", "PRIOR_ART_2026_SCAN.md"))
    prior = bool(scan.strip())
    # SOTA 基线比较：需要外部基线产出的数值对照，而不只是文献列表
    base = (
        glob.glob(_p("out_ext", "**", "*baseline*"), recursive=True)
        + glob.glob(_p("out_baseline*"), recursive=True)
        + glob.glob(_p("out", "**", "*baseline*"), recursive=True)
    )
    ok = prior and bool(base)
    return _item(
        "E3_sota_baseline",
        "SOTA 基线数值对照（非仅文献列表）",
        "PASS" if ok else "GAP",
        3,
        "prior-art 扫描=%s；基线产物=%d" % (prior, len(base)),
        "" if ok else "在同一划分上跑 ADMET-AI/Chemprop 等公开基线并给 CI",
    )


def check_E2():
    txt = _read(_p("references", "PAPER_SKELETON_v4.4.md"))
    n_block = txt.count("⛔") + txt.count("待补")
    return _item(
        "E2_figure_inventory",
        "图表清单无待补占位",
        "PASS" if (txt and n_block == 0) else "GAP",
        2,
        "占位/待补 %d 处" % n_block,
        "" if n_block == 0 else "补齐或缺图声明",
    )


CHECKS = [
    check_A1,
    check_A2,
    check_A3,
    check_B1,
    check_B2,
    check_B3,
    check_B4,
    check_C1,
    check_C2,
    check_C3,
    check_C4,
    check_D1,
    check_D2,
    check_D3,
    check_E1,
    check_E2,
    check_E3,
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)

    items = []
    for fn in CHECKS:
        try:
            items.append(fn())
        except Exception as exc:  # noqa: BLE001
            items.append(
                _item(fn.__name__, fn.__name__, "UNKNOWN", 1, "检查异常 %r" % exc)
            )

    total_w = sum(i["weight"] for i in items)
    got_w = sum(i["weight"] for i in items if i["status"] == "PASS")
    score = round(100.0 * got_w / total_w, 1) if total_w else 0.0

    print("=" * 78)
    print("投稿就绪度审计（%d 检查，加权得分 %.1f/100）" % (len(items), score))
    print("=" * 78)
    for i in items:
        mark = {"PASS": "OK  ", "GAP": "GAP ", "UNKNOWN": "?   "}[i["status"]]
        print("%s [w%d] %-34s %s" % (mark, i["weight"], i["name"], i["evidence"][:70]))
        if i["action"]:
            print("           -> %s" % i["action"][:100])

    print("\n--- 期刊档位可达性 ---")
    verdict = {}
    for tier, need in TIER_RULES:
        miss = [
            c
            for c in need
            if not any(i["id"] == c and i["status"] == "PASS" for i in items)
        ]
        verdict[tier] = miss
        print(
            "%s：%s"
            % (tier, "可达" if not miss else "不可达（缺 %s）" % ", ".join(miss))
        )

    if a.json:
        io.open(a.json, "w", encoding="utf-8", newline="\n").write(
            json.dumps(
                dict(score=score, n=len(items), items=items, tiers=verdict),
                ensure_ascii=False,
                indent=1,
            )
        )
        print("\n[json] %s" % a.json)
    blocker_gap = [i["id"] for i in items if i["status"] == "GAP" and i["weight"] >= 3]
    return 0 if not blocker_gap else 2


if __name__ == "__main__":
    sys.exit(main())
