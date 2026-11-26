# -*- coding: utf-8 -*-
"""Estimand 绑定门（G13）—— 把"跨量纲比较"从教训变成可执行的阻断。

## 为什么存在（七寸漏洞）

2026-11-04 的 C01 撤回，根因是一句看似无害的比较：
    `auc < always_positive_accuracy` → "域外没有排序能力"
AUC 的随机基线是 0.5（秩量纲），always-positive accuracy 恒等于 prevalence
（正确分类比例量纲）。两个不同量纲、不同零假设的数**不能比大小**。
这个错误不是算术错误，而是 estimand 未绑定——没有一层在数字对外前问一句：
"你测的是哪个量？基线是什么？和谁比？同量纲吗？"

本模块把这个问题变成机器可判的门：
  1. `check_comparison(metric_a, metric_b, ...)`：两指标量纲/基线不同 → BLOCK；
  2. `check_claim(endpoint, metric, ...)`：端点 estimand 未绑定 → 禁推断性结论；
  3. `validate_text(text)`：扫描文本里已知违规表达式（C01/C18）→ BLOCK；
  4. `audit_artifact(path)`：审计产物里 estimand_status 与 inference_status 自洽。

发布门禁 G13 调用本模块；CLI `estimand-check` 提供人工入口。
纯标准库 + pyyaml，无网络、无 rdkit 依赖，换机即用。

## 诚实边界

* 本门只拦"可静态举证的跨量纲/未绑定"错误，不能判断一个 estimand 是否"科学上恰当"
  ——那是评审专家的判断，不是正则的判断。
* 通过本门 ≠ 结论正确；只是"没有犯 C01 那类可判定的错误"。
* endpoint 卡的 gold_standard_bound=true 必须由人回填实验证据，代码不会自动置位。
"""

from __future__ import annotations

import io
import json
import os
import re

from . import resref

CARDS_NAME = "ENDPOINT_ESTIMAND_CARDS.yaml"


def load_cards(path=None):
    """加载 estimand 卡；走 resref 解析顺序（显式 > env > 源码树 > 包内）。"""
    import yaml

    if path and os.path.isfile(path):
        p = path
    else:
        try:
            p = resref.resolve(CARDS_NAME)
        except Exception:
            p = os.path.join(resref.package_root(), "references", CARDS_NAME)
            if not os.path.isfile(p):
                raise FileNotFoundError("estimand 卡找不到：%s" % CARDS_NAME)
    return yaml.safe_load(io.open(p, encoding="utf-8").read())


# 比较运算符（中英文）：出现在两指标之间即视为"比较句"
_CMP = re.compile(
    r"(?:\s*(?:<|>|<=|>=|==|!=)\s*|"
    r"\s*(?:低于|高于|小于|大于|劣于|优于|不如|超过|低于同批)\s*)"
)


def _metric_scale(cards, name):
    m = (cards.get("metrics") or {}).get(name)
    if not m:
        return None
    return dict(
        scale=m.get("scale"),
        baseline_kind=m.get("baseline_kind"),
        null_baseline=m.get("null_baseline"),
        label=m.get("label", name),
    )


def check_comparison(metric_a, metric_b, cards=None, context=""):
    """判断两个指标能否放在同一比较句。返回机器可读裁决 dict。

    判据（按强度顺序）：
      1. 指标未在卡中登记 → BLOCK（未登记量纲不可比）；
      2. scale 不同 → BLOCK（跨量纲，C01 就是这类）；
      3. scale 相同但 baseline_kind 不同 → BLOCK（同量纲不同零假设，仍不可直接比大小）；
      4. scale 与 baseline_kind 都相同 → ALLOW。
    """
    cards = cards or load_cards()
    a = _metric_scale(cards, metric_a)
    b = _metric_scale(cards, metric_b)
    out = dict(
        metric_a=metric_a,
        metric_b=metric_b,
        context=context,
        verdict=None,
        reason="",
        a=a,
        b=b,
    )
    if a is None or b is None:
        missing = [x for x, v in ((metric_a, a), (metric_b, b)) if v is None]
        out.update(
            verdict="BLOCK",
            reason="指标未登记量纲：%s（不可参与比较）" % ", ".join(missing),
        )
        return out
    if a["scale"] != b["scale"]:
        out.update(
            verdict="BLOCK",
            reason=(
                "跨量纲比较：%s(scale=%s, null=%s) vs %s(scale=%s, null=%s)。"
                "C01 同类错误：AUC 基线 0.5 与 always-positive=prevalence 不可比。"
            )
            % (
                metric_a,
                a["scale"],
                a["null_baseline"],
                metric_b,
                b["scale"],
                b["null_baseline"],
            ),
        )
        return out
    if a["baseline_kind"] != b["baseline_kind"]:
        out.update(
            verdict="BLOCK",
            reason=(
                "同量纲但零假设不同：%s(baseline=%s) vs %s(baseline=%s)，"
                "须各自对基线做配对检验，不得直接比数值。"
            )
            % (metric_a, a["baseline_kind"], metric_b, b["baseline_kind"]),
        )
        return out
    out.update(
        verdict="ALLOW",
        reason="同量纲（%s）且零假设同类（%s），可比。"
        % (a["scale"], a["baseline_kind"]),
    )
    return out


