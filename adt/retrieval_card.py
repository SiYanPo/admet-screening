# -*- coding: utf-8 -*-
"""可复现检索策略卡（2026-11-19；技能市场 100 skill 移植）。

## 来源
`@clawhub_.../biomedical-search-strategy-builder`（组4[96]）原文：
"MeSH-based Boolean query... expand a concept with synonyms, apply study-type or date
filters, or adapt a query across multiple databases"。
`@indiv-.../quantitative...` 与 `@clawhub_.../paper-search-pro`（组2[30]/[33]）：
"adjustable depth / MeSH term mapping / Boolean query construction"。

## 为什么需要
本 skill 的 `snapshot.py` 锁的是**数据 hash**；`LITERATURE_SEARCH_SOP.md` 要求
检索式可复现，但缺一个机器可读的"用什么查询拿到这批数据"的工件。
检索式一变，语料就不可复现——这与 G4 冻结纪律同级，却一直没被锁住。

## 诚实边界
* 本模块只登记策略工件与哈希，**不执行检索、不代替数据库**。
* 查询串不保密；哈希只证明"策略未变"，不证明"数据库未变"（数据库会更新）。
* 须与 `retrieved_at` 一起归档，否则无法区分策略漂移与库漂移。
"""

from __future__ import annotations

import hashlib
import io
import json


def make_card(
    query,
    sources,
    date_from=None,
    date_to=None,
    depth="full",
    filters=None,
    synonyms=None,
    note="",
    retrieved_at=None,
):
    """构造检索策略卡。

    query: 主查询串（原样保存，不做任何规范化，便于逐字节复核）。
    sources: 数据库/端点列表。
    depth: quick / full / audit（可调深度档位）。
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query 必须是非空字符串")
    # 字符串会被 list() 逐字符拆成单字符列表（"PubMed" -> ['P','u','b'...]），
    # 静默损坏策略工件；dict 同理只留 key。这里显式拒绝非列表/元组来源。
    if isinstance(sources, (str, bytes)) or not isinstance(sources, (list, tuple)):
        raise ValueError("sources 必须是非空列表/元组（不接受字符串/dict）")
    sources = list(sources)
    if not sources or not all(isinstance(s, str) and s.strip() for s in sources):
        raise ValueError("sources 必须是非空字符串列表")
    card = dict(
        schema="adt-retrieval-card/1.0",
        query=query,
        sources=sources,
        date_from=date_from,
        date_to=date_to,
        depth=depth,
        filters=filters or {},
        synonyms=synonyms or {},
        retrieved_at=retrieved_at,
        note=note,
        discipline="登记策略工件，不执行检索；哈希只证明策略未变，不证明数据库未变",
    )
    canonical = json.dumps(
        card, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    card["strategy_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return card


def verify_card(card):
    """复核策略卡哈希（防被静默改写）。"""
    if not isinstance(card, dict) or "strategy_sha256" not in card:
        return dict(ok=False, reason="非策略卡或缺 strategy_sha256")
    cp = dict(card)
    expected = cp.pop("strategy_sha256")
    canonical = json.dumps(
        cp, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    got = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    ok = got == expected
    return dict(
        ok=ok,
        expected=expected,
        computed=got,
        reason="策略未被改动" if ok else "策略卡内容与哈希不符——疑似事后修改",
    )


def save_card(card, path):
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(card, ensure_ascii=False, indent=2) + "\n")
    return path


def selftest():
    rows = []

    def chk(name, cond, detail=""):
        rows.append(dict(name=name, ok=bool(cond), detail=detail))

    c = make_card(
        '("conformal prediction"[Title/Abstract]) AND 2024:2026[dp]',
        ["PubMed", "arXiv"],
        date_from="2024",
        date_to="2026",
        depth="audit",
        synonyms={"conformal": ["conformal prediction"]},
        retrieved_at="2026-11-19T00:00:00",
    )
    chk("card_created", len(c["strategy_sha256"]) == 64, c["strategy_sha256"][:12])
    chk("hash_verifies", verify_card(c)["ok"], "")
    bad = dict(c)
    bad["query"] = "different query"
    chk("tamper_detected", verify_card(bad)["ok"] is False, "")
    # 同输入必须同哈希（确定性）
    c2 = make_card(
        c["query"],
        c["sources"],
        date_from=c["date_from"],
        date_to=c["date_to"],
        depth=c["depth"],
        filters=c["filters"],
        synonyms=c["synonyms"],
        note=c["note"],
        retrieved_at=c["retrieved_at"],
    )
    chk("deterministic", c2["strategy_sha256"] == c["strategy_sha256"], "")
    # query 顺序变化应产生不同哈希（不做规范化）
    c3 = make_card(c["query"] + " ", c["sources"])
    chk("byte_exact", c3["strategy_sha256"] != c["strategy_sha256"], "")
    try:
        make_card("", ["PubMed"])
        chk("empty_query_rejected", False, "")
    except ValueError:
        chk("empty_query_rejected", True, "")
    try:
        make_card("x", [])
        chk("empty_sources_rejected", False, "")
    except ValueError:
        chk("empty_sources_rejected", True, "")
    return all(x["ok"] for x in rows), rows


if __name__ == "__main__":
    import argparse, json

    ap = argparse.ArgumentParser(prog="retrieval-card")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        ok, rows = selftest()
        for r in rows:
            print(
                "[%s] %s %s"
                % ("OK" if r["ok"] else "FAIL", r["name"], r["detail"][:60])
            )
        print("[retrieval-card] %s" % ("PASS" if ok else "FAIL"))
        raise SystemExit(0 if ok else 4)
