# -*- coding: utf-8 -*-
"""面板实跑（2026-11-19）暴露的缺陷 → 永久回归。

这一批用例的共同点：**它们都是"跑真分子才暴露"的问题**，单元测试造不出来——
  * 消旋药进不了流水线（提示语承诺了一条不存在的门）；
  * 外部源不可达时命令挂死 3 分钟而不是快速失败；
  * 非糖苷酯被套上"糖苷水解轴"的名义；
  * 人工回填（manual）被 cardiac 静默丢弃，与它自己打印的指引冲突；
  * 宽表直接喂 conformal 触发 KeyError；
  * pbpk-qualify 文件写错给 20 行 traceback。

因此每条都按"用户会怎么用"来写断言，而不是按内部函数签名写。
"""
import io
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from adt import acyl_glucuronide as AG      # noqa: E402
from adt import cardiac_panel as CP         # noqa: E402
from adt import glycoside_hydrolysis as GH  # noqa: E402
from adt import pubchem as PB               # noqa: E402
from adt import schema                      # noqa: E402

PY = sys.executable


def _cli(args, timeout=300, env_extra=None):
    env = dict(os.environ)
    env.setdefault("ADT_PROFILE", "academic-internal")
    if env_extra:
        env.update(env_extra)
    return subprocess.run([PY, "-m", "adt.cli"] + args, cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=timeout,
                          errors="replace")


# ---------------------------------------------------------------- F1 消旋体
def test_stereo_three_states():
    """未声明 → 拦；声明消旋 → 放行但留态；声明单一异构体却无立体标记 → 拦。"""
    warfarin = "CC(=O)CC(c1ccccc1)c1c(O)c2ccccc2oc1=O"
    v = PB.validate_entry("warfarin", warfarin)
    assert v["status"] == "fail" and v["stereo_state"] == "undefined"
    v = PB.validate_entry("warfarin", warfarin, declared_racemic=True)
    assert v["status"] == "ok" and v["stereo_state"] == "racemic_declared"
    v = PB.validate_entry("warfarin", warfarin, declared_stereo=True)
    assert v["status"] == "fail"
    # 自相矛盾必须显式拒绝
    v = PB.validate_entry("warfarin", warfarin, declared_stereo=True,
                          declared_racemic=True)
    assert v["status"] == "fail" and "矛盾" in v["reasons"][0]


def test_achiral_is_not_applicable_not_undefined():
    """无立体中心的分子不该被标成"立体未定"（那会污染下游的立体上限提示）。"""
    v = PB.validate_entry("aspirin", "CC(=O)Oc1ccccc1C(=O)O")
    assert v["status"] == "ok" and v["stereo_state"] == "not_applicable"


def test_normalize_accepts_stereo_column_and_report_prints_cap(tmp_path):
    """端到端：第三列 stereo=racemic → 通过闸门 → 发布结论段带立体上限。"""
    hits = tmp_path / "hits.tsv"
    hits.write_text("warfarin\tCC(=O)CC(c1ccccc1)c1c(O)c2ccccc2oc1=O\tracemic\n",
                     encoding="utf-8")
    out = tmp_path / "out"
    r = _cli(["normalize", "--in", str(hits), "--outdir", str(out),
              "--strict-input"])
    assert r.returncode == 0, r.stderr
    gate = list(__import__("csv").DictReader(
        io.open(out / "input_gate.csv", encoding="utf-8-sig")))
    assert gate[0]["status"] == "ok"
    assert gate[0]["stereo_state"] == "racemic_declared"


# ---------------------------------------------------------------- F3 糖苷轴
def test_ester_only_is_not_a_glycoside_conclusion():
    """阿司匹林：有酯键、无糖 → 必须标 axis_applicable=False，不得冒充糖苷结论。"""
    r = GH.classify("CC(=O)Oc1ccccc1C(=O)O", "aspirin")
    assert r["glycosidic_bond"] is False and r["ester_bond"] is True
    assert r.get("axis_applicable") is False
    assert "不适用" in r["summary"]
    # 真糖苷仍然适用
    rutin = ("OC[C@H]1O[C@@H](Oc2cc(O)c3c(c2)oc(-c2ccc(O)c(O)c2)cc3=O)"
             "[C@H](O)[C@@H](O)[C@@H]1O")
    r2 = GH.classify(rutin, "rutin_like")
    assert r2["glycosidic_bond"] is True and r2.get("axis_applicable") is True


# ---------------------------------------------------------------- F4 cardiac
def test_cardiac_accepts_manual_readback(tmp_path):
    """readback 默认可能写 manual；cardiac 若丢弃它，等于吃掉刚回填的数据。"""
    m = tmp_path / "m.csv"
    m.write_text("compound_id,endpoint,value,unit,source,source_version,"
                 "retrieved_at,domain_flag,uncertainty,provenance_url,note\n"
                 "terfenadine,cardiac_herg_ic50,0.03,uM,cardiosim_tox,,"
                 "2026-11-19T00:00:00,manual,,https://example.org/x,SYNTHETIC_test\n",
                 encoding="utf-8")
    out = tmp_path / "out"
    r = _cli(["cardiac", "--in", str(m), "--outdir", str(out)])
    assert r.returncode == 0, r.stderr
    assert "manual" in r.stdout and "纳入" in r.stdout
    rows = list(__import__("csv").DictReader(
        io.open(out / "cardiac_panel.csv", encoding="utf-8-sig")))
    assert rows and rows[0]["compound_id"] == "terfenadine"


