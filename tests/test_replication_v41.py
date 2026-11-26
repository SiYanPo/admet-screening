# -*- coding: utf-8 -*-
"""R28（预注册外部锚定）/ R29–R30（复现挑战包 + 容差由种子方差反推）回归测试。"""
import io
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import prereg as P        # noqa: E402
from adt import replication as R   # noqa: E402


# ------------------------------------------------------------ R28
def test_prereg_unanchored_blocks_claim():
    d = tempfile.mkdtemp()
    pr = P.Prereg(os.path.join(d, "p.jsonl"))
    pr.register_criteria("src_inclusion_v1", {"min_n": 30})
    st = pr.anchor_status()
    assert st["anchored"] is False and st["claim_allowed"] is False
    assert "UNANCHORED" in pr.footnote()
    assert "不得声称" in st["warning"] and "预注册" in st["warning"]


def test_prereg_anchor_post_hoc_is_visible():
    d = tempfile.mkdtemp()
    pr = P.Prereg(os.path.join(d, "p.jsonl"))
    pr.register_criteria("src_inclusion_v1", {"min_n": 30})
    pr.attach_anchor({"registry": "OSF", "doi": "10.17605/OSF.IO/ABCDE",
                      "deposited_at": "2026-11-01T10:00:00"})
    st = pr.anchor_status()
    # 2026-11-17 同行评审更正：旧断言 `assert st["claim_allowed"]` 把 bug 当作正确行为锁死——
    # 事后锚定只证明"文档提交时刻"，不证明"提交时未看过数据"（红线8 / C01 / C18）。
    # SKILL 授予条件①拿 claim_allowed 当判据，若 post_hoc 仍为 True，则事后补锚
    # 一次点击即可满足①。现改为：锚定可见但仍不得授予"已预注册"资格。
    assert st["anchored"] and not st["claim_allowed"]
    assert st["post_hoc_anchor"] is True          # 锚定晚于登记，必须可见
    assert st["doi"] == "10.17605/OSF.IO/ABCDE"
    assert pr.verify()["ok"]                       # 链仍然完整


def test_prereg_anchor_validation():
    d = tempfile.mkdtemp()
    pr = P.Prereg(os.path.join(d, "p.jsonl"))
    for bad in ({"registry": "OSF", "doi": "not-a-doi"},
                {"registry": "OSF"},                       # doi/url 至少给一个
                {"registry": "Figshare", "url": "https://x"}):
        try:
            pr.attach_anchor(bad)
        except P.PreregError:
            continue
        raise AssertionError("应拒绝：%r" % (bad,))


# ------------------------------------------------------------ R30
def test_tolerance_is_k_times_seed_sd():
    t = R.tolerance_from_seeds([1.0, 2.0, 3.0])       # sd = 1.0
    assert abs(t["sd"] - 1.0) < 1e-9
    assert abs(t["tol"] - 2.0) < 1e-9                 # k=2
    assert t["degenerate"] is False
    assert R.tolerance_from_seeds([1.0, 2.0, 3.0], k=3)["tol"] > t["tol"]
    wide = R.tolerance_from_seeds([-1.0, 0.0, 1.0])
    assert wide["tol"] > R.tolerance_from_seeds([-0.1, 0.0, 0.1])["tol"]


def test_tolerance_degenerate_for_deterministic_metric():
    """sd=0 时禁止把容差定为 0（否则等于要求逐位相等），必须退化为下限并声明。"""
    t = R.tolerance_from_seeds([0.5] * 20)
    assert t["sd"] == 0 and t["degenerate"] is True
    assert t["tol"] == R.TOL_FLOOR_ABS > 0
    assert "不能由种子方差反推" in t["note"]


# ------------------------------------------------------------ R29
def _mk_pack(tmp, weak=False):
    metrics = [dict(name="hERG.auc", value=0.84, tol=0.02, kind="auc", seed_sd=0.01, n_seeds=20)]
    if weak:
        metrics.append(dict(name="hERG.risk", value=0.10, tol=0.10,
                            kind="risk_decided", seed_sd=0.05, n_seeds=20))
    return R.build_pack(tmp, metrics, spec=dict(seeds=list(range(20))))


def test_pack_files_and_no_intermediate_artifacts():
    tmp = tempfile.mkdtemp()
    exp = _mk_pack(tmp)
    names = set(os.listdir(tmp))
    assert {"README.md", "expected.json", "score.py",
            "SUBMISSION_TEMPLATE.json"} <= names
    # 挑战包不得含中间产物（预测概率 / 每种子明细）
    assert not [n for n in names if n.endswith((".csv", ".npz", ".pkl"))]
    assert exp["metrics"][0]["tol"] == 0.02 and exp["n_counted"] == 1


