# -*- coding: utf-8 -*-
"""默认配置 = 负结果的落地形态（A3 / G11）。

## 这个模块解决什么问题
框架最容易犯的伪善是：论文里写"准入层不优于基线"，代码里**默认仍然启用准入层**。
那样负结果只对读者生效、对自己不生效。

本模块把 `references/NEGATIVE_RESULT_DEFAULTS.yaml` 里的每条负结果读成**默认值**，
并提供 `assert_consistent()`：
  ① yaml 的 `default` 必须与 `DEFAULTS` 逐键相等（防文档改了代码没改）；
  ② 每条必须带 `evidence`，且产物文件存在、数字字面量真的在文件里（防"证据是编的"）。

发布门禁 `G11_negative_result_defaults` 直接调用 `assert_consistent()`，
所以"负结果进默认配置"是**可断言的**，不是一句表态。

## 用法
```python
from adt import defaults
defaults.get("decision_strategy")        # -> "S1_naive_majority"
defaults.assert_consistent()             # -> dict(ok=..., mismatches=[], evidence_failures=[])
```
"""

from __future__ import annotations

import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YAML_PATH = os.path.join(ROOT, "references", "NEGATIVE_RESULT_DEFAULTS.yaml")

# 与 yaml 的 `defaults[].default` 逐键对应。改这里必须同步改 yaml 与证据。
DEFAULTS = {
    "decision_strategy": "S1_naive_majority",
    "admission_layer_enabled": False,
    "require_cost_ratio": True,
    "ranking_enabled": False,
    "gate_passthru_interpretation": "unweighted_abstention",
    "multi_criteria_ad_default": False,
    "mmp_endpoints_default": "hERG,BBB_Martins",
    "external_claim_scope": "no_extrapolation",
}

# 【2026-11-04 已撤回 / R4·C18】原注释「弃权代价轴上准入层开始不划算的上界」基于
# Δu(c)=a−q·c 一阶线性会计恒等式，c* 只是该线性函数的零点，代价未进入决策，
# 不得用于任何推断（见 references/RETRACTION_NOTE.md §五）。
# 全库无调用点，仅为历史兼容保留；新代码禁止引用。
MAX_ADVANTAGE_ABSTAIN_COST = 0.26


def get(key, fallback=None):
    return DEFAULTS.get(key, fallback)


def load_yaml(path=None):
    import yaml

    p = path or YAML_PATH
    with io.open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _norm(v):
    """yaml 里 True/False 与字符串 "true" 的宽松比较。"""
    if isinstance(v, str):
        low = v.strip().lower()
        if low in ("true", "yes", "on"):
            return True
        if low in ("false", "no", "off"):
            return False
        return v.strip()
    return v


def assert_consistent(path=None):
    doc = load_yaml(path)
    entries = doc.get("defaults") or []
    mismatches, evidence_failures, checked = [], [], 0
    for e in entries:
        key = e.get("key")
        want = _norm(e.get("default"))
        got = DEFAULTS.get(key, "<missing>")
        if _norm(got) != want:
            mismatches.append({"key": key, "yaml": want, "code": got})
        ev = e.get("evidence") or {}
        art = ev.get("artifact")
        expect = ev.get("expect") or []
        if not art or not expect:
            evidence_failures.append(
                {"key": key, "why": "缺 evidence.artifact 或 expect"}
            )
            continue
        p = os.path.join(ROOT, art) if not os.path.isabs(art) else art
        if not os.path.exists(p):
            evidence_failures.append({"key": key, "artifact": art, "why": "产物不存在"})
            continue
        txt = io.open(p, encoding="utf-8", errors="replace").read()
        missing = [t for t in expect if str(t) not in txt]
        if missing:
            evidence_failures.append(
                {"key": key, "artifact": art, "why": "产物内找不到 %s" % missing}
            )
            continue
        checked += 1
    return {
        "ok": not mismatches
        and not evidence_failures
        and len(entries) == len(DEFAULTS),
        "yaml": os.path.relpath(YAML_PATH, ROOT).replace("\\", "/"),
        "n_entries": len(entries),
        "n_defaults_in_code": len(DEFAULTS),
        "n_evidence_verified": checked,
        "mismatches": mismatches,
        "evidence_failures": evidence_failures,
        "rule": doc.get("meta", {}).get("rule", ""),
    }
