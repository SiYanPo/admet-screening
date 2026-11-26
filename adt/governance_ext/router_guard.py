# -*- coding: utf-8 -*-
"""穿透式追问 Q1：前置意图分类器 / 路由守卫。

在进入 Skill 前做确定性关键词打分隔离，避免 14 Skill 并存时被泛化 Skill 抢占。
同时对"三个 description 逐字相同的 pharmacology-agent"去做重告警。
纯标准库。
"""

from __future__ import annotations

# 路由规则：(意图信号集合, 目标 Skill, 排他/负信号集合)
ROUTE_RULES = [
    (
        {
            "多源",
            "冲突",
            "矛盾",
            "该信谁",
            "弃权",
            "undetermined",
            "适用域",
            "admet",
            "裁决",
            "置信",
        },
        "admet-screening",
        {"网络药理学", "ppl", "富集"},
    ),
    (
        {"pbpk", "pk-sim", "生理药代", "nca", "ivive", "ddi", "群体药代"},
        "pk-sim-pbpk",
        set(),
    ),
    (
        {"网络药理学", "ppi", "富集", "成分-靶点", "复方", "tcmsp"},
        "tcm-network-pharmacology",
        set(),
    ),
    (
        {"藏药", "体内adme", "lc-ms", "pk markers", "生物利用度方案"},
        "tibetan-adme-study",
        set(),
    ),
    ({"民族药", "基原", "q-marker", "炮制"}, "ethnic-medicine-pharmacology", set()),
    (
        {"chain", "chemistry-query", "流水线", "agent链"},
        "pharmaclaw-pharmacology-agent",
        set(),
    ),
]
# 已知重复 skill 组（description 逐字相同，需去重）
DUPLICATE_GROUPS = {
    "pharmacology_agent_triplet": [
        "pharmaclaw-pharmacology-agent",
        "pcl-pharmacology-agent",
        "pharma-pharmacology-agent",
    ],
}


def _normalize(q):
    return q.lower().strip()


def route_guard(user_query, *, default="admet-screening"):
    """返回路由目标 + 打分明细 + 去重告警。"""
    q = _normalize(user_query)
    scored = []
    for signals, target, negatives in ROUTE_RULES:
        pos = sum(1 for s in signals if s in q)
        neg = sum(1 for s in negatives if s in q)
        score = pos - neg
        if score > 0:
            scored.append((target, score, pos, neg))
    if not scored:
        return {
            "target": default,
            "reason": "no_signal_default",
            "confidence": "low",
            "scores": [],
            "dedup_notice": _dedup_notice(default),
        }
    scored.sort(key=lambda x: x[1], reverse=True)
    winner = scored[0]
    # 若最高分唯一，confidence=high；并列 → medium
    tie = len([s for s in scored if s[1] == winner[1]]) > 1
    return {
        "target": winner[0],
        "reason": "keyword_score",
        "confidence": "medium" if tie else "high",
        "winner_score": winner[1],
        "scores": [
            {"target": t, "score": s, "pos": p, "neg": n} for t, s, p, n in scored
        ],
        "dedup_notice": _dedup_notice(winner[0]),
    }


def _dedup_notice(target):
    for group, members in DUPLICATE_GROUPS.items():
        if target in members:
            return {
                "group": group,
                "message": "检测到 %d 个 description 逐字相同的重复 Skill，已路由到 %s；"
                "建议市场侧合并/下架" % (len(members), target),
                "members": members,
            }
    return None
