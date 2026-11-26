# -*- coding: utf-8 -*-
"""U14/U15/U16 回归：TRIPOD+AI 自查 / model card / FAIR 映射。

文献：
  Collins GS et al. TRIPOD+AI. BMJ 2024;385:e078378 (DOI 10.1136/bmj-2023-078378)
  Mitchell M et al. Model Cards. FAT* '19:220-229 (DOI 10.1145/3287560.3287596)
  Wilkinson MD et al. FAIR. Sci Data 2016;3:160018 (DOI 10.1038/sdata.2016.18)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import reporting as R  # noqa: E402

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


print("== 1) TRIPOD+AI：全齐 vs 全空 ==")
full = dict(skill_version="3.0.0", has_registry=True, has_tier=True, tier="T3",
            n_sources=3, n_sources_versioned=3, has_normalize=True,
            n_endpoints=59, n_endpoints_with_unit=59, has_source_groups=True,
            n_compounds=120, n_pos=40, has_coverage=True, has_manifest=True,
            has_benchmark=True, has_real_benchmark=True, has_calibration=True,
            has_external=True, has_subgroup=True, has_ledger=True, has_units=True,
            threshold_from_measured=True)
t = R.tripod_checklist(full)
check("条目数 16", len(t) == 16, len(t))
check("全齐时无 not_met", all(x["status"] != "not_met" for x in t),
      [(x["code"], x["status"]) for x in t if x["status"] == "not_met"])
check("code 唯一", len({x["code"] for x in t}) == len(t))

empty = R.tripod_checklist({})
bad = [x["code"] for x in empty if x["status"] == "not_met"]
check("空上下文下 11/12/13 未达", {"11", "12", "13"}.issubset(set(bad)), bad)
check("未达项都写了缺口", all(x["gap"] for x in empty if x["status"] == "not_met"))
check("判别力未达时点名校准/真值", any("真值" in x["gap"] for x in empty
                                       if x["code"] == "11"))

print("== 2) TRIPOD：DEMO 基准不算判别力 ==")
demo = dict(full, has_real_benchmark=False, has_calibration=False)
t2 = {x["code"]: x for x in R.tripod_checklist(demo)}
check("无真基准 -> 11 partial", t2["11"]["status"] == "partial", t2["11"])
check("无校准 -> 12 partial", t2["12"]["status"] == "partial", t2["12"])

print("== 3) model card ==")
cards = R.load_cards()
check("登记 8 个源", len(cards) == 8, sorted(cards))
check("含 admetlab3/admet_ai/vnn_admet",
      {"admetlab3", "admet_ai", "vnn_admet"}.issubset(set(cards)), sorted(cards))
rows, md = R.model_cards()
check("每张卡都有 intended_use", all(r["intended_use"] for r in rows),
      [r["source"] for r in rows if not r["intended_use"]])
check("已知失效被汇总", all(r["n_known_failures"] >= 1 for r in rows),
      [(r["source"], r["n_known_failures"]) for r in rows])
check("markdown 含'已知失效'", "已知失效" in md)
check("markdown 含表格", "| 字段 | 内容 |" in md)
check("admetlab3 卡里写明 429 限流",
      "429" in cards["admetlab3"]["rate_limit"],
      cards["admetlab3"]["rate_limit"])

rows2, md2 = R.model_cards(missing={"brand_new_source"})
check("未登记源被点名", "未登记的源" in md2 and "brand_new_source" in md2)

print("== 4) FAIR 映射 ==")
f = R.fair_mapping(dict(has_registry=True, has_manifest=True, has_ledger=True,
                        has_units=True))
check("13 条子原则", len(f) == 13, len(f))
check("全齐时全部 covered", all(x["status"] == "covered" for x in f),
      [x for x in f if x["status"] != "covered"])
f2 = R.fair_mapping(dict(has_registry=False, has_manifest=False, has_ledger=False,
                         has_units=True))
check("无 manifest -> R1.2 partial",
      [x for x in f2 if x["code"] == "R1.2"][0]["status"] == "partial",
      [x for x in f2 if x["code"] == "R1.2"])
check("无 registry -> F4 partial",
      [x for x in f2 if x["code"] == "F4"][0]["status"] == "partial")
check("每条都给了本 skill 的落地物", all(x["artifact"] for x in f))

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
