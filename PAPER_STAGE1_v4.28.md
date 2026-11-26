# Stage 1 Registered Report 草稿（v4.28，投稿就绪结构）

**配套**：`PREREG_STAGE1_PACKAGE.md`（冻结命题/SAP/OSF 交接）；`references/STRATEGIC_DECISIONS_2026-11-18.md`（策略裁决）
**结构声明**：Stage 1 = Introduction + Hypotheses + Methods，**不含结果**。所有"预期证据"仅来自回溯集，标注为功效分析输入，不构成结果。Stage 2 解盲后按同 SAP 填 Results/Discussion。
**Frame（裁决 1）**：失效边界检测框架；负结果是一等输出。
**Target（裁决 3）**：Stage 1 RR 投 soundness 刊（PLOS ONE / Nat Hum Behav / Elsevier RR 表）；本轮不投 Nature Methods。

---

## Title

**When does source-level evidence admission beat direct combination? A preregistered failure-boundary analysis of multi-source ADMET decision-making**

（中文：证据源级准入何时优于直接组合？多源 ADMET 决策的预注册失效边界分析）

---

## Abstract（Stage 1 结构式，待 Stage 2 补结果数字）

**Background**: Multi-source in-silico ADMET predictions are routinely combined by voting or weighting without asking whether each source is admissible for the endpoint and chemical class at hand. We previously proposed an explicit *admission* layer that decides, auditably and with attributed reasons, whether a source may enter the combination, and that prices abstention and error on a common utility scale. Whether this layer improves decisions — and where it fails — has not been tested prospectively.

**Hypotheses (frozen)**: H1 (primary): at reference cost c_ref=(5,1,0.5) and applicability-domain threshold τ=0.35, full admission (S4) yields a positive paired utility change Δu relative to naive majority voting (S1), with paired-bootstrap 95% CI lower bound > 0, on at least 2 of 3 endpoints (hERG, DILI, BBB_Martins), Holm-adjusted. H2/H3 (secondary, exploratory): a cost interval exists where S4 wins; and S4's incremental value over confidence-only abstention (S3) is non-positive at c_ref.

