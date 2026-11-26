# -*- coding: utf-8 -*-
"""规则表角色与升级条件的契约测试（v2.3.1）。

背景：v2.3.1 把 MMP 从"参照"升级为"质量端点"（有了第 2 个独立组），
其余候选（CYP 抑制、微粒体清除率）**因为条件不满足而保持参照**。
这类"谁能投票、谁只能报告"的判断必须由规则表本身可验证，不能靠记忆。

跑法: python tests/test_rules_roles.py
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import yaml                                   # noqa: E402

PASS = 0
FAIL = []


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL.append(name)
        print("FAIL  %s  %s" % (name, detail))


rules = {e["id"]: e for e in yaml.safe_load(
    io.open(os.path.join(HERE, "references", "03_endpoint_rules.yaml"),
            encoding="utf-8"))["endpoints"]}

print("== 1) MMP 已升级为质量端点（两独立组）==")
m = rules.get("mmp")
check("mmp 存在", m is not None)
check("role 为 quality（缺省）", (m or {}).get("role", "quality") == "quality", str((m or {}).get("role")))
check("require_sources = 2", (m or {}).get("require_sources") == 2, str((m or {}).get("require_sources")))
check("三区带：shape=down，pass=0.3 / fail=0.7（拒单点 0.5）",
      (m or {}).get("shape") == "down" and (m or {}).get("pass") == 0.3
      and (m or {}).get("fail") == 0.7, str(m))
check("note 说明 0.5 是 arbitrary、采用灰区带",
      "arbitrary" in (m or {}).get("note", "") and "灰区" in (m or {}).get("note", ""))

print("== 2) CYP 抑制保持参照（vNN 全 NoPrediction，只有单组）==")
for ep in ("cyp1a2_inhibition", "cyp2c19_inhibition", "cyp2c9_inhibition",
           "cyp2d6_inhibition", "cyp3a4_inhibition"):
    r = rules.get(ep) or {}
    check("%s role=reference" % ep, r.get("role") == "reference", str(r.get("role")))

print("== 3) 微粒体清除率：单位已核，单源入 quality（confidence 必为 low）==")
cl = rules.get("clint_microsome") or {}
check("role 为 quality（缺省）", cl.get("role", "quality") == "quality")
check("unit = uL/min/mg", cl.get("unit") == "uL/min/mg", str(cl.get("unit")))
check("require_sources 已严化为 2（v2.3.5：单组不下判决）",
      cl.get("require_sources") == 2, str(cl.get("require_sources")))
check("note 记录单位核实（mL/min/g ≡ µL/min/mg）",
      "数值等价" in cl.get("note", ""), cl.get("note", "")[:50])
check("旧参照端点 clint_microsome_admetai 已撤销",
      "clint_microsome_admetai" not in rules)

print("== 4) 旧源前缀命名已清理 ==")
legacy = [k for k in rules if k.startswith("vnn_cyp") or k == "vnn_mmp"]
check("无 vnn_cyp* / vnn_mmp 残留", legacy == [], str(legacy))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
