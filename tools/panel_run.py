# -*- coding: utf-8 -*-
"""面板全流程跑批器：把 adt 的可执行面按依赖顺序跑一遍，产出运行台账。

设计约束（都是踩过的坑）：
  * **不改产物语义**：跑批器只调用 CLI，不自己算任何判据；
  * **不把失败美化成跳过**：rc 不在期望集合里就是 FAIL，即使命令"看起来"跑完了；
  * **每条失败都留第一手证据**：stdout/stderr 尾部 + 完整日志文件路径；
  * **可达性失败单独归类**（ENV）：BT/PubChem 这类外部源不通不是代码 bug，
    但也不能算通过——它们必须出现在报告里，且写明"0 产物 ≠ 阴性"。

用法：
    python tools/panel_run.py --panel panel_resolved.csv --workdir <dir> \
        --legs A --report <dir>
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PY = sys.executable


# ------------------------------------------------------------------ 面板输入
def load_panel(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_hits(rows, path):
    """id<TAB>smiles<TAB>stereo —— 第三列是本轮新增的显式立体声明。"""
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write("%s\t%s\t%s\n" % (r["id"], r["smiles"], r["stereo"] or "defined"))


# ------------------------------------------------------------------ 步骤定义
class Step:
    def __init__(
        self,
        sid,
        leg,
        argv,
        expect=(0,),
        needs=(),
        produces=(),
        note="",
        timeout=900,
        reuse_ok=False,
    ):
        self.sid = sid
        self.leg = leg
        self.argv = argv  # 可含 {out} {work} {panel} {root}
        self.expect = set(expect)
        self.needs = list(needs)  # 前置产物（run 前检查）
        self.produces = list(produces)  # 应产出（run 后检查；缺失即 FAIL）
        self.note = note
        self.timeout = timeout
        # reuse_ok：产物已存在时承认"复用"，不重复抓取（外部源慢/有配额时必需）。
        # 复用必须显式写进台账，不能假装这次跑过。
        self.reuse_ok = reuse_ok


def build_steps(panel_csv, synthetic_cardiac):
    out = "{out}"
    S = []
    A = lambda sid, argv, **k: S.append(Step(sid, "A", argv, **k))  # noqa: E731
    B = lambda sid, argv, **k: S.append(Step(sid, "B", argv, **k))  # noqa: E731
    C = lambda sid, argv, **k: S.append(Step(sid, "C", argv, **k))  # noqa: E731

    # ---------------- A. 化学腿：面板驱动的全链路 ----------------
    A(
        "A01_normalize",
        ["normalize", "--in", "{work}/hits.tsv", "--outdir", out],
        produces=["compounds.csv", "input_gate.csv"],
        note="结构闸门 + 标准化 + 立体声明",
    )
    A(
        "A02_web_admetlab3",
        [
            "web",
            "--source",
            "admetlab3",
            "--in",
            out + "/compounds.csv",
            "--outdir",
            out,
        ],
        produces=["measurements_admetlab3.csv", "admetlab3_raw.csv"],
        note="网页源 1（9 端点）",
    )
    A(
        "A03_web_admet_ai",
        [
            "web",
            "--source",
            "admet_ai",
            "--in",
            out + "/compounds.csv",
            "--outdir",
            out,
        ],
        produces=["measurements_admet_ai.csv"],
        note="网页源 2（12 端点）",
    )
    A(
        "A04_web_protox3",
        ["web", "--source", "protox3", "--in", out + "/compounds.csv", "--outdir", out],
        produces=["measurements_protox3.csv"],
        note="网页源 3（毒性）",
    )
    A(
        "A05_chembl",
        [
            "chembl",
            "--in",
            out + "/compounds.csv",
            "--outdir",
            out,
            "--threshold",
            "40",
            "--max-neighbors",
            "3",
        ],
        produces=["measurements_chembl.csv"],
        note="实测参照源（邻居上限 3：成本随邻居数与活性分页线性增长，见台账）",
        timeout=1200,
        reuse_ok=True,
    )
    # 2026-11-19：BioTransformer 在本网络不可达（裸域超时/www 只回 301），
    # 但本地 SyGMa 引擎可用（Ridder & Wagener 2008），代谢层不再是空档。
    # 产物 source=sygma_local，**不是** BioTransformer 结果，两者规则覆盖面不同。
    A(
        "A06_bt",
        [
            "bt",
            "--in",
            out + "/compounds.csv",
            "--outdir",
            out,
            "--engine",
            "sygma",
            "--top",
            "25",
            "--cycles",
            "1",
        ],
        produces=["metabolites_sygma_local.csv"],
        note="代谢产物（本地 SyGMa 引擎；BioTransformer 不可达已降级）",
        timeout=900,
    )
    A(
        "A07_gut_micro",
        [
            "gut-micro",
            "--in",
            out + "/compounds.csv",
            "--outdir",
            out,
            "--option",
            "HGUT",
            "--poll-timeout",
            "90",
        ],
        expect=(0, 3),
        note="肠菌代谢（同一源，预期不可达；SyGMa 无肠道菌群模块，不作为替代）",
        timeout=600,
    )
    A(
        "A08_xeno_prep",
        ["xeno-prep", "--in", out + "/compounds.csv", "--outdir", out],
        note="XenoSite 人工桥任务单",
    )
    A(
        "A08b_stereo",
        [
            "{root}/tools/stereo_ceiling.py",
            "--compounds",
            out + "/compounds.csv",
            "--outdir",
            out,
        ],
        produces=["stereo_ceiling.csv"],
        note="立体盲区证书（枚举全部立体异构体，量化 2D 栈的区分力）",
    )
    A(
        "A09_merge",
        [
            "merge",
            "--inputs",
            out + "/measurements_admet_ai.csv",
            out + "/measurements_admetlab3.csv",
            out + "/measurements_protox3.csv",
            out + "/measurements_chembl.csv",
            "--outdir",
            out,
        ],
        produces=["measurements_merged.csv"],
        note="多源长表合并",
    )
    A(
        "A10_validate",
        ["validate", "--in", out + "/measurements_merged.csv"],
        note="长表契约校验",
    )
    A(
        "A11_advisory",
        ["advisory-check", "--in", out + "/measurements_merged.csv"],
        note="非阻断告警（红线 6 措辞层）",
    )
    A(
        "A12_saturate",
        ["saturate", "--wide", out + "/admetlab3_raw.csv", "--outdir", out],
        produces=["admetlab3_raw_saturation.csv"],
        note="全端点饱和扫描",
    )
    A(
        "A13_saturate_mark",
        [
            "saturate",
            "--wide",
            out + "/admetlab3_raw.csv",
            "--mark-measurements",
            out + "/measurements_admetlab3.csv",
            "--outdir",
            out,
        ],
        expect=(0,),
        note="饱和标记回写长表",
    )
    A(
        "A14_reliab",
        [
            "reliab",
            "--in",
            out + "/measurements_merged.csv",
            "--outdir",
            out,
            "--rules",
            "{root}/references/03_endpoint_rules.yaml",
            "--saturation",
            out + "/admetlab3_raw_saturation.csv",
            "--compounds",
            out + "/compounds.csv",
        ],
        produces=["reliability.csv"],
        note="多源裁决（PASS/FAIL/UNDETERMINED）",
    )
    A(
        "A15_desire",
        [
            "desire",
            "--in",
            out + "/reliability.csv",
            "--outdir",
            out,
            "--rules",
            "{root}/references/03_endpoint_rules.yaml",
        ],
        produces=["desirability.csv", "axis_scores.csv"],
        note="desirability + Pareto",
    )
    A(
        "A16_coverage",
        ["coverage", "--in", out + "/measurements_merged.csv", "--outdir", out],
        produces=["coverage_matrix.csv"],
        note="源×端点覆盖率矩阵",
    )
    A(
        "A17_coverage_gate",
        ["coverage-gate", "--emit", "--outdir", out],
        note="未覆盖端点强制声明",
    )
    A(
        "A18_qaf",
        [
            "qaf",
            "--reliability",
            out + "/reliability.csv",
            "--coverage",
            out + "/coverage_matrix.csv",
            "--measurements",
            out + "/measurements_merged.csv",
            "--compounds",
            out + "/compounds.csv",
            "--outdir",
            out,
        ],
        note="OECD QAF + PROBAST",
    )
    A(
        "A19_ledger",
        [
            "ledger",
            "--reliability",
            out + "/reliability.csv",
            "--axis",
            out + "/axis_scores.csv",
            "--measurements",
            out + "/measurements_merged.csv",
            "--outdir",
            out,
        ],
        note="证据台账反查",
    )
    A(
        "A20_tier",
        [
            "tier",
            "--reliability",
            out + "/reliability.csv",
            "--coverage",
            out + "/coverage_matrix.csv",
            "--outdir",
            out,
            "--request",
            "T2",
        ],
        expect=(0, 3, 4),
        note="运行档位封顶",
    )
    A(
        "A21_report",
        [
            "report",
            "--reliability",
            out + "/reliability.csv",
            "--axis",
            out + "/axis_scores.csv",
            "--outdir",
            out,
        ],
        note="结论段（探索模式）",
    )
    A(
        "A22_report_publish",
        [
            "report",
            "--reliability",
            out + "/reliability.csv",
            "--outdir",
            out,
            "--publish",
        ],
        expect=(0, 4),
        note="发布模式（红线 1/3 会拦；含消旋体时须出现立体上限提示）",
    )
    A(
        "A23_reporting",
        [
            "reporting",
            "--reliability",
            out + "/reliability.csv",
            "--coverage",
            out + "/coverage_matrix.csv",
            "--outdir",
            out,
        ],
        note="TRIPOD+AI 自查 + FAIR",
    )
    A(
        "A24_background",
        [
            "background",
            "--in",
            out + "/measurements_merged.csv",
            "--within-set",
            "--outdir",
            out,
        ],
        note="稳健 Z 背景归一化",
    )
    A(
        "A25_rank",
        ["rank", "--in", out + "/axis_scores.csv", "--outdir", out],
        expect=(0, 3),
        note="bootstrap 名次（默认拒绝 underpowered）",
    )
    A(
        "A26_independence",
        ["independence", "--in", out + "/measurements_merged.csv", "--outdir", out],
        note="源独立性分组",
    )
    A(
        "A27_certainty",
        ["certainty", "--reliability", out + "/reliability.csv", "--outdir", out],
        note="证据确定性分级",
    )
    A(
        "A28_selective",
        ["selective", "--reliability", out + "/reliability.csv", "--outdir", out],
        note="选择性报告诊断",
    )
    A(
        "A29_failure_modes",
        [
            "failure-modes",
            "--in",
            out + "/measurements_merged.csv",
            "--reliability",
            out + "/reliability.csv",
            "--outdir",
            out,
        ],
        note="失效模式分类",
    )
    A(
        "A30_perturb",
        [
            "perturb",
            "--compounds",
            out + "/compounds.csv",
            "--predictions",
            out + "/measurements_merged.csv",
            "--outdir",
            out,
        ],
        note="结构扰动稳定性",
    )
    A(
        "A31_dst",
        ["dst", "--in", out + "/measurements_merged.csv", "--outdir", out],
        note="Dempster-Shafer 融合（与投票法对照）",
    )
    A(
        "A32_abstain_why",
        ["abstain-why", "--reliability", out + "/reliability.csv", "--outdir", out],
        note="弃权归因",
    )
    A(
        "A33_abstain_cmp",
        ["abstain-cmp", "--reliability", out + "/reliability.csv", "--outdir", out],
        note="弃权策略对照",
    )
    A(
        "A34_fail_layers",
        [
            "fail-layers",
            "--in",
            out + "/measurements_merged.csv",
            "--reliability",
            out + "/reliability.csv",
            "--outdir",
            out,
        ],
        note="失败分层定位",
    )
    A(
        "A35_sar",
        ["sar", "--in", out + "/compounds.csv", "--outdir", out],
        note="SAR 通透性瓶颈",
    )
    A(
        "A36_acyl_glu",
        ["acyl-glucuronide", "--in", out + "/compounds.csv", "--outdir", out],
        note="酰基葡糖醛酸化风险分级",
    )
    A(
        "A37_glycoside",
        ["glycoside-hyd", "--in", out + "/compounds.csv", "--outdir", out],
        note="糖苷水解/苷元首过轴",
    )
    A(
        "A38_interference",
        ["interference", "--in", out + "/compounds.csv", "--outdir", out],
        note="结构干扰红旗层",
    )
    A(
        "A39_pka",
        ["pka", "--in", out + "/compounds.csv", "--outdir", out],
        note="电离分区（类别级 pKa）",
    )
    A(
        "A41_transport",
        ["transport", "--in", out + "/compounds.csv", "--outdir", out],
        note="转运体先验（决策清单）",
    )
    A(
        "A42_pbpk",
        [
            "pbpk",
            "--in",
            out + "/measurements_merged.csv",
            "--compounds",
            out + "/compounds.csv",
            "--dose-mg",
            "100",
            "--ic50-list",
            "11.2,2.5,30,50",
            "--ehr-scan",
            "--dump-curves",
            "--dump-cmax",
            "--outdir",
            out,
        ],
        produces=["pbpk_curves.csv", "cmax_uM.csv"],
        note="PBPK + 暴露裕度 + EHR 扫描 + 曲线/Cmax 导出",
    )
    A(
        "A40_cardiac",
        [
            "cardiac",
            "--in",
            out + "/measurements_merged.csv",
            "--exposure",
            out + "/cmax_uM.csv",
            "--outdir",
            out,
        ],
        needs=[out + "/cmax_uM.csv"],
        note="心脏安全（无 cardiac_* 端点时给出测什么）",
    )
    A(
        "A43_pd",
        [
            "pd",
            "--curves",
            out + "/pbpk_curves.csv",
            "--compounds",
            out + "/compounds.csv",
            "--ec50",
            "0.5",
            "--dosing-interval",
            "24",
            "--outdir",
            out,
        ],
        needs=[out + "/pbpk_curves.csv"],
        note="PD 效应室（曲线链）",
    )
    A(
        "A44_interop",
        [
            "interop",
            "--what",
            "all",
            "--curves",
            out + "/pbpk_curves.csv",
            "--dose-mg",
            "100",
            "--snapshot",
            "--outdir",
            out,
        ],
        needs=[out + "/pbpk_curves.csv"],
        note="PK-Sim / NONMEM 互操作",
    )
    A(
        "A45_pbpk_qualify",
        ["pbpk-qualify", "--pred", out + "/pbpk_curves.csv", "--outdir", out],
        expect=(0, 3, 4),
        needs=[out + "/pbpk_curves.csv"],
        note="PBPK 资格判定（无观测时须拒绝）",
    )
    A(
        "A46_sensitize",
        [
            "sensitize",
            "--in",
            out + "/measurements_merged.csv",
            "--outdir",
            out,
            "--factors",
            "0.2",
            "0.5",
        ],
        note="阈值敏感性",
    )
    A(
        "A47_source_rho",
        [
            "source-rho",
            "--source-a",
            out + "/admetlab3_raw.csv",
            "--source-b",
            out + "/admet_ai_raw.csv",
            "--outdir",
            out,
        ],
        note="源间相关（互补性）",
    )
    A(
        "A48_source_admit",
        ["source-admit", "--results", "{work}/source_results.csv", "--outdir", out],
        needs=["{work}/source_results.csv"],
        produces=[],
        note="源准入注册门（CP95 上界 ≤ tol）",
    )
    A(
        "A49_ac_plan",
        [
            "ac-plan",
            "--compounds",
            out + "/compounds.csv",
            "--controls",
            "--outdir",
            out,
        ],
        note="主动学习变体计划",
    )
    A(
        "A51_conformal_scale",
        [
            "conformal-scale",
            "--train-compounds",
            "{work}/split_train.csv",
            "--target-compounds",
            "{work}/split_target.csv",
            "--k",
            "5",
            "--outdir",
            out,
        ],
        expect=(0, 3, 4),
        needs=["{work}/split_train.csv"],
        note="难度自适应保形（kNN 距离作难度；面板 15/15 切分）",
    )
    A(
        "A50_knn_sens",
        ["knn-sensitivity", "--outdir", out],
        expect=(0,),
        note="AD 阈值网格敏感性（需真实数据，缺则如实报）",
    )

    # ---------------- B. 统计/基准腿：随包真实数据 ----------------
    B(
        "B01_external_openadmet",
        [
            "external",
            "--dataset",
            "openadmet",
            "--data-dir",
            "{root}/assets/external/openadmet",
            "--split",
            "test",
            "--outdir",
            "{work}/legB",
        ],
        note="随包 OpenADMET 契约表",
    )
    B(
        "B02_external_npass",
        [
            "external",
            "--dataset",
            "npass",
            "--data-dir",
            "{root}/assets/external/npass",
            "--outdir",
            "{work}/legB",
        ],
        note="随包 NPASS 契约表",
    )
    B(
        "B02b_legb_pair",
        [
            "{root}/tools/panel_legb_split.py",
            "--measurements",
            "{work}/legB/measurements_test.csv",
            "--outdir",
            "{work}/legB",
        ],
        produces=["{work}/legB/synthetic_pred.csv", "{work}/legB/synthetic_truth.csv"],
        note="为统计腿构造带种子标记的合成配对（SYNTHETIC）",
    )
    B(
        "B03_benchmark",
        ["benchmark", "--demo", "--outdir", "{work}/legB"],
        note="AUROC/AUPRC + 聚类 bootstrap（--demo：合成真值，仅验指标代码）",
    )
    B(
        "B04_conformal",
        [
            "conformal",
            "--predictions",
            "{work}/legB/synthetic_pred.csv",
            "--truth",
            "{work}/legB/synthetic_truth.csv",
            "--alpha",
            "0.2",
            "--min-n",
            "20",
            "--outdir",
            "{work}/legB",
        ],
        needs=["{work}/legB/synthetic_pred.csv"],
        produces=["{work}/legB/conformal_intervals.csv"],
        note="保形区间（合成配对，仅验数学与接线）",
    )
    B(
        "B05_conformal_check",
        [
            "conformal-check",
            "--conformal",
            "{work}/legB/conformal_intervals.csv",
            "--reliability",
            out + "/reliability.csv",
            "--outdir",
            "{work}/legB",
        ],
        needs=["{work}/legB/conformal_intervals.csv"],
        expect=(0, 3, 4),
        note="覆盖率自检",
    )
    B(
        "B06_landscape",
        ["landscape", "--outdir", "{work}/legB"],
        expect=(0, 3, 4),
        note="方法生态位分工",
    )
    B(
        "B07_transfer",
        [
            "transfer",
            "--datasets",
            "{work}/legB/measurements_train.csv=openadmet_train,"
            "{work}/legB/measurements_test.csv=openadmet_test",
            "--proxy",
            "--outdir",
            "{work}/legB",
        ],
        expect=(0, 3, 4),
        needs=["{work}/legB/measurements_train.csv"],
        note="跨数据集稳健性（同源不同 split → 代理运行，不等于外部效度）",
    )
    B(
        "B08_regaloside",
        ["regaloside-ab", "--outdir", "{work}/legB"],
        expect=(0, 3, 4),
        note="Regaloside A/B 案例复算",
    )

    # ---------------- C. 治理/基础设施腿 ----------------
    C("C01_env_fp", ["env-fp", "--out", "{work}/legC/env_fp.json"], note="环境指纹")
    C(
        "C02_env_audit",
        ["env-audit", "--quiet", "--required-only"],
        expect=(0, 1),
        note="环境自检（rc=1 才是阻断）",
    )
    C(
        "C03_release_check",
        ["release-check", "--root", "{root}"],
        expect=(0,),
        note="发布门禁 G1–G14",
    )
    C(
        "C04_snapshot_summary",
        ["snapshot-summary", "--out", "{work}/legC/snap.json"],
        expect=(0, 3),
        note="快照台账",
    )
    C("C05_snapshot_verify", ["snapshot-verify"], expect=(0, 3, 4), note="快照校验")
    C("C06_prereg", ["prereg-status"], expect=(0, 3, 4), note="预注册状态")
    C("C07_endpoint_tiers", ["endpoint-tiers"], note="端点等级表")
    C("C08_indep_power", ["indep-power", "--n", "10,20,40"], note="独立复现功效")
    C("C09_indep_bayes", ["indep-bayes"], expect=(0, 3, 4), note="独立复现贝叶斯")
    C("C10_estimand", ["estimand", "--selftest"], note="G13 跨量纲门自检")
    C("C11_trust", ["trust", "--selftest"], note="单分子 TRUST 决策")
    C(
        "C12_claims_fragility",
        ["claims-fragility"],
        expect=(0, 3),
        note="主张脆弱性普查",
    )
    C("C13_evidence_streams", ["evidence-streams", "--selftest"], note="证据流互补性")
    C("C14_silent_failure", ["silent-failure", "--selftest"], note="静默失败率")
    C("C15_perm_contribution", ["perm-contribution", "--selftest"], note="组件贡献置换")
    C("C16_deviation", ["deviation", "--selftest"], note="OOS/OOT")
    C("C17_retrieval_card", ["retrieval-card", "--selftest"], note="检索策略卡")
    C("C18_power", ["power-analysis", "--selftest"], note="样本量/功效")
    C("C19_external_compare", ["external-compare", "--selftest"], note="G14 外部对照")
    C(
        "C20_source_health",
        ["source-health", "--outdir", "{work}/legC"],
        expect=(0, 3),
        note="源健康探针（联网）",
        timeout=300,
    )
    C("C21_interference_selftest", ["interference", "--selftest"], note="干扰层自检")
    C(
        "C22_local_tools",
        [
            "local-tools",
            "--tool",
            "all",
            "--smiles",
            "{panel_first_smiles}",
            "--format",
            "long",
            "--deterministic",
        ],
        note="6 个离线工具",
    )

    # ---------------- A2. 合成链路（隔离目录，非证据） ----------------
    A(
        "S01_readback_synthetic",
        [
            "readback",
            "--source",
            "cardiosim_tox",
            "--file",
            "{syn}/cardiac_synthetic.csv",
            "--compounds",
            out + "/compounds.csv",
            "--map",
            "herg_ic50_uM=cardiac_herg_ic50:uM",
            "--domain-flag",
            "manual",
            "--provenance-url",
            "synthetic://panel-wiring-test",
            "--outdir",
            "{out_syn}",
        ],
        needs=["{syn}/cardiac_synthetic.csv"],
        note="回填通道（合成值，仅验接线）",
    )
    A(
        "S02_cardiac_synthetic",
        [
            "cardiac",
            "--in",
            "{out_syn}/measurements_readback_cardiosim_tox.csv",
            "--outdir",
            "{out_syn}",
        ],
        expect=(0,),
        note="心脏安全（有 IC50 时的完整路径，合成值）",
    )
    return S


# ------------------------------------------------------------------ 执行
def run_step(s, ctx):
    argv = [a.format(**ctx) for a in s.argv]
    # 纯脚本步骤（tools/xxx.py）不经过 adt.cli；CLI 步骤统一走 python -m adt.cli
    if argv and argv[0].endswith(".py"):
        argv = [PY] + argv
    else:
        argv = [PY, "-m", "adt.cli"] + argv
    shown = " ".join(argv[2:])
    log = os.path.join(ctx["logs"], s.sid + ".log")
    t0 = time.time()
    rec = dict(
        id=s.sid,
        leg=s.leg,
        cmd=shown,
        note=s.note,
        rc=None,
        status="",
        seconds=0.0,
        log=log,
        stdout_tail="",
        stderr_tail="",
        reason="",
    )

    def _abspath(p):
        p = p.format(**ctx)
        return p if os.path.isabs(p) else os.path.join(ctx["out"], p)

    absent = [n for n in s.needs if not os.path.exists(_abspath(n))]
    if absent:
        rec.update(
            status="SKIP",
            reason="缺前置产物：%s" % ", ".join(os.path.basename(x) for x in absent),
        )
        return rec
    if (
        s.reuse_ok
        and s.produces
        and all(os.path.exists(_abspath(n)) for n in s.produces)
    ):
        rec.update(
            status="PASS", rc=0, reason="复用已有产物（本轮未重跑，避免重复抓取）"
        )
        return rec
    env = dict(os.environ)
    env.setdefault("ADT_PROFILE", "academic-internal")
    # 2026-11-19（本轮自查）：不要用 subprocess.run(timeout=)。Windows 上被 kill 的
    # 子进程若还有孙进程持有管道，run() 会在 communicate() 里继续等 → 超时形同虚设，
    # 整个跑批被一个慢步骤挂死（本轮 chembl 就挂住了 20+ 分钟）。
    # 这里改成 Popen + 显式 kill + 限时排空，超时后一定返回。
    pr = subprocess.Popen(
        argv,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    try:
        out, err = pr.communicate(timeout=s.timeout)
        rec["rc"] = pr.returncode
    except subprocess.TimeoutExpired:
        pr.kill()
        try:
            out, err = pr.communicate(timeout=15)
            err = "TIMEOUT after %ss\n%s" % (s.timeout, err or "")
        except Exception:
            out, err = (
                "",
                "TIMEOUT after %ss（子进程未在 15s 内退出，已放弃排空）" % s.timeout,
            )
        rec["rc"] = -9
    rec["seconds"] = round(time.time() - t0, 1)
    with io.open(log, "w", encoding="utf-8") as fh:
        fh.write("$ %s\n\n[stdout]\n%s\n[stderr]\n%s\n" % (shown, out, err))
    rec["stdout_tail"] = out.strip().splitlines()[-6:]
    rec["stderr_tail"] = err.strip().splitlines()[-6:]
    absent_out = [n for n in s.produces if not os.path.exists(_abspath(n))]
    if absent_out and rec["rc"] in s.expect:
        rec.update(
            status="FAIL",
            reason="rc=%s 但未产出：%s" % (rec["rc"], ", ".join(absent_out)),
        )
        return rec
    if rec["rc"] in s.expect:
        rec["status"] = "PASS" if rec["rc"] == 0 else "REFUSED"
        if rec["rc"] != 0:
            rec["reason"] = "预期内拒绝/不可达（rc=%d）" % rec["rc"]
    else:
        rec["status"] = "FAIL"
        rec["reason"] = "rc=%s 不在期望 %s" % (rec["rc"], sorted(s.expect))
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--legs", default="A,B,C")
    ap.add_argument("--only", default="", help="只跑这些 step id（逗号分隔/前缀）")
    ap.add_argument("--skip", default="")
    a = ap.parse_args(argv)

    rows = load_panel(a.panel)
    work = os.path.abspath(a.workdir)
    out = os.path.join(work, "out")
    logs = os.path.join(work, "logs")
    syn = os.path.join(work, "synthetic_in")
    out_syn = os.path.join(work, "synthetic_out")
    legb = os.path.join(work, "legB")
    legc = os.path.join(work, "legC")
    for d in (out, logs, syn, out_syn, legb, legc):
        os.makedirs(d, exist_ok=True)

    write_hits(rows, os.path.join(work, "hits.tsv"))
    _make_aux_inputs(rows, work, syn)

    legs = {x.strip().upper() for x in a.legs.split(",") if x.strip()}
    steps = [
        s for s in build_steps(rows, syn) if s.leg in legs or s.sid.startswith("S")
    ]
    if a.only:
        pref = tuple(x.strip() for x in a.only.split(",") if x.strip())
        steps = [s for s in steps if s.sid.startswith(pref)]
    if a.skip:
        pref = tuple(x.strip() for x in a.skip.split(",") if x.strip())
        steps = [s for s in steps if not s.sid.startswith(pref)]

    ctx = dict(
        out=out,
        work=work,
        logs=logs,
        root=ROOT,
        syn=syn,
        out_syn=out_syn,
        panel=a.panel,
        panel_first_smiles=rows[0]["smiles"] if rows else "",
    )
    recs = []
    print("[panel] %d 个化合物 / %d 个步骤" % (len(rows), len(steps)))
    for s in steps:
        r = run_step(s, ctx)
        recs.append(r)
        print(
            "  %-24s %-8s rc=%-3s %5.1fs %s"
            % (r["id"], r["status"], r["rc"], r["seconds"], r["reason"][:60])
        )
    _write_reports(recs, rows, work, a)
    bad = [r for r in recs if r["status"] == "FAIL"]
    print(
        "[panel] FAIL %d / PASS %d / REFUSED %d / SKIP %d"
        % (
            len(bad),
            sum(r["status"] == "PASS" for r in recs),
            sum(r["status"] == "REFUSED" for r in recs),
            sum(r["status"] == "SKIP" for r in recs),
        )
    )
    return 0 if not bad else 4


def _make_aux_inputs(rows, work, syn):
    """构造跑批需要的两个小输入：源准入结果、合成心脏回填。

    两个都**不是**面板证据：
      * `source_results.csv`：`n / observed_failures` 由各源长表里 out_of_domain
        行数直接统计（真实观测），用于 source-admit 的 CP95 判据；
      * `cardiac_synthetic.csv`：**合成值**，只验证 readback→cardiac 接线，
        文件名与 note 列都标 SYNTHETIC，禁止进入任何结论表。
    """
    p = os.path.join(work, "source_results.csv")
    if not os.path.exists(p):
        per_source = {}
        for name in ("admet_ai", "admetlab3", "protox3", "chembl"):
            f = os.path.join(work, "out", "measurements_%s.csv" % name)
            if not os.path.exists(f):
                continue
            with io.open(f, encoding="utf-8-sig") as fh:
                rws = list(csv.DictReader(fh))
            n = len(rws)
            bad = sum(1 for r in rws if (r.get("domain_flag") or "") == "out_of_domain")
            per_source[name] = (n, bad)
        with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("source,n,observed_failures\n")
            for k, (n, bad) in per_source.items():
                fh.write("%s,%d,%d\n" % (k, n, bad))
            if not per_source:
                fh.write("placeholder,50,1\n")
    # 面板切成 train/target 两支（conformal-scale 需要），用 compounds.csv 的列
    comp = os.path.join(work, "out", "compounds.csv")
    if os.path.exists(comp):
        with io.open(comp, encoding="utf-8-sig") as fh:
            rows_c = list(csv.DictReader(fh))
        if len(rows_c) >= 4:
            half = len(rows_c) // 2
            for tag, sub in (("train", rows_c[:half]), ("target", rows_c[half:])):
                pth = os.path.join(work, "split_%s.csv" % tag)
                if not os.path.exists(pth):
                    with io.open(pth, "w", encoding="utf-8-sig", newline="") as fh:
                        w = csv.DictWriter(fh, fieldnames=list(rows_c[0].keys()))
                        w.writeheader()
                        w.writerows(sub)

    q = os.path.join(syn, "cardiac_synthetic.csv")
    if not os.path.exists(q):
        # readback_schemas.yaml 里 cardiosim_tox 的 key_column 是 SMILES（key_kind=smiles），
        # 所以合成文件必须给 SMILES 列，否则对齐失败——这是本轮实测发现的接线细节。
        with io.open(q, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("SMILES,herg_ic50_uM,note\n")
            for i, r in enumerate(rows[:3], 1):
                fh.write(
                    "%s,%.1f,SYNTHETIC_pipeline_wiring_test\n" % (r["smiles"], 30.0 * i)
                )


def _write_reports(recs, rows, work, a):
    """**合并**写报告：增量跑（--only/--skip）不能把之前跑过的步骤抹掉。

    2026-11-19 踩过：先全跑 83 步，再用 --only A40 补跑一步，run_report.json
    被覆盖成 1 步——台账因此失真。改为按 step id 合并，新记录覆盖旧记录。
    """
    path = os.path.join(work, "run_report.json")
    merged = {}
    if os.path.exists(path):
        try:
            old = json.load(io.open(path, encoding="utf-8"))
            for r in old.get("steps") or []:
                merged[r["id"]] = r
        except Exception:
            merged = {}
    for r in recs:
        merged[r["id"]] = r
    order = {}
    try:
        for i, st in enumerate(build_steps(rows, os.path.join(work, "synthetic_in"))):
            order[st.sid] = i
    except Exception:
        pass
    steps = sorted(merged.values(), key=lambda r: order.get(r["id"], 10**6))
    with io.open(path, "w", encoding="utf-8") as fh:
        json.dump(
            dict(
                panel=rows, steps=steps, generated_at=time.strftime("%Y-%m-%dT%H:%M:%S")
            ),
            fh,
            ensure_ascii=False,
            indent=1,
        )
    recs = steps
    lines = [
        "# 面板全流程运行台账",
        "",
        "生成时间：%s" % time.strftime("%Y-%m-%dT%H:%M:%S"),
        "",
        "| 步骤 | 腿 | 状态 | rc | 秒 | 说明 | 命令 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in recs:
        lines.append(
            "| `%s` | %s | **%s** | %s | %.1f | %s | `%s` |"
            % (
                r["id"],
                r["leg"],
                r["status"],
                r["rc"],
                r["seconds"],
                (r["note"] or r["reason"]).replace("|", "/"),
                r["cmd"][:90],
            )
        )
    bad = [r for r in recs if r["status"] == "FAIL"]
    if bad:
        lines += ["", "## 失败详情", ""]
        for r in bad:
            lines += [
                "### `%s`（%s）" % (r["id"], r["reason"]),
                "",
                "日志：`%s`" % r["log"],
                "",
                "```",
                " \\n".join(r["stderr_tail"]),
                "```",
                "",
            ]
    with io.open(os.path.join(work, "run_report.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