**Methods**: Preregistered Stage 1 RR. The frozen protocol is anchored by a public commitment
(https://dpaste.com/9TRMMK4Z5, 2026-11-24T01:21:35+08:00) plus an independent RFC 3161 timestamp
(freeTSA serial 0x0A6E1091); this is an interim public commitment, **not** a registry DOI —
a restricted-access Zenodo deposit will replace it when repository access is restored.
Prospective labels obtained strictly after registration anchoring; retrospective data used only for power analysis. Endpoint estimands are bound in `ENDPOINT_ESTIMAND_CARDS.yaml`; cross-dimensional comparisons (AUC vs always-positive accuracy) are mechanically blocked (G13). Paired bootstrap over seeds (B=10,000), Holm FWER across endpoints, fixed stopping at n≥30 valid labels/endpoint.

**Anticipated contribution**: Regardless of H1's outcome, the study delivers a *failure-boundary map* — the cost/endpoint regimes where **source-level** admission cannot be shown to help — as a first-class, citable output. This is a difference in kind from prior sample-level confidence gating and evidence arbitration (§1.2): we ask at what cost the source-level gate stops paying for itself. Retrospective evidence already suggests H1 may not be supported (Δu(S4−S1) at c_ref: DILI +0.013 [0.000,0.026], hERG −0.197 [−0.201,−0.193], BBB −0.223 [−0.227,−0.220]); these numbers are **power-analysis inputs only**, not Stage 2 results. If H1 is likewise unsupported prospectively, that is a preregistered negative result protected by the RR mechanism.

---

## 1. Introduction

### 1.1 Problem
虚拟筛选命中的 ADMET 评估普遍存在"多源结果相互矛盾却不知道信谁"。常规做法（投票、加权、BMA）默认所有源都有资格进入组合。但一个在化学类/端点上不适用的源，其"投票"本身是噪声——组合前的**资格判定**应是被显式建模的决策，而非隐含假设。

### 1.2 Related work（2026-11-24 重写，投稿成稿）

We position this study against four lines of work and state explicitly which claims are **not** ours.

**Classical foundations — each component already exists.** Rejection with a cost on the same scale as error was formalised by Chow (1970) and extended by Cortes, DeSalvo & Mohri (2016); risk–coverage curves by Geifman & El-Yaniv (2017); multi-rejector combination and rejection-type attribution by Hendrickx et al. (2024, §7). Reliability estimation without gold labels goes back to Dawid & Skene (1979). Selecting members *before* combination — the architectural move closest to ours — is established by Caruana et al. (2004) and Zhou, Wu & Tang (2002, GASEN), while discounting evidence before Dempster combination is established by Shafer (1976). Net-benefit cost scaling in clinical prediction is due to Vickers & Elkin (2006). Applicability domains are tightly bound to the base learner (Alvarsson et al. 2021) and their "reliable" labels can reside in high-error subspaces (Mora et al. 2024; Sahigara et al. 2012; Norinder et al. 2014). **We therefore claim none of these components as novel.**

**ADMET-specific selective prediction and benchmarking.** Honest ADMET (Imdad, 2026) studied 22 TDC endpoints with applicability-domain effects, conformal under-coverage and sample-level abstention, and reported that abstention benefit was uncorrelated with the generalisation gap (ρ = 0.07). The Trustworthy ADMET Benchmark (Jiang et al., 2026; 22 endpoints × 5 models × 5 seeds) quantified *model-selection* reliability regret. TRUST-ADMET (Bollepalli, 2026) packages ML, GNN, ChemBERTa, calibration, AD, conformal, explainability and external validation as open software. We do not claim a multi-model/multi-endpoint matrix as a contribution: that design space is already covered, at larger scale, by these works. Our question is different in kind — not which model to select, but which *source* is admissible before any combination.

**Confidence gating, evidence arbitration and reliability-aware screening — the closest prior art.** Three 2026 studies approach our decision layer from adjacent directions. CADT (Yalcin Ozkat, *Pharmaceuticals* 2026, 10.3390/ph19091445) couples an ensemble drug–target affinity estimate, its epistemic uncertainty, an applicability-domain check and an ADME-T soft flag into a confidence-gated docking triage; on a cold-target split it routed 86% fewer compounds to docking while retaining 61% of true strong binders. Its conclusion is explicitly aligned with ours: *"the uncertainty and applicability-domain terms act as an abstention mechanism rather than an accuracy gain, and that abstention is not free."* MIRAGE-DTA (Bioinformatics 2026, 10.1093/bioinformatics/btag812) implements a reliability-oriented **evidence-arbitration layer** with two explicit evidence chains, modality masks carried into fusion, an interaction gate resolving disagreement, 10-seed paired evaluation and risk-at-coverage under cold-start and temporal shift. NeuroBACE-ML (J. Mol. Graph Model 2026, 10.1016/j.jmgm.2026.109415) applies reliability-aware screening to BACE1 inhibitors with strict binary labels and Optuna-tuned XGBoost. ADMET-EvO (Zhou et al., arXiv:2609.10121v2, 2026) is the closest in governance: an evidence-gated self-evolving ADMET agent that generates falsifiable hypotheses, may abstain, quarantines external observations until source-held-out performance is established, records verdicts in a hash-chained evidence ledger, freezes recipes by SHA-256 before opening the test split, and reports ≥5-seed held-out certification with coverage–error analysis. **We do not claim priority for abstention, evidence gating, applicability-domain checks, source-held-out evaluation, hash-chained ledgers, frozen recipes, or risk–coverage reporting.**

**Admission, arbitration and audit as general mechanisms.** AdmitOR (arXiv:2608.15565) provides a label-free admission gate with accept/abstain/escalate and finite-sample FDR bounds, and publishes a full negative result. PACT (arXiv:2609.01662) performs provenance-conserving multi-view fusion with typed action admission in robotics. SciForge (arXiv:2607.16038) supplies Evidence-DAG audit sidecars and review gates; the PRML/falsify.dev specification defines preregistration with negative results as a deterministic exit code and hash chains. FinAbstain (arXiv:2607.24875) and SSRN 7441664 cover time- and cost-dependent evidence admission. These works establish that "negative results as first-class output", "claim-to-provenance auditing" and "admission before use" are **community-level practices**, not inventions of this paper.

**What remains — a difference in kind, not degree.** Across all of the above, the unit of decision is a molecule, a compound–target pair, a model choice, an agent action, or a modality; where an admission gate exists it precedes a *different downstream task* (docking, a skill library, fusion, or self-experimentation). None treats the **prediction source** itself as the admissibility unit for a chemical class and endpoint, decides before voting/BMA/stacking, and reports the **cost-dependent boundary at which the sign of admission's net benefit flips** under one shared utility scale for false PASS, false FAIL and abstention. We report that boundary with preregistered criteria, exact sign-flip permutation tests and Holm correction (cABS ≤ 0.2 positive on all three endpoints; cABS ≥ 0.5 negative on all three; the preregistered reference point cABS = 0.5 falls on the failing side). In short: prior work establishes that *abstention is not free*; we quantify *the cost at which source admission starts costing more than it returns*.

Full per-component comparison and the Chinese-language search record (CNKI, four query groups, no equivalent architecture found) are in `references/PRIOR_ART_UPDATE_2026-11-24_LIBRARY.md` and `references/PRIOR_ART_2026_SCAN.md`.


### 1.3 Contribution statement（2026-11-24 修订，替换冻结版）
1. We formalise source-level admission as a decision that precedes voting/BMA/stacking, with attributed verdicts and one shared utility scale for false PASS, false FAIL and abstention. The *unit* of admission — a prediction source for a chemical class and endpoint — is the contribution; the gating mechanism itself is not claimed as novel (§1.2).
2. We test a preregistered falsifiable hypothesis about its net benefit and report the **cost-dependent failure-boundary map** as the primary citable output (Fig 1): the sign of S4−S1 flips between cABS = 0.2 and 0.5, with the preregistered reference point on the failing side, quantified by exact sign-flip permutation and Holm correction.
3. We make the claim itself machine-governable: endpoint estimands are bound and cross-dimensional comparisons are blocked (G13), so a withdrawn claim cannot be silently revived. We follow, rather than invent, 2026 practices for auditable research (evidence ledgers, preregistration, frozen recipes); the novelty is their use to certify a *cost boundary*, not the mechanisms.

> **边界（投稿前不得删除）**：本文不声称弃权、适用性域、证据门、哈希链、冻结配方、source-held-out、risk–coverage、负结果一等输出或审计链的首创性——这些均已在 §1.2 逐条引用。

---

## 2. Hypotheses（冻结，逐字来自 PREREG_STAGE1_PACKAGE §3）

H1 / H0 / H2 / H3 原文见 `PREREG_STAGE1_PACKAGE.md` §3，此处不复制以免版本漂移；以该包为唯一来源，
其公开承诺锚定见 `anchors/PUBLIC_COMMITMENT.md`（OSF/Zenodo 注册号待补，不得虚构）。

---

## 3. Methods（Stage 1 完整，Stage 2 不得改写）

### 3.1 Decision framework
三态裁决（PASS / FAIL / UNDETERMINED）+ 九类归因码；准入层独立于组合器；代价三元组 c=(c_abstain, c_false_PASS, c_false_FAIL)；Δu 定义、配对 bootstrap、Holm。详见 `PREREG_STAGE1_PACKAGE.md` §5。

### 3.2 Estimand binding
四个端点卡（hERG/DILI/BBB/caco2）逐条见 `ENDPOINT_ESTIMAND_CARDS.yaml`。跨量纲禁令由 `adt.estimand.check_comparison` 机检，G13 blocker。

### 3.3 Data & split
前瞻集（锚定后新标签）为主分析；回溯集仅功效分析；排除规则冻结于 `inputs/EXCLUSION_RULES.md`（Stage 1 附件）。TDC 随机切分与 temporal holdout 区别见 `references/TEMPORAL_HOLDOUT_DISCIPLINE.md`；时间切分不构成前瞻。

### 3.4 Analysis
按 SAP §5.2–5.5；主分析一次解盲，固定 n≥30/端点，不中途加样。

### 3.5 Reproducibility
- 版本三轨（发布号 0.9.0 / 能力等级 4.0-dev / 材料修订 4.28）；引用数字写产物身份（manifest_sha1 前 12 位 + 路径），不写"v4.x 的结果"。
- 25/25 主张字段级绑定（`CLAIMS_REGISTRY.yaml`，G10 ratio=1.00）。
- 独立统计复算 8/8 通过（`logs/peer_review_20261117/second_replicator/comparison.md`）；**外部人类复现（G9 条件③）仍未完成**，不得声称已外部复现。
- 环境：`bootstrap.py` + `env-audit --required-only`；可选 pytdc 层不影响主分析。

---

## 4. Figure/Table plan（每张绑定具体产物；已撤回图不列）

| 编号 | 内容 | 产物路径 | 状态 |
|---|---|---|---|
| **Fig 1（主图）** | **失效边界图**：代价点×端点 × Δu(S4−S1) 中位数与配对 bootstrap CI；CI 下界≤0 的格子标红为"未证明有益" | `out_keystone_v43/results.json`（回溯版）/ Stage 2 前瞻产物 | 待 Stage 2 前瞻数据；回溯版仅供功效分析 |
| Fig 2 | 框架数据流与准入层位置、归因码、计票账目 | `references/EVIDENCE_DAG.md` + `SKILL.md` | ✅ 可直接画 |
| Fig 3 | gate 判别力端点依赖 + Holm 校正：hERG 0.580 / DILI 0.669 / BBB 0.514；familywise_any_reject=false | `out_ext/tdc/gate_audit*.json`、`gate_multiplicity.json` | ✅ |
| Fig 4 | Ames 双方法层：放行错误率 0.2685→0.177，差 0.0915 CI[0.0479,0.1345]（条件于放行集的配对表） | `out_ext/tdc/ames_release_ci.json`、`ames_alerts.json` | ✅ |
| Fig 5 | MMP 双向检验与功效边界（DILI 31 对 < 需 61 → insufficient_power） | `out_ext/tdc/p8_mmp_results*.json` | ✅ |
| Fig 6 | kNN 阈值网格敏感性：5/6 组合 threshold_critical（Δacc 14–37%）——新增负结果 | `logs/peer_review_20261117/knn_sens_cli/knn_threshold_sensitivity.json` | ✅ |
| Fig S1 | 近邻泄漏归因（BBB −0.212 未解释） | `out_ext/tdc/leakage_attribution.json` | ✅ |
| Table 1 | 端点 estimand 卡与绑定状态 | `references/ENDPOINT_ESTIMAND_CARDS.yaml` | ✅ |
| Table 2 | 主张×产物×字段级证据（25/25） | `references/CLAIMS_REGISTRY.yaml` | ✅ |
| Table S1 | 阈值 census 与冻结状态 | `references/THRESHOLD_REGISTRY.yaml` | ✅ |

**禁止入稿**：`external_cuts_summary.json` 的 "AUC vs always-positive" 旧图（C01 撤回）；
`keystone_indifference.json` 的无差异曲线（C18 会计恒等式撤回）；
`TAIL_RISK_THESIS.md` 的"域外处处不可用/门全拒是保守的正确"（R2 撤回）。
这些只作审计证据，不作科学结论。

---

## 5. Limitations & boundary conditions（冻结，Stage 2 不得删除）

1. **estimand 未绑定**：hERG 金标准仍 NOT_BOUND；AUC 不承载临床决策含义。当前回溯分析为探索性；Stage 1 冻结后前瞻检验。
2. **方法同源**：三计算源仍是同一训练集上的模型；独立性瓶颈来自方法同源而非源数量（Fig S1 的 BBB 泄漏 −0.212 未解释）。
3. **单源外源结论**：DILI 的域外差异仅单一来源，不升格为普适主张。
4. **阈值未全部实测标定**：11 条阈值中 2 条未冻结（Table S1）；kNN 阈值敏感性显示 5/6 组合临界（Fig 6）。
5. **无外部人类复现**：本轮只有第二 agent 实例的独立复算；G9 条件③未完成。
6. **PK/PBPK 边界**：nlmixr2 模型参数结构性不可辨识（仅 V 可估，Condition# 1.65e5，71.8% 观测为零）；PK-Sim 仿真可完整往返，但仿真引用的 ObservedData 缺失会导致静默跳过（退出码仍 0）——见 `logs/peer_review_20261117/pkpd_diagnosis.md`。本工作不作 regulator-grade PBPK 声称。

---

## 6. 投稿策略（裁决 3）

| 路径 | 目标 | 适用条件 | 判断 |
|---|---|---|---|
| 主线 | Stage 1 RR → PLOS ONE / Nature Human Behaviour / Elsevier RR 刊表 | 接受 RR 且 soundness 导向 | 首选：一次解决负结果保护 + 确证升级 |
| Backup | PLOS ONE Missing Pieces / Scientific Reports null-findings 专集 / PeerJ | 若 RR 路径不可行 | 负结果友好、索引正常 |
| 不投 | Nature Methods 类旗舰方法刊 | 缺前瞻 validation（G9 条件②） | 本轮高概率 desk reject |
| 末位 | JONNPR | 所有主流路径失败 | 索引/声望弱，须标注局限 |

投稿前按 `references/POSITIONING_EVIDENCE_2026-11-18.md` 的官方链接二次核对当前 RR 政策（链接实测 HTTP 200，2026-11-18）。

---

## 7. 状态声明（必须随稿）

> This is a Stage 1 Registered Report draft prepared by the authors. It has **not yet been registered** on OSF as of draft date; submission is an operational hand-off requiring a human account (see PREREG_STAGE1_PACKAGE §6). Capability level remains `4.0-dev` (G9 conditions ①②③ unmet). Do not cite as preregistered or externally replicated until OSF DOI is obtained and an external human replication is completed.