# 推断性措辞：estimand 未绑定时禁用
_INFERENTIAL = re.compile(
    r"(?:判别力|排序能力|域外不可用|保守的正确|门有(?:无)?(?:用|效|判别)|"
    r"没有排序|仍有弱排序|显著劣于|无增加值)"
)


def check_claim(endpoint, claim_text, cards=None, metric=None):
    """端点评测主张的 estimand 绑定检查。返回裁决 dict。"""
    cards = cards or load_cards()
    ep = (cards.get("endpoints") or {}).get(endpoint)
    out = dict(
        endpoint=endpoint,
        claim=claim_text,
        metric=metric,
        verdict=None,
        estimand_status=None,
        reason="",
    )
    if ep is None:
        out.update(
            verdict="BLOCK",
            estimand_status="UNREGISTERED",
            reason="端点 %r 未在 estimand 卡登记" % endpoint,
        )
        return out
    status = ep.get("estimand_status")
    out["estimand_status"] = status
    inferential = bool(_INFERENTIAL.search(claim_text or ""))
    bound = bool(ep.get("gold_standard_bound"))
    if inferential and (not bound or status in ("NOT_AN_ESTIMAND",)):
        out.update(
            verdict="BLOCK",
            reason=(
                "端点 %s 的 estimand_status=%s（金标准未绑定），"
                "禁止推断性措辞。reason=%s；requires=%s"
            )
            % (endpoint, status, ep.get("reason", ""), ep.get("requires", "")),
        )
        return out
    if metric and metric not in (ep.get("admissible_metrics") or []):
        out.update(
            verdict="WARN",
            reason="指标 %r 不在端点 %s 的 admissible_metrics 内" % (metric, endpoint),
        )
        return out
    out.update(verdict="ALLOW", reason="estimand_status=%s，措辞未越界" % status)
    return out


def validate_text(text, cards=None):
    """扫描一段文本，命中已知违规表达式（C01/C18）即 BLOCK。"""
    cards = cards or load_cards()
    hits = []
    for v in cards.get("known_violations") or []:
        expr = v.get("expression", "")
        if not expr:
            continue
        # 允许正则式表达；字面量先精确匹配，再做宽松空白匹配
        patterns = [re.escape(expr), re.escape(expr).replace(r"\ ", r"\s+")]
        found = False
        for pat in patterns:
            if re.search(pat, text or "", re.IGNORECASE):
                found = True
                break
        if found:
            hits.append(
                dict(
                    id=v.get("id"),
                    status=v.get("status"),
                    reason=v.get("reason"),
                    expression=expr,
                )
            )
    # 通用跨量纲模式：auc ... < ... (always_positive|prevalence|accuracy)
    generic = re.search(
        r"\bauc\b[^。.\n]{0,40}(?:<|低于|小于)[^。.\n]{0,40}"
        r"(?:always[_-]?positive|prevalence|accuracy|准确率)",
        text or "",
        re.IGNORECASE,
    )
    if generic and not any(h["id"] == "C01" for h in hits):
        hits.append(
            dict(
                id="C01-like",
                status="DETECTED",
                reason="检测到 AUC 与准确率/prevalence 的量纲混比（C01 型）",
                expression=generic.group(0)[:80],
            )
        )
    return dict(verdict="BLOCK" if hits else "ALLOW", hits=hits, n_hits=len(hits))


