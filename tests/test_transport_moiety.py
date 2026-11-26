# -*- coding: utf-8 -*-
"""U1 回归：苷元/糖苷分档（Peng 2023, RSC Med Chem 14:890-898）。

断言四件事：
  1. 糖在芳环上（异槲皮苷）→ OATP2B1 下调一档，证据标 direct；
  2. 糖在脂肪碳上（王百合苷 A）→ 只弱下调半档，证据标 extrapolated；
  3. 苷元（槲皮素）→ 无吡喃糖，不触发任何糖苷规则；
  4. 调整**只作用于 OATP2B1**，不得外溢到 SGLT1 / MRP2。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adt import transport as T  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  ok  %s" % name)
    else:
        print("  FAIL %s  %s" % (name, detail))
        FAILS.append(name)


PR = T.load_priors()
ISOQ = ("OC[C@H]1O[C@@H](Oc2cc(O)c3c(=O)cc(-c4ccc(O)c(O)c4)oc3c2)"
        "[C@H](O)[C@@H](O)[C@@H]1O")
QUERCETIN = "O=c1cc(-c2ccc(O)c(O)c2)oc2cc(O)cc(O)c12"
REG_A = ("O=C(/C=C/c1ccc(O)cc1)OC[C@@H](O)CO[C@@H]1O[C@H](CO)[C@@H](O)"
         "[C@H](O)[C@H]1O")

print("== 1. 芳环氧苷：直接下调 ==")
mo = T.moiety_flags(ISOQ)
check("异槲皮苷判为芳环氧苷", mo["sugar_on_aryl"] and not mo["sugar_on_aliphatic"], mo)
rows, _, _ = T.assess("isoq", ISOQ, PR)
oatp = [r for r in rows if r["transporter"] == "OATP2B1"]
check("命中 OATP2B1", len(oatp) >= 1, len(oatp))
check("base 保留为 medium", oatp[0]["plausibility_base"] == "medium", oatp[0])
check("调整后 low_to_medium", oatp[0]["plausibility"] == "low_to_medium", oatp[0])
check("证据标 measured_literature_SAR",
      oatp[0]["evidence_level"] == "measured_literature_SAR", oatp[0]["evidence_level"])
check("adjust_reason 非空", bool(oatp[0]["adjust_reason"]), oatp[0]["adjust_reason"])

print("== 2. 脂肪碳糖苷：弱下调 ==")
mo2 = T.moiety_flags(REG_A)
check("王百合苷 A 判为脂肪碳糖苷",
      mo2["has_pyranose"] and mo2["sugar_on_aliphatic"] and not mo2["sugar_on_aryl"], mo2)
rows2, _, _ = T.assess("regA", REG_A, PR)
o2 = [r for r in rows2 if r["transporter"] == "OATP2B1"]
check("命中 OATP2B1（两类化学型均给出）", len(o2) >= 1, len(o2))
check("弱下调为 low_to_medium（不是直接降档）",
      all(r["plausibility"] == "low_to_medium" for r in o2), [r["plausibility"] for r in o2])
check("证据标 extrapolated",
      all(r["evidence_level"] == "extrapolated_from_literature_SAR" for r in o2),
      [r["evidence_level"] for r in o2])

print("== 3. 苷元：不触发糖苷规则 ==")
mo3 = T.moiety_flags(QUERCETIN)
check("槲皮素无吡喃糖", not mo3["has_pyranose"], mo3)
check("无芳环/脂肪糖苷标记",
      not mo3["sugar_on_aryl"] and not mo3["sugar_on_aliphatic"], mo3)
rows3, _, _ = T.assess("que", QUERCETIN, PR)
check("苷元不出现 OATP2B1 的糖苷调整行",
      all(r["adjust_reason"] == "" for r in rows3),
      [(r["transporter"], r["adjust_reason"]) for r in rows3])

print("== 4. 不外溢：其他转运体档位不变 ==")
for r in rows2 + rows:
    if r["transporter"] in ("SGLT1", "MRP2 / BCRP", "MCT / LAT（一元羧酸/氨基酸转运体）"):
        check("%s 未被糖苷规则改写" % r["transporter"],
              r["plausibility"] == r["plausibility_base"],
              (r["plausibility_base"], r["plausibility"]))

print("== 5. 只下调、不上调 ==")
adj = T.apply_moiety_rules("low", "OATP2B1",
                           dict(sugar_on_aryl=True, sugar_on_aliphatic=False),
                           PR.get("moiety_rules"))
check("low 再降仍为 low（不下溢成负档）", adj["level"] == "low", adj)
up = T.apply_moiety_rules("high", "SGLT1",
                          dict(sugar_on_aryl=True, sugar_on_aliphatic=False),
                          PR.get("moiety_rules"))
check("非目标转运体不调整", up["level"] == "high" and up["tag"] == "", up)

print()
if FAILS:
    print("FAILED %d: %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("ALL OK")
