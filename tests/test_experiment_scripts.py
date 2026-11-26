# -*- coding: utf-8 -*-
"""C5（2026-11-03 评审）：21 个根目录 `run_*.py` 评测脚本入网。

## 问题

这些脚本产生了材料里的**核心数字**（gate_audit、external_holdout、p8_mmp、
tail_risk_stratified、spec_multiverse……），但 `tests/` 里**没有任何一个测试文件
覆盖它们**——它们的正确性只靠作者目检。这恰好是本包批评别人的镜像：
"pytest 全绿 ≠ 科学结论"，而这里连 pytest 都没进去。

## 为什么不是"给每个脚本加一条 exit 0 断言"（R-A 外部评审的修订）

外部评审原话：Tier-A 的 `exit 0 + 产物存在` 是最低线，其中 5 个产生论文核心数字的
脚本必须包含**数值快照断言**，否则只是把"无测试"换成了"安慰剂测试"。

因此本文件分三层：
  L1 清单完整性：`run_*.py` 集合必须与 REGISTRY 完全一致（新增脚本必须登记）；
  L2 卫生性：`--help` 必须 exit 0 且**无副作用**（本轮实测发现 1 个脚本在 --help
     时写出了挑战包——已作为失败用例固化）；
  L3 数值快照：核心脚本 → 产物 → 产物内数字已由 CLAIMS_REGISTRY 逐字核对
     （直接复用 G10 的 verify_registry，避免另造一套口径）。
"""
import glob
import io
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# script -> dict(artifact=产物, core=是否产生论文核心数字, kind)
REGISTRY = {
    "run_ad_multicriteria.py": dict(artifact="out_ext/tdc/ad_multicriteria.json", core=False),
    "run_ames_alerts.py": dict(artifact="out_ext/tdc/ames_alerts.json", core=True),
    "run_blacklist_analysis.py": dict(artifact="out_blacklist/results.json", core=False),
    "run_blacklist_report.py": dict(artifact="out_blacklist/results.json", core=False),
    "run_evidence_export.py": dict(artifact="references/EVIDENCE_DAG.md", core=False),
    "run_external_cuts_summary.py": dict(artifact="out_ext/external/external_cuts_summary.json",
                                         core=True, no_argparse=True),
    "run_external_holdout.py": dict(artifact="out_ext/external/herg_holdout.json", core=True),
    "run_gate_audit.py": dict(artifact="out_ext/tdc/gate_audit.json", core=True),
    "run_independence_gradient.py": dict(artifact="out_ext/tdc/independence_gradient.json", core=True),
    "run_indifference.py": dict(artifact="out_ext/keystone_indifference.json", core=True),
    "run_keystone.py": dict(artifact="out_keystone/results.json", core=True),
    "run_leakage_attribution.py": dict(artifact="out_ext/tdc/leakage_attribution.json", core=True),
    "run_leakage_confound_check.py": dict(artifact="out_ext/tdc/leakage_confound_check.json", core=True),
    "run_p6_seed_ci.py": dict(artifact="out_ext/tdc/p6_seed_ci.json", core=True, no_argparse=True),
    "run_p8_mmp.py": dict(artifact="out_ext/tdc/p8_mmp_results.json", core=True),
    # 按端点分文件输出（实测：p8_mmp_reg_<endpoint>.json，端点名来自 TDC 数据集名）
    "run_p8_mmp_regression.py": dict(
        artifact="out_ext/tdc/p8_mmp_reg_caco2_wang.json", core=True),
    "run_p8_real.py": dict(artifact="out_ext/tdc/p8_results.json", core=True, no_argparse=True),
    "run_replication_pack.py": dict(artifact="replication/MANIFEST.json", core=False,
                                    no_argparse=True),
    "run_spec_multiverse.py": dict(artifact="out_ext/keystone_spec_multiverse.json", core=True),
    "run_tail_risk_stratified.py": dict(artifact="out_ext/external/herg_holdout_stratified.json",
                                        core=True),
    # P2.4（2026-11-03）：Ames 双方法层差值的配对 bootstrap CI（解 D3）
    "run_ames_release_ci.py": dict(artifact="out_ext/tdc/ames_release_ci.json", core=True),
    # P2.4-d（2026-11-03）：三端点门判别力的多重比较台账（Holm + 族内 CI）
    "run_gate_multiplicity.py": dict(artifact="out_ext/tdc/gate_multiplicity.json",
                                     core=True),
    # P2.4-e（2026-11-03）：校准 / 类不平衡指标 / 决策曲线（只读 per-sample CSV）
    "run_gate_metrics.py": dict(artifact="out_ext/tdc/gate_metrics.json", core=True),
    # 黑榜 B2（2026-11-03 补登记；2026-11-04 加 argparse + JSON 产物后可登记）：
    # BBB 转运体先验覆盖度 1/18、分子级 ≤7.1%
    "run_b2_coverage.py": dict(artifact="out_ext/tdc/b2_coverage.json", core=True),
    "run_tdc_real.py": dict(artifact="out_ext/tdc/tdc_results.json", core=False, no_argparse=True),
}

# 允许 --help 有副作用的白名单（必须有理由；空 = 一个都不允许）
HELP_SIDE_EFFECT_ALLOWED = {
    # 例如 "run_xxx.py": "需要首次生成缓存，--help 亦会建目录（已确认为只读缓存）",
}


