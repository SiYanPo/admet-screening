# -*- coding: utf-8 -*-
"""P2.2 回归测试：前瞻数据时间窗校验（"锚定先于数据"从口头承诺变机器校验）。

背景（references/PREREG_ANCHORING_CHECKLIST.md §5 的"仍是空的"）：
  G9 此前只能证明"锚定过"，不能证明"锚定发生在看到数据之前"。
本测试锁定 5 条行为：
  1) 数据全部晚于锚定 → ok=True；
  2) 任一数据不晚于锚定 → ok=False / reason=data_before_anchor，并给出 n_violations；
  3) 无锚定 → reason=no_anchor（不许在没有锚点时假称时序合规）；
  4) prospective_data_window 进冻结项且链上可回读（temporal_window_declared）；
  5) CLI：prereg-status --data-timestamps 在违规时 exit 4、合规时 exit 0。
运行：python tests/test_prereg_temporal.py
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt.prereg import Prereg  # noqa: E402

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".scratch")
ANCHOR = {"registry": "OSF", "url": "https://osf.io/example",
          "deposited_at": "2026-11-23T03:22:32Z"}
CRITERIA = {"main": "dU>0 on >=2/3 endpoints"}


def _fresh(tag):
    os.makedirs(SCRATCH, exist_ok=True)
    path = os.path.join(SCRATCH, "prereg_temporal_%s_%d.jsonl" % (tag, os.getpid()))
    if os.path.exists(path):
        os.remove(path)
    return path


def test_data_after_anchor_is_ok():
    log = _fresh("ok")
    p = Prereg(log)
    p.register_criteria(name="t", criteria=CRITERIA, external_anchor=ANCHOR)
    tv = p.temporal_validity(["2026-11-24T10:00:00Z", "2026-12-01", "2026-11-23T12:00:00"])
    assert tv["ok"] is True, tv
    assert tv["reason"] == "ok"
    assert tv["n_data"] == 3 and tv["n_violations"] == 0
    assert p.verify()["ok"] is True


def test_data_before_anchor_blocks():
    log = _fresh("bad")
    p = Prereg(log)
    p.register_criteria(name="t", criteria=CRITERIA, external_anchor=ANCHOR)
    # 2026-11-22 早于锚定 2026-11-23T03:22:32Z；同时放一条无法解析的
    tv = p.temporal_validity(["2026-11-24T00:00:00Z", "2026-11-22T09:00:00Z", "not-a-date"])
    assert tv["ok"] is False
    assert tv["reason"] == "data_before_anchor"
    assert tv["n_violations"] == 2, tv
    assert any("2026-11-22" in x for x in tv["early_examples"])


def test_no_anchor_cannot_claim_temporal_validity():
    log = _fresh("noanchor")
    p = Prereg(log)
    p.register_criteria(name="t", criteria=CRITERIA)      # 无外部锚定
    tv = p.temporal_validity(["2026-11-24T00:00:00Z"])
    assert tv["ok"] is False and tv["reason"] == "no_anchor", tv


def test_prospective_window_is_frozen_and_readable():
    log = _fresh("window")
    p = Prereg(log)
    win = {"rule": "min(data_ts) > anchor_date",
           "data_ts_source": "labels.csv:collected_at"}
    p.register_criteria(name="t", criteria=CRITERIA, external_anchor=ANCHOR,
                        prospective_data_window=win)
    assert p.temporal_window_declared() == win
    # 冻结项进了 hash 链：篡改 criteria 会被 verify 抓到（此处只验证链自洽）
    assert p.verify()["ok"] is True


def test_cli_exit_codes():
    log = _fresh("cli")
    p = Prereg(log)
    p.register_criteria(name="t", criteria=CRITERIA, external_anchor=ANCHOR)
    bad = os.path.join(SCRATCH, "ts_bad_%d.txt" % os.getpid())
    good = os.path.join(SCRATCH, "ts_good_%d.json" % os.getpid())
    with open(bad, "w", encoding="utf-8") as fh:
        fh.write("2026-11-22T00:00:00Z\n")
    with open(good, "w", encoding="utf-8") as fh:
        json.dump(["2026-12-01", "2026-12-02"], fh)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = [sys.executable, "-m", "adt.cli", "prereg-status", "--log", log,
           "--data-timestamps"]
    r_bad = subprocess.run(cmd + [bad], cwd=root, capture_output=True, text=True)
    r_good = subprocess.run(cmd + [good], cwd=root, capture_output=True, text=True)
    assert r_bad.returncode == 4, (r_bad.returncode, r_bad.stderr[-400:])
    assert r_good.returncode == 0, (r_good.returncode, r_good.stderr[-400:])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS %s" % fn.__name__)
    print("ALL OK (%d tests)" % len(fns))
