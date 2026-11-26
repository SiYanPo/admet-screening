# -*- coding: utf-8 -*-
"""工作包 B/G 测试：外部公开数据接入 + 方向对齐 + 基线预测。

跑法: python tests/test_external.py
"""
import csv
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt import external as E  # noqa: E402

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


print("== 1) 数值解析（censor / 千分位 / 百分号） ==")
check("'>5' -> (5,'>')", E._fnum(">5") == (5.0, ">"), str(E._fnum(">5")))
check("'<0.1' -> (0.1,'<')", E._fnum("<0.1") == (0.1, "<"), str(E._fnum("<0.1")))
check("'1,351.1' -> 1351.1", E._fnum("1,351.1")[0] == 1351.1, str(E._fnum("1,351.1")))
check("'abc' -> None", E._fnum("abc")[0] is None, str(E._fnum("abc")))

print("== 2) OpenADMET 规则 ==")
rules = E.openadmet_rules()
check("9 个端点", len(rules) == 9, str(len(rules)))
check("KSOL shape=up", rules["openadmet_ksol"]["shape"] == "up", str(rules["openadmet_ksol"]))
check("LogD window=[0,4]", rules["openadmet_logd"]["window"] == [0.0, 4.0],
      str(rules["openadmet_logd"]))
check("单位显式（HLM mL/min/kg）",
      rules["openadmet_hlm_clint"]["unit"] == "mL/min/kg")

print("== 3) 风险方向对齐 ==")
check("up: 高值 -> 低风险（负分）",
      E.oriented_score(10, {"shape": "up"}) == -10.0)
check("down: 高值 -> 高风险（原值）",
      E.oriented_score(10, {"shape": "down"}) == 10.0)
check("window 内=0", E.oriented_score(2, {"shape": "window", "window": [0, 4]}) == 0.0)
check("window 外=距离", E.oriented_score(6, {"shape": "window", "window": [0, 4]}) == 2.0)

print("== 4) OpenADMET test split -> 契约表 ==")
tmp = tempfile.mkdtemp(prefix="adt_ext_")
try:
    res = E.write_openadmet(os.path.join(HERE, "assets", "external", "openadmet"),
                            tmp, split="test")
    check("2282 个分子", res["meta"]["n_compounds"] == 2282,
          str(res["meta"]["n_compounds"]))
    check("10738 条实测", res["meta"]["n_measurements"] == 10738,
          str(res["meta"]["n_measurements"]))
    check("compounds 文件存在", os.path.exists(res["compounds"]))
    check("truth 文件存在", os.path.exists(res["truth"]))
    tr = list(csv.DictReader(io.open(res["truth"], encoding="utf-8-sig")))
    check("truth 有 PASS/FAIL", {r["truth_class"] for r in tr} >= {"PASS", "FAIL"},
          str({r["truth_class"] for r in tr}))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("== 5) NPASS curated -> 契约表 + 70/30 切分 ==")
tmp2 = tempfile.mkdtemp(prefix="adt_npass_")
try:
    res2 = E.write_npass(os.path.join(HERE, "assets", "external", "npass"), tmp2)
    c = res2["meta"]["counts"]
    check("总 1307 个分子", c["train"]["compounds"] + c["test"]["compounds"] == 1307,
          str(c))
    check("train 916", c["train"]["compounds"] == 916, str(c["train"]))
    check("test 391", c["test"]["compounds"] == 391, str(c["test"]))
    tr2 = list(csv.DictReader(io.open(res2["truth"], encoding="utf-8-sig")))
    check("LD50 truth 有 PASS/FAIL",
          {r["truth_class"] for r in tr2} >= {"PASS", "FAIL"},
          str({r["truth_class"] for r in tr2}))
    check("ADME 子集 76 条", res2["meta"]["n_adme"] == 76,
          str(res2["meta"]["n_adme"]))
finally:
    shutil.rmtree(tmp2, ignore_errors=True)

print("== 6) 基线预测形状（小样本，只测代码路径） ==")
tmp3 = tempfile.mkdtemp(prefix="adt_base_")
try:
    def w(path, cols, rows):
        with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=cols)
            wr.writeheader(); wr.writerows(rows)
    smis = ["C" * (i + 1) for i in range(30)]
    comp_tr = [dict(compound_id="T%d" % i, calc_smiles=s) for i, s in enumerate(smis)]
    comp_te = [dict(compound_id="E%d" % i, calc_smiles=s) for i, s in enumerate(smis[:6])]
    w(os.path.join(tmp3, "compounds_train.csv"),
      ["compound_id", "calc_smiles"], comp_tr)
    w(os.path.join(tmp3, "compounds_test.csv"),
      ["compound_id", "calc_smiles"], comp_te)
    m_tr = [dict(compound_id="T%d" % i, endpoint="e", value=str(14 * (i + 1)),
                 unit="u", domain_flag="measured") for i in range(30)]
    m_te = [dict(compound_id="E%d" % i, endpoint="e", value="0", unit="u",
                 domain_flag="measured") for i in range(6)]
    w(os.path.join(tmp3, "measurements_train.csv"),
      ["compound_id", "endpoint", "value", "unit", "domain_flag"], m_tr)
    w(os.path.join(tmp3, "measurements_test.csv"),
      ["compound_id", "endpoint", "value", "unit", "domain_flag"], m_te)
    rows = E.fit_predict(os.path.join(tmp3, "measurements_train.csv"),
                         os.path.join(tmp3, "measurements_test.csv"),
                         os.path.join(tmp3, "compounds_train.csv"),
                         os.path.join(tmp3, "compounds_test.csv"),
                         method="rdkit", min_train=10)
    check("6 条预测", len(rows) == 6, str(len(rows)))
    check("source=baseline_rdkit", rows and rows[0]["source"] == "baseline_rdkit",
          str(rows[:1]))
    check("predicted 有值", all(r["value"] == r["value"] for r in rows))
finally:
    shutil.rmtree(tmp3, ignore_errors=True)

print()
if FAIL:
    print("FAILED: %d 条 -> %s" % (len(FAIL), FAIL))
    sys.exit(1)
print("ALL PASS (%d assertions)" % PASS)