def test_weak_discrimination_metric_is_not_counted():
    tmp = tempfile.mkdtemp()
    exp = _mk_pack(tmp, weak=True)
    by = {m["name"]: m for m in exp["metrics"]}
    assert by["hERG.risk"]["weak_discrimination"] is True
    assert by["hERG.risk"]["counted"] is False
    assert by["hERG.auc"]["counted"] is True
    assert exp["n_counted"] == 1
    # 全部指标都判别力不足 → 拒绝出包（否则挑战包无法判对错）
    try:
        R.build_pack(tempfile.mkdtemp(), [dict(name="x", value=0.1, tol=0.5)])
    except ValueError as e:
        assert "无法判别对错" in str(e)
    else:
        raise AssertionError("应拒绝全部弱判别指标的包")


def test_score_pass_fail_missing_and_copy_detection():
    tmp = tempfile.mkdtemp()
    _mk_pack(tmp)
    ok = R.score(tmp, dict(metrics={"hERG.auc": dict(value=0.84)}))
    assert ok["all_pass"] and ok["suspicious_identical"]     # 照抄 → 触发反游戏化标记
    near = R.score(tmp, dict(metrics={"hERG.auc": dict(value=0.851)}))
    assert near["all_pass"] and not near["suspicious_identical"]
    bad = R.score(tmp, dict(metrics={"hERG.auc": dict(value=0.90)}))
    assert (not bad["all_pass"]) and bad["rows"][0]["status"] == "FAIL"
    miss = R.score(tmp, dict(metrics={}))
    assert (not miss["all_pass"]) and miss["rows"][0]["status"] == "MISSING"


def test_pack_score_py_standalone_agrees_with_module():
    """包内 score.py 必须能脱离 skill 独立运行（第二实现者只有这个包）。"""
    tmp = tempfile.mkdtemp()
    _mk_pack(tmp)
    sub = os.path.join(tmp, "submission.json")
    with io.open(sub, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(metrics={"hERG.auc": dict(value=0.84)})))
    out = subprocess.run([sys.executable, os.path.join(tmp, "score.py"), sub],
                         capture_output=True, text=True, timeout=120)
    res = json.loads(out.stdout)
    assert res["all_pass"] is True and res["suspicious_identical"] is True


def test_numbers_only_submission_is_not_replication():
    """2026-11-19：README 承诺"只交数字不算复现"，评分器必须真的执行这条。

    旧行为的真实缺陷：`score()` 只比对数字，纯数字提交 `verdict=pass` ——
    文档承诺与代码行为不一致，外部审阅者会误信"已要求代码"。
    """
    tmp = tempfile.mkdtemp()
    _mk_pack(tmp)
    # ① 纯数字：数字全过，但缺 implementation/environment → numbers_only
    only = R.score(tmp, dict(metrics={"hERG.auc": dict(value=0.851)}))
    assert only["all_pass"] is True
    assert only["verdict"] == "numbers_only"
    assert only["provenance"]["complete"] is False
    assert "implementation" in only["provenance"]["missing"]
    # ② 补齐环境但没实现 → 仍不完整
    env_only = R.score(tmp, dict(metrics={"hERG.auc": dict(value=0.851)},
                                environment=dict(python="3.13.12", rdkit="2024.09.6",
                                                 numpy="2.5.4")))
    assert env_only["verdict"] == "numbers_only"
    assert "implementation" in env_only["provenance"]["missing"]
    # ③ 实现 + 环境齐备 → pass
    full = R.score(tmp, dict(metrics={"hERG.auc": dict(value=0.851)},
                            implementation=dict(repo="https://example.org/repro"),
                            environment=dict(python="3.13.12", rdkit="2024.09.6",
                                             numpy="2.5.4")))
    assert full["verdict"] == "pass"
    assert full["provenance"]["complete"] is True
    # ④ 包内 score.py 的退出码必须区分三种结局（0 通过 / 2 只交数字 / 1 失败）
    sub = os.path.join(tmp, "sub_numbers.json")
    with io.open(sub, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(metrics={"hERG.auc": dict(value=0.851)})))
    out = subprocess.run([sys.executable, os.path.join(tmp, "score.py"), sub],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 2, out.stdout[-500:]
    assert json.loads(out.stdout)["verdict"] == "numbers_only"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("OK", fn.__name__)
    print("ALL PASS test_replication_v41.py (%d)" % len(fns))
