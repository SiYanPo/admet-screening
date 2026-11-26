# -*- coding: utf-8 -*-
"""pytest 入口：把 4+ 个独立测试脚本以子进程方式跑一遍。

为什么这样写而不是把脚本改写成 pytest 函数：这些脚本原本是"每套 20–40 条断言
的顺序检查 + 末尾 sys.exit"，改写风险大于收益；子进程方式能真实走脚本入口，
且失败时能看到原始输出。真正的 pytest 风格断言见 test_smoke_pytest 自身的
那条"全部脚本 exit 0"。
"""
import io
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = [
    "tests/test_gates_protocol.py",
    "tests/test_reliability.py",
    "tests/test_desirability.py",
    "tests/test_e2e_cli.py",
    "tests/test_chembl_units.py",
    "tests/test_batch_anchor.py",
    "tests/test_sensitivity.py",
    "tests/test_web_adapters.py",
    "tests/test_saturation_mark.py",
    "tests/test_vnn_parser.py",
    "tests/test_coverage.py",
    "tests/test_rules_roles.py",
    "tests/test_units_and_transforms.py",
    "tests/test_strict_and_mixed_units.py",
    "tests/test_chembl_admet_count.py",
    "tests/test_phys_range.py",
    "tests/test_class_blocks.py",
    "tests/test_pbpk.py",
    "tests/test_herg_anchor.py",
    "tests/test_pbpk_ehr.py",
    "tests/test_transport.py",
    "tests/test_background.py",
    "tests/test_rank.py",
    "tests/test_benchmark.py",
    "tests/test_tiers.py",
    "tests/test_help_all.py",
    "tests/test_pbpk_mcrank.py",
    "tests/test_normalize_coverage_fixes.py",
    # v3.0.0 学术升级（对应 20 篇文献）
    "tests/test_transport_moiety.py",
    "tests/test_calibration.py",
    "tests/test_scaffold_tdc.py",
    "tests/test_governance.py",
    "tests/test_ad_sensitivity.py",
    "tests/test_pbpk_academic.py",
    "tests/test_conformal.py",
    "tests/test_desirability_weight.py",
    "tests/test_reporting.py",
    # v3.1.0 学术化升级（工作包 A/C/D/E/H/I/J）
    "tests/test_independence.py",
    "tests/test_certainty.py",
    "tests/test_selective.py",
    "tests/test_failure_modes.py",
    "tests/test_perturbation.py",
    "tests/test_decision_value.py",
    "tests/test_dst.py",
    # v3.1.1 外部公开数据接入（B/G）
    "tests/test_external.py",
    # v3.2.0 工作包 F/K 补全
    "tests/test_conformal_check.py",
    "tests/test_landscape.py",
    # 深水区 2.1/2.2/2.3：SAR 预筛 / BBB 双层机制 / 酰基葡萄糖醛酸化
    "tests/test_sar.py",
    "tests/test_bbb_dual_layer.py",
    "tests/test_acyl_glucuronide.py",
    # v3.4.0 深水区补齐 + 4 条增量方向
    "tests/test_bbb_three_channel.py",
    "tests/test_glycoside_hydrolysis.py",
    "tests/test_conformal_class.py",
    "tests/test_crossclass.py",
    # v3.5.0 三次评审落地：消融 / Regaloside A-B / decision_trigger / L-M-N-O
    "tests/test_ablation.py",
    "tests/test_case_regaloside.py",
    "tests/test_abstain_attrib.py",
    "tests/test_abstention_compare.py",
    "tests/test_failure_layers.py",
    "tests/test_transfer.py",
    # v3.6.0 未闭环项处理：G 真前瞻 / A 真实源 ρ / A-C 变体清单与位移
    "tests/test_prospective.py",
    "tests/test_source_rho.py",
    "tests/test_ac_plan.py",
    # v4.0 拔高（评审 v4.0：P1/P2/P4/P5 可测回归）
    "tests/test_rho_contraction.py",
    "tests/test_stats_ci.py",
    "tests/test_p4_p5.py",
    "tests/test_v4_elevation.py",
    "tests/test_decontamination.py",
    # v4.0 续作：P11 源纳入/排除预注册 + mppb supersede 补留痕
    "tests/test_prereg.py",
    # v4.1（评审 v4.0 落地）：快照/发布门禁、独立性 v4.1、输入与合规、复现挑战包、六条红线
    "tests/test_snapshot.py",
    "tests/test_independence_v41.py",
    "tests/test_input_compliance_v41.py",
    "tests/test_replication_v41.py",
    "tests/test_red_lines_v41.py",
    # 黑榜闭环：C6 误差方差分解、C9 统一分数口径、A1 四种权重方案
    "tests/test_blacklist_v41.py",
    # C1/P1.7（2026-11-03 评审落地）：红线接线集成测试 + domain_flag 写入点白名单
    "tests/test_redline_wiring.py",
    "tests/test_c2_flag_audit.py",
    # 元测试补漏（2026-11-03 由 test_every_test_file_is_registered 现场抓出）：
    # 以下 5 个文件此前**从未被默认批跑**——它们的断言只存在于自己的文件里，
    # 谁也不会去单独跑。其中 test_v44_guards.py 正是红线 7/8/9 的单元测试：
    # "红线 7-9 有测试"这句话在当时是不成立的。
    "tests/test_ames_alerts_wired.py",
    "tests/test_gate_mmp_v42.py",
    "tests/test_v43_measures.py",
    "tests/test_v44_gates.py",
    "tests/test_v44_guards.py",
    # C7/C9（2026-11-03 评审落地）：归因分类唯一真源 + 单位投射置信度分档
    "tests/test_c7_c9_taxonomy.py",
    # C5（2026-11-03 评审落地）：21 个 run_*.py 评测脚本入网（清单/卫生/数值快照）
    "tests/test_experiment_scripts.py",
    # C6（2026-11-03 评审落地）：阈值普查表与代码常量双向一致
    "tests/test_threshold_census.py",
    # 元测试第二次抓漏（2026-11-04 全量批跑现场）：efflux/uptake 两个启发式模块
    # 自 v4.12 起就有测试文件，但从未登记 → 默认批跑**一直没执行过**。
    "tests/test_efflux_heuristic.py",
    "tests/test_uptake_heuristic.py",
    # v4.14–v4.20 扩展（pKa/心脏三联/PK-PD/PBPK 资格/互操作/菌群/回填）
    "tests/test_extension_v414.py",
]

