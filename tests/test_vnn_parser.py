# -*- coding: utf-8 -*-
"""C65 回归：vNN checkjob 解析 + 就绪判据（离线，用真实结果页夹具）。

背景（2026-10-28 实测）：结果页在**不同分子数**下布局不同——
14 分子是扁平 33-td 行，2 分子是嵌套表。项目脚本用正则 `<table.*?</table>`
数结果行，遇嵌套表只数到外层 → 2 分子作业被判"还在计算"，实测白等 6 分钟
（结果其实早已就绪）。本测试把三条教训固化成断言：

  1) 正则数表法在 2 分子页上得 0 行（复现 bug）
  2) parse_checkjob 在同一页得 2 行（正确判据）
  3) NoPrediction 必须落 out_of_domain 且不带数值；Yes/No 落 1/0 类别

跑法: python tests/test_vnn_parser.py
"""
import csv
import gzip
import io
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from adt.adapters.vnn import ENDPOINTS, parse_checkjob, VnnAdapter   # noqa: E402

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


FIX = os.path.join(HERE, "tests", "fixtures", "vnn_checkjob_2mol.html.gz")
if not os.path.exists(FIX):
    print("skip  夹具缺失：%s（无法复现 C65）" % FIX)
    sys.exit(0)

tmp = tempfile.mkdtemp(prefix="vnnfix_")
html_path = os.path.join(tmp, "page.html")
with gzip.open(FIX, "rb") as f, open(html_path, "wb") as out:
    shutil.copyfileobj(f, out)
html = open(html_path, encoding="utf-8", errors="replace").read()

print("== 1) 复现旧 bug：正则数 33-td 行在 2 分子页上失效 ==")
n33 = 0
for t in re.findall(r"<table.*?</table>", html, re.S):
    for tr in re.findall(r"<tr.*?</tr>", t, re.S):
        if len(re.findall(r"<td", tr)) == 33:
            n33 += 1
check("正则法得 0 行（若为 0 说明确实会误判'未就绪'）", n33 == 0, "n33=%d" % n33)

print("== 2) 正确判据：parse_checkjob 能拿到 2 行 ==")
rows = parse_checkjob(html)
check("解析出 2 行", len(rows) == 2, str([r["ID"] for r in rows]))
ids = {r["ID"] for r in rows}
check("化合物名正确", ids == {"APAP", "M_TRUE"}, str(ids))
check("15 个端点齐全", all(all(ep in r for ep in ENDPOINTS) for r in rows))
apap = [r for r in rows if r["ID"] == "APAP"][0]
m = [r for r in rows if r["ID"] == "M_TRUE"][0]
check("APAP DILI=Yes（已知 DILI 阳性）", apap["DILI"] == "Yes", apap["DILI"])
check("真 M DILI=NoPrediction（域外，与既有结论一致）",
      m["DILI"] == "NoPrediction", m["DILI"])
check("真 M MRTD=251", m["MRTD"] == "251", m["MRTD"])

print("== 3) 长表转换：类别 / NoPrediction / 参照端点 ==")
ad = VnnAdapter(verbose=False)
meas, unmapped = ad.to_measurements(rows, "https://example/checkjob")
by = {(x["compound_id"], x["endpoint"]): x for x in meas}
check("APAP dili 入长表为 1（class）",
      by[("APAP", "dili")]["value"] == 1 and by[("APAP", "dili")]["unit"] == "class",
      str(by.get(("APAP", "dili"))))
check("真 M dili 为 out_of_domain 且不带数值",
      by[("M_TRUE", "dili")]["domain_flag"] == "out_of_domain"
      and by[("M_TRUE", "dili")]["value"] == "",
      str(by.get(("M_TRUE", "dili"))))
check("NoPrediction 的 note 说明域外",
      "NoPrediction" in by[("M_TRUE", "dili")]["note"])
check("MRTD -> vnn_mrtd（参照端点，数值保留）",
      by[("M_TRUE", "vnn_mrtd")]["value"] == 251.0,
      str(by.get(("M_TRUE", "vnn_mrtd"))))