def audit_artifact(path, cards=None):
    """审计产物内 estimand_status / inference_status 是否自洽。"""
    cards = cards or load_cards()
    obj = json.load(io.open(path, encoding="utf-8"))
    est = obj.get("estimand_status", "")
    rob = obj.get("robustness") or {}
    inf = rob.get("inference_status", "")
    cross = rob.get("cross_dimensional_comparison") or {}
    out = dict(
        path=path,
        estimand_status=est,
        inference_status=inf,
        cross_dim_valid=cross.get("valid"),
        verdict=None,
        reason="",
    )
    revoked = "NOT_AN_ESTIMAND" in str(est) or "revoked" in str(inf)
    if revoked:
        if cross.get("valid") is not False:
            out.update(
                verdict="BLOCK",
                reason="estimand 未绑定但未显式登记 cross_dimensional_comparison.valid=false",
            )
        else:
            out.update(
                verdict="ALLOW",
                reason="estimand 未绑定，但产物已如实标 inference_revoked + cross_dim invalid（一致性通过）",
            )
        return out
    out.update(verdict="ALLOW", reason="estimand 已绑定或产物无需 estimand 声明")
    return out


def selftest():
    """内置自检：C01 必须被拦，合法比较必须放行。返回 (all_ok, rows)。"""
    cards = load_cards()
    rows = []

    def rec(name, ok, detail):
        rows.append(dict(name=name, ok=bool(ok), detail=detail))

    # 1. C01 跨量纲必须 BLOCK
    r = check_comparison("auc", "always_positive_accuracy", cards)
    rec("C01_cross_dimension_blocked", r["verdict"] == "BLOCK", r["reason"])
    # 2. AUC vs 0.5（同尺度自比）不应因跨量纲被拦——用 AUC 对固定 chance 基线是合法的
    r2 = check_claim("hERG", "域外没有排序能力", cards, metric="auc")
    rec("hERG_inferential_blocked_unbound", r2["verdict"] == "BLOCK", r2["reason"])
    # 2b. 纯描述性指标报告（非推断）不应被 estimand 门误伤
    r2b = check_claim("hERG", "报告域内 AUC=0.580 及其 95% CI", cards, metric="auc")
    rec("descriptive_claim_not_blocked", r2b["verdict"] != "BLOCK", r2b["reason"])
    # 3. 同量纲同基线应 ALLOW
    r3 = check_comparison("accuracy", "always_positive_accuracy", cards)
    rec("same_scale_allowed", r3["verdict"] == "ALLOW", r3["reason"])
    # 4. 文本违规表达式扫描
    r4 = validate_text("结论：三集合 AUC 全部低于同批 always-positive accuracy", cards)
    rec("text_c01_detected", r4["verdict"] == "BLOCK", str(r4["hits"]))
    # 5. 干净文本应放行
    r5 = validate_text("本报告仅报告域内 AUC 及其 95% CI，未做跨量纲比较。", cards)
    rec("clean_text_allowed", r5["verdict"] == "ALLOW", str(r5["hits"]))
    ok = all(x["ok"] for x in rows)
    return ok, rows


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(prog="estimand")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    ap.add_argument("--claim", help="主张文本")
    ap.add_argument("--endpoint")
    ap.add_argument("--text", help="扫描文本中的违规表达式")
    ap.add_argument("--artifact", help="审计产物 JSON")
    a = ap.parse_args()
    if a.selftest:
        ok, rows = selftest()
        for r in rows:
            print(
                "[%s] %s : %s"
                % ("OK" if r["ok"] else "FAIL", r["name"], r["detail"][:90])
            )
        print("[estimand] %s" % ("PASS" if ok else "FAIL"))
        raise SystemExit(0 if ok else 4)
    if a.compare:
        r = check_comparison(a.compare[0], a.compare[1])
        print(json.dumps(r, ensure_ascii=False, indent=2))
        raise SystemExit(0 if r["verdict"] != "BLOCK" else 4)
    if a.claim:
        r = check_claim(a.endpoint or "", a.claim)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        raise SystemExit(0 if r["verdict"] != "BLOCK" else 4)
    if a.text:
        r = validate_text(a.text)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        raise SystemExit(0 if r["verdict"] != "BLOCK" else 4)
    if a.artifact:
        r = audit_artifact(a.artifact)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        raise SystemExit(0 if r["verdict"] != "BLOCK" else 4)
    ap.print_help()