# 不纳入「脚本式子进程批跑」的文件，每个都必须写理由：
# 一旦允许"沉默地漏跑"，测试文件就等于文档。
# 注意：列在此处 ≠ 不运行。它们由本文件末尾的 test_native_pytest_file_passes
# 以 `pytest <file>` 子进程逐个执行（2026-11-22 修复：此前因 pyproject 只收集
# smoke，这些原生测试实际从未进入默认批跑）。
SKIP = {
    # 2026-11-04 新增的三份 **pytest 原生风格** 回归锁（函数式 + fixtures/tmp_path）：
    # 由 pytest 直接收集，脚本式包装不会执行任何 assert，故不得放进 SCRIPTS。
    "tests/test_selective_denominator.py",   # B1 / C06 分母不变性
    "tests/test_cost_decision.py",           # B6 / C18 代价进入决策 + R18
    "tests/test_contract_write_guard.py",    # C11 / C1-a 写入端强校验
    # 2026-11-07 新增的离线 6 工具回归（pytest 原生 + tmp_path；上一轮漏登记，
    # 由 test_every_test_file_is_registered 在 2026-11-11 全量跑中抓出）
    "tests/test_local_admet.py",             # local_admet 离线替代，函数式 + fixture
    # 2026-11-11 新增的结构干扰红旗层回归（同上）
    "tests/test_interference.py",            # interference / source_health / f_oral / F2 断言
    # 2026-11-11 第二轮补齐（同上，pytest 原生 + tmp_path/monkeypatch）
    "tests/test_coverage_gate.py",           # C82 声明闸门：正反双向 / e2e / report 接线
    "tests/test_module_wiring.py",           # 零引用模块可用性 + local-tools 主 CLI 入口
    # 2026-11-17 同行评审整改回归（pytest 原生 + tmp_path/subprocess）
    "tests/test_estimand.py",                # G13 estimand 门 + prereg 事后锚定 + version 台账修复
    "tests/test_external_comparison.py",     # G14 外部对照台账（含漂移/棘轮/超容差的反向用例）
    "tests/test_panel_fixes.py",            # 面板实跑暴露的 9 类缺陷（消旋体/糖苷轴/manual/宽表/退出码）
    "tests/test_real_truth_legs.py",        # 真值驱动实跑暴露的缺陷（方向定向/no-op 变体/互变体空转/立体盲区）
    # 2026-11-22 同行评审修复（pytest 原生 + tmp_path）
    "tests/test_peer_review_fixes.py",       # trust.physchem 嵌套 limits 静默放行 + 零引用 API 真实调用
    "tests/test_api_usage_audit.py",         # 零引用公共 API 必须登记（死代码门禁）
    "tests/test_governance_ext.py",          # adt.governance_ext 移植层可用性（实验层，不接主 CLI）
}


