# -*- coding: utf-8 -*-
"""v4.4 回归：Ames ICH M7 双方法合成必须真正发生（不是只写进文档）。

锁住的历史教训：v4.3 把"补 adt/alerts.py 专家规则层、放行错误率 0.269→0.177"
写进了 CHANGELOG 与 ENDPOINT_TIER_EVIDENCE，但 reliab 从未调用 alerts.py，
导致 ames 在生产管线里永远 UNDETERMINED——文档声称与实际行为脱节。
本测试直接钉住 apply_tier_policy 在 expert_rule_layer=True 时做 two_method_verdict 合成。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import endpoints as E


def _ames(verdict, cid="B", expert=True, sources="admet_ai;vnn"):
    return {"compound_id": cid, "endpoint": "ames", "verdict": verdict,
            "sources": sources, "expert_rule_layer": expert, "reason": ""}


def test_two_method_synthesis_stat_pass_alert_hit_is_fail():
    """统计阴性 + 结构警示命中 → ICH M7 不得判 Class 5 → FAIL。"""
    recs = [_ames("PASS", cid="C1")]
    out, _ = E.apply_tier_policy([dict(r) for r in recs], False,
                                 alert_cache={"C1": True})
    assert out[0]["verdict"] == "FAIL", out[0]
    assert "ich_m7_two_method" in out[0]["reason"]
    assert out[0]["alert_hit"] == "Y"


def test_two_method_synthesis_stat_pass_no_alert_is_pass():
    """统计阴性 + 无结构警示 → 双法皆阴 → PASS（Class 5 方向）。"""
    recs = [_ames("PASS", cid="C2")]
    out, _ = E.apply_tier_policy([dict(r) for r in recs], False,
                                 alert_cache={"C2": False})
    assert out[0]["verdict"] == "PASS", out[0]
    assert out[0]["alert_hit"] == "N"


def test_two_method_synthesis_stat_fail_is_fail():
    """统计阳性 → 任一法阳性即 FAIL。"""
    recs = [_ames("FAIL", cid="C3")]
    out, _ = E.apply_tier_policy([dict(r) for r in recs], False,
                                 alert_cache={"C3": False})
    assert out[0]["verdict"] == "FAIL", out[0]


def test_no_expert_layer_still_undetermined():
    """未启用专家规则层（expert_rule_layer=False）→ 维持 UNDETERMINED。"""
    recs = [_ames("PASS", cid="C4", expert=False)]
    out, log = E.apply_tier_policy([dict(r) for r in recs], False,
                                  alert_cache={"C4": False})
    assert out[0]["verdict"] == "UNDETERMINED"
    assert any("requires_expert_rules" in l["reason"] for l in log)


def test_backward_compat_no_cache_defaults_false():
    """未传 alert_cache 时 alert_hit 默认 False（与旧行为兼容）。"""
    recs = [_ames("PASS", cid="C5")]
    out, _ = E.apply_tier_policy([dict(r) for r in recs], False)
    assert out[0]["verdict"] == "PASS"
    assert out[0]["alert_hit"] == "N"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("OK", fn.__name__)
    print("ALL PASS test_ames_alerts_wired.py (%d)" % len(fns))