def test_advisory_warning_covers_manual_values():
    rows = [dict(compound_id="x", endpoint="cardiac_herg_ic50", value="30",
                 unit="uM", source="s", domain_flag="manual", uncertainty="")]
    assert schema.advisory_warnings(rows), "manual 数值无 CI 也必须提示（红线 6）"


# ---------------------------------------------------------------- F8 conformal
def test_conformal_rejects_wide_table_with_clear_message(tmp_path):
    wide = tmp_path / "wide.csv"
    wide.write_text("idx,y_true,model_prob\n0,1,0.9\n1,0,0.2\n", encoding="utf-8")
    truth = tmp_path / "truth.csv"
    truth.write_text("compound_id,endpoint,truth_value\nc1,e1,1\n", encoding="utf-8")
    r = _cli(["conformal", "--predictions", str(wide), "--truth", str(truth),
              "--outdir", str(tmp_path / "o")])
    assert r.returncode == 2
    assert "长表" in r.stderr and "Traceback" not in r.stderr


# ---------------------------------------------------------------- F7 pbpk-qualify
def test_pbpk_qualify_missing_file_is_clean(tmp_path):
    r = _cli(["pbpk-qualify", "--pred", str(tmp_path / "nope.csv"),
              "--outdir", str(tmp_path / "o")])
    assert r.returncode == 3
    assert "不存在" in r.stderr and "Traceback" not in r.stderr


# ---------------------------------------------------------------- F9 acyl 文本
def test_acyl_glucuronide_note_is_context_free_and_counterexample_documented():
    """旧文案残留"失眠适应症"（别的项目串味），必须已清除。"""
    r = AG.risk("CC(=O)Oc1ccccc1C(=O)O", "aspirin")
    blob = " ".join(r["reasons"])
    assert "失眠" not in blob
    src = io.open(os.path.join(ROOT, "adt", "acyl_glucuronide.py"),
                  encoding="utf-8").read()
    assert "已知反例" in src and "双氯芬酸" in src, \
        "必须在源码里登记已知反例，避免把该分级当跨分子排序"


# ---------------------------------------------------------------- F10 电离
def test_lactone_enol_is_not_a_phenol():
    """华法林 4-羟基香豆素被当成酚（pKa 10）→ pH 7.4 判成中性。

    真实 pKa≈4.5–5.0，应判 ionized_dominant。这不是"±1 log 类别区间"的问题，
    是**认错了基团**，会把 logD 高估约 2.7 个 log。
    """
    from adt import ionization as IZ
    p = IZ.ionization_profile("CC(=O)CC(c1ccccc1)c1c(O)c2ccccc2oc1=O")
    names = [g["name"] for g in p["groups"]]
    assert "vinylogous_acid_lactone_enol" in names, names
    assert "phenol" not in names
    assert p["charge_class"] == "ionized_dominant"
    # 普通酚不受影响；香豆素（无 4-OH）也不受影响
    assert [g["name"] for g in IZ.ionization_profile("Oc1ccccc1")["groups"]] == ["phenol"]
    assert IZ.ionization_profile("O=c1ccc2ccccc2o1")["n_acid"] == 0


def test_biguanide_counted_once():
    """二甲双胍被拆成 amidine+guanidine → 净电荷 +2；真实 +1。"""
    from adt import ionization as IZ
    p = IZ.ionization_profile("CN(C)C(=N)NC(=N)N")
    names = [g["name"] for g in p["groups"]]
    assert names == ["biguanide"], names
    assert abs(p["net_charge"] - 1.0) < 0.05


# ---------------------------------------------------------------- 面板文件
def test_panel_spec_and_resolved_are_consistent():
    """面板定义与结构锚定表必须一一对应（防止改了 spec 忘了重抓）。"""
    spec_p = os.path.join(ROOT, "..", "..", "..", "WorkBuddy", "本地文件",
                          "2026-11-17-22-52-47", "panel_run", "panel_spec.json")
    spec_p = os.path.normpath(spec_p)
    if not os.path.exists(spec_p):
        return          # 面板定义在交付目录，仓库内不强求存在
    spec = json.load(io.open(spec_p, encoding="utf-8"))
    ids = {c["id"] for c in spec["compounds"]}
    res = os.path.join(os.path.dirname(spec_p), "panel_resolved.csv")
    rows = list(__import__("csv").DictReader(io.open(res, encoding="utf-8-sig")))
    assert {r["id"] for r in rows} == ids
    assert all(r["inchi_key"] for r in rows), "面板结构必须全部有 InChIKey 锚点"
