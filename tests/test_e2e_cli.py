# -*- coding: utf-8 -*-
"""CLI 级端到端测试（C42 教训：单测直调函数测不出调用时序错误）。

用 subprocess 走真实的 `python -m adt.cli` 入口，断言**落盘 CSV 的列内容**，
而不是函数返回值。跑法: python tests/test_e2e_cli.py
"""
import csv
import io
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

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


tmp = tempfile.mkdtemp(prefix="admet_e2e_")
inp = os.path.join(tmp, "in.txt")
with io.open(inp, "w", encoding="utf-8", newline="\n") as f:
    f.write("ok_mol\tCCO\n")                                  # 正常
    f.write("zwitter\t[NH3+]CC(=O)[O-]\n")                    # 两性离子 → state_sensitive
    f.write("radical\t[CH3]\n")                               # 硬门
    f.write("badvalence\tC(C)(C)(C)(C)C\n")                   # 解析失败

# ---- 1) normalize 端到端：必须过 CLI 入口（C42 的时序 bug 只有这一层能抓到）----
r = subprocess.run([PY, "-m", "adt.cli", "normalize", "--in", inp,
                    "--outdir", tmp], cwd=HERE, capture_output=True,
                   text=True, timeout=180)
check("normalize exit=0", r.returncode == 0, r.stderr[-200:])
p = os.path.join(tmp, "compounds.csv")
check("compounds.csv 落盘", os.path.exists(p))
rows = {r["compound_id"]: r
        for r in csv.DictReader(io.open(p, encoding="utf-8-sig"))}
check("解析失败分子被跳过（3 行非 4）", len(rows) == 3, str(list(rows)))
check("正常分子 unchanged", rows["ok_mol"]["state_flag"] == "unchanged")
# C42 回归核心断言：两性离子的 state_sensitive 必须在 **CLI 层**非空
check("两性离子 state_sensitive 非空（C42 回归）",
      rows["zwitter"]["state_sensitive"] != "",
      repr(rows["zwitter"]["state_sensitive"]))
check("自由基被硬门拦（CLI 层）",
      rows["radical"]["hard_gate_problems"] != "")

# ---- 2) 拦截分子禁止进入分发层 ----
sys.path.insert(0, HERE)
from adt.cli import load_released_compounds   # noqa: E402
comps = load_released_compounds(p, tag="test")
check("公共层过滤后 2 个（radical 被剔）", len(comps) == 2,
      str([c["compound_id"] for c in comps]))
check("公共层保留的都是无硬门问题",
      all(not c["hard_gate_problems"] for c in comps))

# ---- 3) report 的措辞封顶（模板占位符必须被填值，不留 {verdict} 裸占位）----
rel = os.path.join(tmp, "reliability.csv")
with io.open(rel, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=[
        "compound_id", "endpoint", "n_total", "n_in_domain", "n_measured",
        "sources", "n_indep_groups", "indep_groups", "value_used", "unit",
        "spread", "verdict", "confidence", "reason", "action",
        "allowed_statement"])
    w.writeheader()
    w.writerow(dict(compound_id="ok_mol", endpoint="herg", n_total=2,
                    n_in_domain=2, n_measured=0, sources="a;b",
                    n_indep_groups=2, indep_groups="g1;g2", value_used=0.02,
                    unit="probability", spread=0.01, verdict="PASS",
                    confidence="medium", reason="一致", action="",
                    allowed_statement="{n_indep} 个独立方法组预测一致指向 "
                                      "{verdict}（中位 {value} {unit}）"))
r = subprocess.run([PY, "-m", "adt.cli", "report", "--reliability", rel,
                    "--outdir", tmp], cwd=HERE, capture_output=True,
                   text=True, timeout=120)
check("report exit=0", r.returncode == 0, r.stderr[-200:])
concl = io.open(os.path.join(tmp, "conclusions.md"),
                encoding="utf-8").read()
check("模板占位符已填值（无裸 {verdict}）",
      "{verdict}" not in concl and "PASS" in concl)
check("措辞为一致指向级（medium/2组）", "一致指向" in concl)

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
