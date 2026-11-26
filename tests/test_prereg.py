# -*- coding: utf-8 -*-
"""P11 回归测试：源纳入/排除预注册（prereg.py）+ mppb supersede 补留痕。

场景取自评审 C12 真实案例：mppb 曾因 ρ 符号翻转被**事后排除**——本测试验证：
  1) 历史决策可补登记但必须标 post_hoc（链上可见其事后性）；
  2) 预注册链上，统计噪声不再是合法排除理由（PreregError）；
  3) supersede 重评必须携带触发统计量并指向真实历史事件 hash；
  4) 哈希链防篡改：任何篡改 verify() 即失败；
  5) footnote 产出可引用的登记声明。
运行：python tests/test_prereg.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt.prereg import (Prereg, PreregError, STRUCTURAL_EXCLUDE_REASONS)

# 每进程独立文件名：避免 Windows 下前一运行的句柄/杀软扫描短暂锁定同名文件，
# 导致 smoke 子进程里 os.remove 抛 PermissionError 的瞬时失败（2026-10-31 实测一次）。
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   ".scratch", "prereg_test_%d.jsonl" % os.getpid())


def _fresh():
    if os.path.exists(LOG):
        os.remove(LOG)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    return Prereg(LOG)


def _setup_trail(p):
    """在**指定的** Prereg 对象上建立"先标准、后事后排除"的完整留痕。

    2026-10-31 修复：原写法是 test_supersede_* 里先 `p = Prereg(LOG)`，
    再调用 `test_criteria_first_*()` —— 而后者内部 `_fresh()` 会**删文件重建另一个对象**。
    外层 p 的 events 是删文件之前读的，看不到随后写入的 prereg_id，
    于是 supersede 的"prereg_id 必须存在"校验必然失败。
    这不是校验过严，而是测试混用了两个会互相覆盖的对象。
    """
    pid = p.register_criteria(
        "independence_matrix_inclusion_v1",
        criteria={
            "exclude_allowed_reasons": list(STRUCTURAL_EXCLUDE_REASONS),
            "stat_noise_policy": "annotate_sign_conflict_not_exclude",
            "decision_order": "criteria_before_data",
        }, note="先定标准、后看数据（C12）")
    assert pid, "prereg_id 不能为空"
    # 历史 mppb 排除（ρ 符号翻转事后决策）——如实补登记，post_hoc=True
    h1 = p.decide("mppb", "PPB", "exclude", pid,
                  reason="rho_sign_flip", evidence="评审材料 v3 矩阵脚注",
                  post_hoc=True)
    return pid, h1


def test_criteria_first_and_posthoc_mppb_trail():
    p = _fresh()
    pid, h1 = _setup_trail(p)
    st = p.replay("mppb")
    assert st[("mppb", "PPB")]["action"] == "exclude", st
    v = p.verify()
    assert v["ok"], v
    print("criteria=%s mppb 事后排除留痕 hash=%s" % (pid[:12], h1[:12]))
    return pid, h1


def test_supersede_reinclude_with_trigger_stat():
    p = _fresh()
    pid, h1 = _setup_trail(p)
    # supersede：按预注册标准重评 → 统计噪声改用 annotate 保留源
    h2 = p.supersede("mppb", "PPB", "annotate", pid,
                     reason="posthoc_exclusion_invalid_under_prereg_criteria",
                     trigger_stat=dict(rho=-0.574, ci_lo=-0.78, ci_hi=-0.30,
                                       n=14, dataset="cinnamon_glycoside"),
                     supersedes_hash=h1,
                     evidence="保留 + sign_conflict 标注（C12 处方）")
    st = p.replay("mppb")
    cur = st[("mppb", "PPB")]
    assert cur["action"] == "annotate", cur
    assert cur["last_event"] == "supersede"
    assert cur["trigger_stat"]["rho"] == -0.574
    assert p.verify()["ok"]
    print("mppb supersede 重评 hash=%s -> annotate" % h2[:12])


def test_stat_noise_not_excludable_on_prereg_chain():
    p = _fresh()
    pid = p.register_criteria("c", criteria={"policy": "x"})
    try:
        p.decide("srcA", "herg", "exclude", pid, reason="rho_sign_flip")
        raise SystemExit("统计噪声作为新排除理由未被拦截")
    except PreregError as e:
        assert "结构性理由" in str(e)
    # 结构性理由可以排除
    p.decide("srcB", "herg", "exclude", pid, reason="data_unavailable")
    print("预注册链上统计噪声排除被拦截；结构性排除放行 OK")


def test_tamper_detected():
    p = _fresh()
    pid = p.register_criteria("c", criteria={"policy": "x"})
    p.decide("srcA", "herg", "include", pid, reason="ok")
    p.events[-1]["payload"]["action"] = "exclude"  # 篡改内存中的事件
    v = p.verify()
    assert not v["ok"] and v["broken_at"] is not None, v
    print("哈希链防篡改 OK（broken_at=%s）" % v["broken_at"])


def test_supersedes_hash_must_exist_and_footnote():
    p = _fresh()
    pid = p.register_criteria("c", criteria={"policy": "x"})
    h = p.decide("srcA", "herg", "include", pid, reason="ok")
    try:
        p.supersede("srcA", "herg", "exclude", pid, reason="x",
                    trigger_stat=0.1, supersedes_hash="deadbeef" * 8)
        raise SystemExit("伪造 supersedes_hash 未被拦截")
    except PreregError:
        pass
    p.supersede("srcA", "herg", "annotate", pid, reason="recheck",
                trigger_stat=0.1, supersedes_hash=h)
    fn = p.footnote()
    assert "链头 hash=" in fn and str(fn).split("hash=")[1][:12] in fn
    print("supersedes_hash 校验 + footnote OK:", fn)


if __name__ == "__main__":
    test_criteria_first_and_posthoc_mppb_trail()
    test_supersede_reinclude_with_trigger_stat()
    test_stat_noise_not_excludable_on_prereg_chain()
    test_tamper_detected()
    test_supersedes_hash_must_exist_and_footnote()
    print("\nP11 预注册测试全部通过")
