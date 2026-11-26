# -*- coding: utf-8 -*-
"""R34–R39：六条红线必须能在代码层被断言（文档承诺不算）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import guards as G     # noqa: E402
from adt import release_gate as RG  # noqa: E402


def test_red_lines_all_enforced():
    ok, st = G.all_enforced()
    assert ok, [k for k, v in st.items() if not v["ok"]]
    # v4.1 原有 6 条；v4.4 由 G8 扩为 9 条（+gate_eval_distribution /
    # external_not_preregistered / endpoint_plurality）。断言须跟随实际条数，
    # 否则"代码 9 条、测试 6 条"又是一种记录≠实现。
    assert len(st) == 9, "v4.4 起红线应为 9 条，实际 %d" % len(st)


def test_line1_admission_blocks_unanchored_or_stereo_missing():
    # 合法立体结构：放行
    assert G.admission_line([{"name": "ok", "smiles": "C[C@H](N)C(=O)O"}])["ok"]
    # 有未指定手性中心 + 未声明 → 阻断（红线 1）
    try:
        G.admission_line([{"name": "bad", "smiles": "CC(N)C(=O)O"}])
    except G.NormalizeInputError as e:
        assert "立体" in str(e)
    else:
        raise AssertionError("缺立体声明应被红线 1 拦截")
    # 不可解析 → 阻断
    try:
        G.admission_line([{"name": "junk", "smiles": "not_a_smiles"}])
    except G.NormalizeInputError:
        pass
    else:
        raise AssertionError("不可解析结构应被拦截")


def test_line2_sample_size_three_levels():
    q = G.sample_size_guard(6)
    assert q["level"] == "qualitative" and q["rates_allowed"] is False
    assert "只允许定性结论" in q["banner"]
    b = G.sample_size_guard(25)
    assert b["level"] == "banner" and b["rates_allowed"] is True
    assert b["ranking_allowed"] is False            # 小样本不默认排序
    assert G.sample_size_guard(40)["level"] == "ok"
    assert G.sample_size_guard(40)["banner"] == ""


def test_line3_replay_required_and_override_leaves_trace():
    old = {k: os.environ.get(k) for k in ("ADT_REPLAY", "ADT_ALLOW_ONLINE")}
    try:
        os.environ.pop("ADT_REPLAY", None)
        os.environ.pop("ADT_ALLOW_ONLINE", None)
        try:
            G.require_replay("论文数字")
        except G.ReplayRequired as e:
            assert "ADT_REPLAY=1" in str(e)
        else:
            raise AssertionError("非重放模式必须拒绝")
        os.environ["ADT_ALLOW_ONLINE"] = "1"
        r = G.require_replay()
        assert r["ok"] and r["override"] is True     # 允许但留痕
        os.environ["ADT_REPLAY"] = "1"
        assert G.require_replay()["override"] is False
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_line4_low_validity_requires_explicit_acceptance():
    try:
        G.low_validity_line(["DILI", "hERG"])
    except G.LowValidityError as e:
        assert "DILI" in str(e) and "--i-accept-low-validity" in str(e)
    else:
        raise AssertionError("DILI 未显式接受应被拦截")
    assert G.low_validity_line(["hERG"])["ok"]                  # 可裁决端点不受限
    r = G.low_validity_line(["DILI"], accepted=True, note="内部探索")
    assert r["ok"] and r["accepted"] and "DILI" in r["note"]


def test_line5_commercial_profile_blocks_nc_sources_and_logs():
    from adt import compliance as C
    d = tempfile.mkdtemp()
    old = os.environ.get("ADT_CALL_LOG")
    os.environ["ADT_CALL_LOG"] = os.path.join(d, "calls.jsonl")
    try:
        try:
            C.enforce("protox3", "commercial")
        except C.ComplianceError:
            pass
        else:
            raise AssertionError("commercial 档必须禁用 CC-BY-NC 源")
        assert C.enforce("admetlab3", "academic-internal") is True
        assert not os.path.exists(os.environ["ADT_CALL_LOG"])    # 学术档不强制归档
        assert C.enforce("admetlab3", "commercial") is True
        with open(os.environ["ADT_CALL_LOG"], encoding="utf-8") as fh:
            txt = fh.read()
        assert "admetlab3" in txt and "commercial" in txt        # 商用必须留痕
    finally:
        if old is None:
            os.environ.pop("ADT_CALL_LOG", None)
        else:
            os.environ["ADT_CALL_LOG"] = old


def test_line6_unqualified_claim_is_blocked():
    try:
        G.interval_line("仅单位守卫 7.83% 略优")
    except G.RedLineError as e:
        assert "略优" in str(e)
    else:
        raise AssertionError("无 CI 的'略优'应被红线 6 拦截")
    assert G.interval_line("差异 0.45pp（95% CI [-1.2,1.3]）",
                           has_ci_or_test=True)["ok"]
    assert G.interval_line("与 B 相比差异为 0.45pp（配对 McNemar p=0.31）",
                           has_ci_or_test=True)["ok"]


def test_release_gate_reads_red_lines_and_label_gate():
    d = tempfile.mkdtemp()
    open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8").write(
        "---\nname: x\nversion: 4.0-dev\n---\n")
    items = {i["key"]: i for i in RG.check(d, include_dag=False)["items"]}
    # C04 / 外审 C V1（2026-11-04）：G8 必须检查**目标制品 root**，不得再查运行中
    # 的 adt 包自身。空临时目录不含源码与红线集成测试证据，因此 G8 判 False 才是
    # 修复后的正确行为；旧断言 `ok is True` 恰恰是 self-attestation 的症状。
    assert items["G8_red_lines"]["ok"] is False
    assert items["G8_red_lines"]["level"] == "blocker"
    assert items["G11_negative_result_defaults"]["ok"] is False  # 目标 root 无登记表
    assert items["G9_label_granting"]["ok"] is True      # -dev 允许（但为 warn 级）
    # 去掉 -dev 但锚定条件未满足 → 必须 BLOCK（防止"改个数字就说完成"）
    open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8").write(
        "---\nname: x\nversion: 4.0\n---\n")
    items = {i["key"]: i for i in RG.check(d, include_dag=False)["items"]}
    assert items["G9_label_granting"]["ok"] is False
    assert items["G9_label_granting"]["level"] == "blocker"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("OK", fn.__name__)
    print("ALL PASS test_red_lines_v41.py (%d)" % len(fns))