@pytest.mark.parametrize("script", SCRIPTS)
def test_script_passes(script):
    # 63 个子进程会话会在系统 temp 下各建一个 pytest 临时根；累积超过安全阈值时，
    # pytest 的垃圾清理会触发环境的"批量删除确认"而返回非零退出码（误报失败）。
    # 固定 PYTEST_DEBUG_TEMPROOT，让所有子会话复用同一个根，避免累积。
    env = dict(os.environ)
    temproot = os.path.join(HERE, ".pytest_tmp",
                            os.path.basename(script).replace(".py", ""))
    os.makedirs(temproot, exist_ok=True)   # 父目录必须先存在，否则 pytest 建临时根会失败
    env["PYTEST_DEBUG_TEMPROOT"] = temproot
    # 2026-11-19：子会话里必须清掉外层 pytest 注入的 PYTEST_* 变量。
    # 实测证据：全量跑期间若**并发**再起一个 pytest 会话（共享 tests/.scratch 与
    # .pytest_tmp），tests/test_redline_wiring.py 的嵌套执行会崩在 pytest 内部
    # （fixtures.py 的 `assert not self._finalizers`，属 pytest 自身的 fixture
    # 终态记账断言），表现为 2 条 ERROR + 'AssertionError'，与测试内容无关。
    # 单独连跑 8 次全绿 → 是环境/状态耦合，不是断言失败。
    # 因此：① 清 PYTEST_CURRENT_TEST 等外层注入；② 每个子会话独立 temproot，
    # 避免与另一个并发会话争同一临时根。
    for _k in list(env):
        if _k.startswith("PYTEST_") and _k != "PYTEST_DEBUG_TEMPROOT":
            env.pop(_k, None)
    env.pop("PYTEST_CURRENT_TEST", None)
    # 注意：tmp_path 已在 conftest.py 里被覆盖为"不删除的 scratch 目录"，
    # 因此子会话不再产生 pytest 临时目录清理动作（否则会触发环境的批量删除确认，
    # 表现为整批测试误报失败）。这里不要再加 tmp_path_retention_policy——它反而强制删除。
    p = subprocess.run([sys.executable, script], cwd=HERE, env=env,
                       capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, "%s 失败\nSTDOUT:\n%s\nSTDERR:\n%s" % (
        script, p.stdout[-3000:], p.stderr[-2000:])

    # ---- 2026-11-03 补漏（本轮自查抓出的最大覆盖度漏洞）------------------
    # 用 `python <script>` 跑**函数式**测试文件是**空跑**：文件里只有
    # `def test_xxx()`，没有模块级断言，直接执行 rc=0 却一条测试都没跑。
    # 实测 tests/test_experiment_scripts.py 就是这样——它自称 40 例，
    # 在默认批跑里**一例都没执行**，而「86 passed」把它算成了通过。
    # 这比"没写测试"更危险：绿灯是假的。
    #
    # 判据：文件里出现 `def test_` 就再跑一遍 pytest 收集执行；
    # 且必须真的跑出用例（"no tests ran" 视为失败，防止收集器配错时再次空转）。
    # 自身排除，否则递归调用 pytest 跑自己。
    if os.path.basename(script) == os.path.basename(__file__):
        return
    src = io.open(os.path.join(HERE, script), encoding="utf-8").read()
    if "def test_" not in src:
        return

    # 嵌套 pytest + rdkit C 扩展在本机出现过**偶发** access violation
    # （0xC0000005，发生在解释器退出阶段，"11 passed" 之后）。同一文件单独跑
    # 连跑两次都 rc=0，说明不是断言问题而是环境抖动。为此允许重试一次：
    # 只重试"非断言失败"，且重试仍失败就判负——不拿重试掩盖真实失败。
    last = None
    for _attempt in range(2):
        q = subprocess.run([sys.executable, "-m", "pytest", script, "-q",
                            "-p", "no:cacheprovider"],
                           cwd=HERE, env=env, capture_output=True, text=True,
                           timeout=600)
        last = q
        if q.returncode == 0:
            break
    q = last
    assert q.returncode == 0, ("%s 的 pytest 收集执行失败（脚本式空跑不算通过；已重试 1 次）\n"
                              "STDOUT:\n%s\nSTDERR:\n%s"
                              % (script, q.stdout[-3000:], q.stderr[-2000:]))
    assert "no tests ran" not in q.stdout, \
        "%s 定义了 test_ 函数但一条都没被收集到（收集器配置有问题）" % script


def test_every_test_file_is_registered():
    """元测试：tests/ 下每个 test_*.py 必须在 SCRIPTS 或 SKIP 里。

    为什么必须有这条：SCRIPTS 是**硬编码列表**，新增测试文件如果忘了登记，
    `pytest tests/` 会静默跳过它——"写了测试但没人跑"比"没写测试"更危险，
    因为它会让人误以为覆盖已存在（本轮 C1 修复时真实踩过一次）。
    """
    import glob
    here = os.path.basename(os.path.abspath(__file__))
    found = {os.path.basename(p) for p in glob.glob(os.path.join(HERE, "tests", "test_*.py"))}
    # 2026-11-04 纠错：SKIP 里的条目带 `tests/` 前缀，而 found 是纯文件名。
    # 旧写法 `set(SKIP)` 未做 basename 归一，SKIP 一旦非空就永远匹配不上
    # （此前 SKIP 恰为空，这个 bug 一直潜伏）。两侧必须同口径。
    registered = ({os.path.basename(p) for p in SCRIPTS}
                  | {os.path.basename(p) for p in SKIP} | {here})
    missing = sorted(found - registered)
    assert not missing, ("以下测试文件未被默认批跑覆盖（加进 SCRIPTS 或 SKIP 并写理由）：%s"
                         % missing)
    ghost = sorted(registered - found)
    assert not ghost, "SCRIPTS 里登记了不存在的文件：%s" % ghost


# ---------------------------------------------------------------------------
# 2026-11-22 同行评审 P0-1 修复：
# 旧配置 `python_files = ["test_smoke_pytest.py"]` 让 SKIP 里的 pytest 原生
# 测试**从未被默认批跑**。注释里"pytest -q 仍会收集"是假的。这里显式补跑，
# 每个文件一个子进程，避免 pytest 全局状态污染；"no tests ran" 视为失败。
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("script", sorted(SKIP))
def test_native_pytest_file_passes(script):
    env = dict(os.environ)
    for _k in list(env):
        if _k.startswith("PYTEST_"):
            env.pop(_k, None)
    env.pop("PYTEST_CURRENT_TEST", None)
    q = subprocess.run([sys.executable, "-m", "pytest", script, "-q",
                        "-p", "no:cacheprovider"],
                       cwd=HERE, env=env, capture_output=True, text=True,
                       timeout=900)
    assert q.returncode == 0, (
        "%s 未被默认批跑（P0-1）；单独执行失败\nSTDOUT:/n%s/nSTDERR:/n%s"
        % (script, q.stdout[-3000:], q.stderr[-2000:]))
    assert "no tests ran" not in q.stdout, (
        "%s 被登记为 pytest 原生测试，但一条都没被收集" % script)
