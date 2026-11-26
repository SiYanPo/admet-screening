# -*- coding: utf-8 -*-
"""C2（bbb 静默降级）与 P1.7（domain_flag 写入点白名单）的回归测试。

两条都属于"评审指出后才被看见"的缺陷：
  C2 —— 会改写 verdict 的决策层失败被裸 `except Exception: pass` 吞掉；
  P1.7 —— 裁决层的信任根字段（domain_flag）没有任何写入点清单，
          外部评审 R-D 明确要求"确认只有合法写入点"。
"""
import io
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from adt import reliability as R          # noqa: E402
from adt import flag_audit as FA         # noqa: E402


def _row(**kw):
    d = dict(compound_id="C1", endpoint="bbb_martins", value=0.3,
             unit="probability", source="s1", domain_flag="predicted")
    d.update(kw)
    return d


# ---------------------------------------------------------------- C2
def test_bbb_layer_failure_leaves_trace(monkeypatch):
    """bbb.postprocess 抛错时：必须留痕 + 置信度降级，禁止静默 pass。"""
    def boom(_out):
        raise ImportError("simulated: sklearn missing")

    monkeypatch.setattr("adt.bbb.postprocess", boom, raising=True)
    recs = R.evaluate([_row(), _row(compound_id="C2")], rules={})
    assert recs, "裁决不应因 bbb 层失败而整体崩溃"
    for r in recs:
        assert str(r.get("bbb_mechanism", "")).startswith("layer_failed:")
        assert r["confidence"] == "low", "决策层失败必须把置信度降到 low"
        assert "BBB 双层机制未运行" in r["reason"]


def test_bbb_layer_success_no_failure_mark():
    recs = R.evaluate([_row()], rules={})
    for r in recs:
        assert not str(r.get("bbb_mechanism", "")).startswith("layer_failed:")


# ---------------------------------------------------------------- P1.7
def test_domain_flag_audit_passes_on_repo():
    ok, bad, sites = FA.audit()
    assert ok, "未登记的 domain_flag 写入点：%s" % [(b["file"], b["line"], b["why"]) for b in bad]
    assert len(sites) >= 9, "写入点普查结果过少，说明扫描失效"


def test_domain_flag_audit_detects_unregistered_site(tmp_path):
    """故意造一个未登记写入点，audit 必须报出来（防止白名单变成空转）。"""
    adt = tmp_path / "adt"
    adt.mkdir(exist_ok=True)
    (adt / "evil.py").write_text(
        "def hack(rows):\n"
        "    for r in rows:\n"
        "        r['domain_flag'] = 'measured'\n"
        "    return rows\n", encoding="utf-8")
    ok, bad, sites = FA.audit(str(tmp_path))
    assert not ok
    assert any(b["file"].endswith("evil.py") for b in bad)


def test_domain_flag_values_are_in_schema_vocab():
    """白名单里允许的取值必须 ⊆ schema.DOMAIN_FLAGS（防止白名单自己漂移）。"""
    from adt.schema import DOMAIN_FLAGS
    for key, spec in FA.WHITELIST.items():
        assert spec["allowed"] <= DOMAIN_FLAGS, "%s 白名单含非法取值" % (key,)
        assert spec["why"], "%s 未写正当性（白名单必须逐点给理由）" % (key,)