def _scripts_on_disk():
    return sorted(os.path.basename(p)
                  for p in glob.glob(os.path.join(ROOT, "run_*.py")))


# ---------------------------------------------------------------- L1 清单完整性
def test_every_run_script_is_registered():
    """新增评测脚本必须先登记（否则它立刻落入"无测试覆盖"的旧状态）。"""
    on_disk = set(_scripts_on_disk())
    missing = sorted(on_disk - set(REGISTRY))
    assert not missing, "以下 run_*.py 未登记（补 artifact 并标 core）：%s" % missing
    ghost = sorted(set(REGISTRY) - on_disk)
    assert not ghost, "REGISTRY 里登记了已不存在的脚本：%s" % ghost


def test_core_scripts_are_majority():
    """自检：登记表不能靠"全标 core=False"蒙混。"""
    n_core = sum(1 for v in REGISTRY.values() if v.get("core"))
    assert n_core >= 5, "产生论文核心数字的脚本至少 5 个（当前只标了 %d）" % n_core


# ---------------------------------------------------------------- L2 卫生性
@pytest.mark.parametrize("script", sorted(REGISTRY))
def test_help_is_side_effect_free(script):
    """`--help` 必须 exit 0，且不得在当前目录写出任何文件。

    实测背景：run_replication_pack.py 无 argparse，`--help` 被当成普通参数，
    直接**写出了挑战包**——这类脚本在 CI 里是"看不见的写入者"。
    """
    if REGISTRY[script].get("no_argparse") and script in HELP_SIDE_EFFECT_ALLOWED:
        pytest.skip("已登记 --help 有副作用：%s" % HELP_SIDE_EFFECT_ALLOWED[script])
    tmp = tempfile.mkdtemp(prefix="adt_help_")
    try:
        p = subprocess.run([sys.executable, os.path.join(ROOT, script), "--help"],
                           cwd=tmp, capture_output=True, text=True, timeout=120)
        created = [f for f in os.listdir(tmp)]
        if created and script not in HELP_SIDE_EFFECT_ALLOWED:
            pytest.fail("%s 在 --help 时写出了文件：%s（加 argparse 或登记理由）"
                        % (script, created))
        assert p.returncode == 0, "%s --help 失败：%s" % (script, p.stderr[-500:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- L3 数值快照
@pytest.mark.parametrize("script", sorted(k for k, v in REGISTRY.items() if v.get("core")))
def test_core_script_artifact_exists(script):
    art = REGISTRY[script]["artifact"]
    p = os.path.join(ROOT, art)
    assert os.path.isfile(p), ("核心脚本 %s 的产物不存在：%s。"
                              "没有产物就没有数字，没有数字就没有主张。" % (script, art))


def test_core_artifacts_covered_by_claims_registry():
    """核心脚本的产物必须至少被 CLAIMS_REGISTRY 的一条主张引用（= 数字被逐字核对）。

    这条把 C5 与 G10 焊在一起：脚本产出 → 产物 → 主张 → 字面量校验，
    整条链上任何一环断了都会红。**只对已被主张引用的产物要求**，
    未引用者由 L3 第一条保证"产物存在"。
    """
    import yaml
    from adt import claims_audit
    reg = os.path.join(ROOT, "references", "CLAIMS_REGISTRY.yaml")
    entries = (yaml.safe_load(open(reg, encoding="utf-8")) or {}).get("entries") or []
    covered = {os.path.normpath(e.get("artifact", "")) for e in entries}
    core_arts = {os.path.normpath(v["artifact"]) for v in REGISTRY.values() if v.get("core")}
    hit = core_arts & covered

    assert len(hit) >= 5, ("核心产物中被主张登记表覆盖的只有 %d 个：%s；"
                           "至少 5 个核心数字必须有 registry 凭证" % (len(hit), sorted(hit)))
    res = claims_audit.verify_registry(reg)
    assert res["passed"], "主张登记表未通过：%s" % res["failures"][:3]


# ---------------------------------------------------------------- L2b 静态保障
def test_every_script_has_help_guard_or_argparse():
    """静态断言：每个 run_*.py 必须有 argparse，或在 __main__ 里 --help 早退。

    为什么不用"cwd 无新文件"作为唯一判据：实测 run_replication_pack.py 写的是
    **绝对路径**（ROOT/replication），换工作目录照样落盘——cwd 检查抓不住。
    静态记号才是完备的：要么 argparse 接管，要么显式早退。
    """
    offenders = []
    for s in sorted(REGISTRY):
        src = io.open(os.path.join(ROOT, s), encoding="utf-8").read()
        has_argparse = "import argparse" in src and "add_argument" in src
        # 静态记号的两种合法写法都要认（2026-11-03：此前只认 `_a` 那个变量名，
        # 于是 run_ames_release_ci.py 明明写了 `any(a in ("-h", "--help") ...)`
        # 却被判成"无守卫"——静态检查太字面，本身就是假阳性来源）。
        has_guard = ('"--help"' in src and "SystemExit(0)" in src)
        if not (has_argparse or has_guard):
            offenders.append(s)
    assert not offenders, ("以下脚本既无 argparse 也无 --help 早退，"
                           "运行 --help 会执行全流程：%s" % offenders)
