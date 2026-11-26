# -*- coding: utf-8 -*-
"""C70/C71/C72 回归：三项湿实验替代的接线、量纲与单位真源。

背景（v2.3.3）：
  * C70——"用 ADMETlab 替代三项湿实验"此前只接了 CLint，Caco-2 与 PPB
    **根本没进长表**；声称的替代在管线上只有 1/3。
  * C71——`caco2_papp_ab` 规则用线性 cm/s 阈值（1e-6/5e-6），而两个源给的是
    log10 值（−6.5）→ −6.5 < 1e-6 恒成立，**所有分子恒判 FAIL**；
    且 `scale` 字段没有任何代码读取（死字段）。
  * C72——适配器把单位硬编码 "probability"，把 CLint（µL/min/mg）也写成了概率。

本测试锁三件事：
  1) 两源的 Caco-2 / PPB 列都映射到同一规范端点；
  2) 单位只有一个真源（规则表），非概率端点不得写 probability；
  3) % bound → fu 的换算方向正确（换算错会让结论反号）。

跑法: python tests/test_units_and_transforms.py
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import yaml                                              # noqa: E402

from adt import endpoints                                # noqa: E402

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


print("== 1) 三项湿实验替代：两源映射必须一致（C70）==")
ai_map, _ = endpoints.load_source_map("admet_ai")
lab_map, _ = endpoints.load_source_map("admetlab3")
check("ADMET-AI Caco2_Wang -> caco2_papp_ab",
      ai_map.get("Caco2_Wang") == "caco2_papp_ab", str(ai_map.get("Caco2_Wang")))
check("ADMET-AI PPBR_AZ -> ppb_fu",
      ai_map.get("PPBR_AZ") == "ppb_fu", str(ai_map.get("PPBR_AZ")))
check("ADMET-AI Clearance_Microsome_AZ -> clint_microsome",
      ai_map.get("Clearance_Microsome_AZ") == "clint_microsome")
check("ADMETlab caco2 -> caco2_papp_ab",
      lab_map.get("caco2") == "caco2_papp_ab", str(lab_map.get("caco2")))
check("ADMETlab PPB -> ppb_fu", lab_map.get("PPB") == "ppb_fu")

print("== 2) 单位只有一个真源（C72）==")
check("caco2_papp_ab 的单位是 log10(cm/s)",
      endpoints.unit_for("caco2_papp_ab") == "log10(cm/s)",
      repr(endpoints.unit_for("caco2_papp_ab")))
check("clint_microsome 的单位不是 probability",
      endpoints.unit_for("clint_microsome") == "uL/min/mg",
      repr(endpoints.unit_for("clint_microsome")))
check("ppb_fu 的单位是 percent",
      endpoints.unit_for("ppb_fu") == "percent", repr(endpoints.unit_for("ppb_fu")))
check("dili 仍是 probability", endpoints.unit_for("dili") == "probability")

print("== 3) Caco-2 规则必须是 log 量纲、无死字段（C71）==")
rules = {e["id"]: e for e in yaml.safe_load(
    io.open(os.path.join(HERE, "references", "03_endpoint_rules.yaml"),
            encoding="utf-8"))["endpoints"]}
c = rules["caco2_papp_ab"]
check("unit=log10(cm/s)", c.get("unit") == "log10(cm/s)", str(c.get("unit")))
check("阈值是 log 数（pass > fail）",
      c.get("pass") == -5.3 and c.get("fail") == -6.0, "%s/%s" % (c.get("pass"), c.get("fail")))
check("scale 死字段已删除", "scale" not in c, str(c.keys()))

print("== 4) % bound -> fu 换算方向（换算错则结论反号）==")
from adt.adapters.admet_ai import TRANSFORMS as AI_T          # noqa: E402
from adt.adapters.admetlab3 import TRANSFORMS as LAB_T        # noqa: E402

f_ai = AI_T["PPBR_AZ"][0]
f_lab = LAB_T["PPB"][0]
check("PPBR_AZ 90 (% bound) -> fu 10", abs(f_ai(90.0) - 10.0) < 1e-9, str(f_ai(90.0)))
check("PPBR_AZ 60 -> fu 40", abs(f_ai(60.0) - 40.0) < 1e-9, str(f_ai(60.0)))
check("ADMETlab PPB 换算一致（77.7 -> 22.3）", abs(f_lab(77.7) - 22.3) < 1e-9, str(f_lab(77.7)))
check("高结合（99.5% bound）= 低 fu（0.5）",
      f_ai(99.5) < 1.0, str(f_ai(99.5)))

print("== 5) 已知药物的换算可用性（APAP 文献 fu≈0.8-0.9）==")
check("APAP 17.3 % bound -> fu 82.7%", abs(f_lab(17.3) - 82.7) < 0.05, str(f_lab(17.3)))
check("caffeine 32.5 % bound -> fu 67.5%", abs(f_lab(32.5) - 67.5) < 0.05, str(f_lab(32.5)))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")


# ---------- v2.3.4：本地离线模式（C74）----------
print("== 6) 本地模式必须与网页服务版本可区分（禁止混用）==")
from adt.adapters.admet_ai import AdmetAIAdapter          # noqa: E402

a_web = AdmetAIAdapter(verbose=False)
a_loc = AdmetAIAdapter(verbose=False, local=True)
check("网页模式 version 不带 local", "local" not in a_web.version, a_web.version)
check("本地模式 version = 2.0.1-local", a_loc.version == "2.0.1-local", a_loc.version)
check("两模式 version 不同（混表即可被发现）",
      a_web.version != a_loc.version, "%s vs %s" % (a_web.version, a_loc.version))
check("本地模式仍需走 TRANSFORMS（PPBR→fu 不能漏）",
      "PPBR_AZ" in __import__("adt.adapters.admet_ai", fromlist=["x"]).TRANSFORMS)

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