# v2.3：15 个端点全部进入长表（3 质量 + 12 参照），不再有未映射端点
check("每分子 15 个端点（3 质量 + 12 参照）",
      all(sum(1 for k in by if k[0] == cid) == 15 for cid in ("APAP", "M_TRUE")),
      str({cid: sum(1 for k in by if k[0] == cid) for cid in ("APAP", "M_TRUE")}))
check("不再有未映射端点", unmapped == [], str(unmapped))
check("CYP1A2 进入源中立参照端点（cyp1a2_inhibition）",
      ("APAP", "cyp1a2_inhibition") in by, str([k[1] for k in by if k[0] == "APAP"]))
check("MMP 升级为质量端点 mmp（v2.3.1）", ("M_TRUE", "mmp") in by,
      str([k[1] for k in by if k[0] == "M_TRUE"]))
check("mmp 的 note 标明来源为 vNN MMP",
      "vNN MMP" in by[("M_TRUE", "mmp")]["note"], by[("M_TRUE", "mmp")]["note"])

print("== 4) C67：原始 15 端点宽表必须留档（不参与裁决 ≠ 不保存）==")
rawdir = os.path.join(tmp, "raw")
ad.raw_dir = rawdir          # 生产环境由 CLI 传入 outdir；测试里显式设置
ad.save_raw(rows, html, "https://x/checkjob.xhtml?myjob=abcdef1234567890", "j1")
wide = os.path.join(rawdir, "vnn_wide.csv")
check("vnn_wide.csv 落盘", os.path.exists(wide))
wr = list(csv.DictReader(io.open(wide, encoding="utf-8-sig")))
check("宽表 2 行", len(wr) == 2, str(len(wr)))
check("宽表含全部 15 端点列",
      all(ep in wr[0] for ep in ENDPOINTS), str(list(wr[0])[:6]))
wmap = {r["ID"]: r for r in wr}
check("未映射端点也在宽表里（APAP CYP1A2=No，真 M=NoPrediction）",
      wmap["APAP"]["CYP1A2"] == "No" and wmap["M_TRUE"]["CYP1A2"] == "NoPrediction",
      "%s / %s" % (wmap["APAP"]["CYP1A2"], wmap["M_TRUE"]["CYP1A2"]))
check("结果页 HTML 同时留档",
      any(f.startswith("vnn_checkjob_") and f.endswith(".html")
          for f in os.listdir(rawdir)), str(os.listdir(rawdir)))

print("== 5) 解析器降级：lxml 缺失时必须退回 html.parser ==")
# 背景（2026-10-31 干净机复现）：requirements.lock 曾漏写 lxml，按 lock 装完的环境里
# BeautifulSoup(html, "lxml") 抛 FeatureNotFound，vnn 适配器直接崩。现已补清单 +
# 代码降级；此段把"降级后结果与 lxml 完全一致"钉成断言，防止分支再次悄悄烂掉。
import bs4                                            # noqa: E402
from adt.adapters.vnn import _make_soup                # noqa: E402

rows_native = parse_checkjob(html)                     # 真实环境路径（有 lxml 走 lxml）
real_bs = bs4.BeautifulSoup


def _no_lxml(h, parser=None, **kw):
    if parser == "lxml":
        raise Exception("FeatureNotFound: simulated (lxml not installed)")
    return real_bs(h, parser, **kw)


bs4.BeautifulSoup = _no_lxml
try:
    rows_fallback = parse_checkjob(html)               # 强制走 html.parser
    tiny = _make_soup("<table><tr><td>x</td></tr></table>")
    soup_ok = tiny.find("td").get_text() == "x"
finally:
    bs4.BeautifulSoup = real_bs

check("lxml 不可用时自动降级 html.parser（不抛异常）", soup_ok)
check("降级后解析结果与默认路径完全一致", rows_fallback == rows_native,
      "%d vs %d 行" % (len(rows_fallback), len(rows_native)))


def _always_fail(h, parser=None, **kw):
    raise Exception("no tree builder available")


bs4.BeautifulSoup = _always_fail
try:
    raised = False
    try:
        _make_soup("<p>x</p>")
    except RuntimeError:
        raised = True
finally:
    bs4.BeautifulSoup = real_bs
check("无任何可用解析器时显式报 RuntimeError（不静默返回空表）", raised)

print()
print("passed %d / failed %d" % (PASS, len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL OK")
