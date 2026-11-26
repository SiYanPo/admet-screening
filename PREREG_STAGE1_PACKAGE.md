# Stage 1 注册研究方案包（RR-ready）

**包版本**：`PREREG-STAGE1-20261118-01`
**性质**：Ready-to-submit 的 Stage 1 Registered Report 草案（methods + frozen hypotheses，无结果）。
**状态（2026-11-24 更新）**：命题/SAP 已冻结；**已取得公开承诺锚定 + RFC3161 第三方时间戳**
（`https://dpaste.com/9TRMMK4Z5`，2026-11-24T01:21:35+08:00，SHA256 `3399cdf5…`；
freeTSA serial `0x0A6E1091`，2026-11-23T08:23:52 GMT）。`prereg-status` rc=0、
`claim_allowed=True`、`post_hoc_anchor=False`，详见 `anchors/PUBLIC_COMMITMENT.md`。
**OSF 仍未提交**：平台侧 `prevent_project_creation` 三次实测 405；Zenodo 邮箱确认未达。
**边界**：公开承诺 + 时间戳证明"内容与时刻"，但**不是 DOI/注册号**；材料只能写
"interim public commitment + RFC3161 timestamp"，不得写"registered on OSF/Zenodo"。
Zenodo 恢复后按 `tools/zenodo_deposit.py` + `tools/prereg_anchor_stage1.py` 升级为多锚链。
投稿前本文件 SHA256 必须与锚定附件一致（见 §6 步骤 4）。

---

## 1. 研究题目（双语）

**中文**：证据源级准入层何时优于直接组合？一个以失效边界为一级输出的多源 ADMET 决策框架
**English**: When does evidence-source admission beat direct combination? A multi-source ADMET decision framework with failure boundaries as a first-class output

---

## 2. 背景与缺口（冻结，Stage 2 不得改写）

多源 ADMET 预测的常规做法是把各源输出直接投票/加权。我们此前提出：在组合之前增设一层
**证据源级准入（admission）**，按"该源在当前化学类/端点上是否有资格进入组合"做可审计判定，
并把弃权代价与错误代价放进同一效用函数。

既有工作分别覆盖：何时弃权（Chow 1970；Geifman & El-Yaniv 2017；Hendrickx 2024 综述 §7）、
AD 是否可信（Sahigara 2012；Norinder 2014；Mora 2024）、无金标准如何加权（Dawid & Skene 1979）、
代价同尺度（Vickers & Elkin 2006）。**没有任何一篇把"证据源级、可归因、代价同尺度的准入判定"
置于证据组合之前**。本文检验这一层级门槛是否真的带来净收益，并把"在哪些条件下不带来收益"
作为一级科学输出（失效边界），而非阴性补充材料。

对标文献与 prior-art 风险排序见 `references/POSITIONING_EVIDENCE_2026-11-18.md`。

---

## 3. 冻结的可证伪命题（PRIMARY，Stage 2 不得改写）

> **H1（条件性收益）**：在参考代价点 c_ref=(c_false_PASS, c_false_FAIL, c_abstain)=(5,1,0.5)
> 且 AD 阈值 τ=0.35、target_risk=0.15 下，完整准入层 S4 相对无准入多数投票 S1 的
> 配对效用差 Δu(S4−S1) **在 3 个端点中的至少 2 个上显著为正**（paired bootstrap 95%CI 下界 > 0）。
>
> **H0（零假设）**：Δu ≤ 0 或 CI 跨 0 的端点 ≥ 2 个。

**初始证据（仅用于功效分析，不构成 Stage 2 结论）**：
来自回溯性 `out_keystone_v43/results.json`（20 seeds，ref 代价点）：
- DILI: Δu=+0.013, CI [0.000, 0.026]（临界，下界贴 0）
- hERG: Δu=−0.197, CI [−0.201, −0.193]（显著为负）
- BBB_Martins: Δu=−0.223, CI [−0.227, −0.220]（显著为负）

→ 回溯数据**不支持 H1**。Stage 2 的前瞻数据将独立检验 H1；
若同样不支持，则结论为"在 c_ref 下准入层无净收益"，这是预注册的负结果，受 RR 制度保护。

**次级命题（SECONDARY，探索性，须标注）**：
- H2：存在代价区间使 S4 净收益转正（对 c_abstain ∈ {0.05,0.1,0.2,0.5,1.0} 与 c_false_PASS ∈{2,5,10} 扫描）。
  判据：至少 1 个代价点的 Δu CI 下界 > 0；报告所有扫描点，不做选择性报告。
- H3：S4 相对 S3（纯置信度弃权）的增量收益 Δu(S4−S3) 在 c_ref 上不为正——
  即准入层的额外复杂度是否有独立贡献。

---

## 4. Estimand 绑定（冻结，解除 C01 类撤回的关键）

| 端点 | 目标量 estimand | 实验金标准 | 当前绑定状态 | Stage 2 规则 |
|---|---|---|---|---|
| hERG | hERG 阻断的体外抑制/IC50 | 膜片钳 IC50 或 %抑制@Cmax | **NOT_BOUND** | 若无湿实验金标准，则主分析改为"相对同数据集内的算法一致性"，并明确标注**不可推断临床安全性**；AUC 不得与 always-positive accuracy 同句比较（G13 已代码化） |
| DILI | 临床 DILI 诊断标签 | 外源临床标签 | PARTIAL | 单源外源结论不升格为普适主张；须报单源边界 |
| BBB_Martins | logBB 阈值被动通透类别 | in vivo logBB | PARTIAL | gate AUC 0.514 只作"未证明有判别力"，不作"证明无判别力" |
| caco2 | logPapp (cm/s) 配对位移 | 实测 logPapp MMP | REGRESSION_PROXY | 用位移比 R + 符号一致率，不用翻转率 |

**跨量纲禁令（冻结）**：AUC（随机基线 0.5, scale=ranking）与 always-positive accuracy
（=prevalence, scale=correct_fraction）不得同句比较；由 `adt.estimand.check_comparison` 机检，
`release-check` G13 为 blocker。详见 `references/ENDPOINT_ESTIMAND_CARDS.yaml`。

---

## 5. 统计分析计划（SAP，冻结）

### 5.1 分析集
- **主分析集**：Stage 2 新采集的、在注册锚定日期之后才获得标签的端点×化合物记录（前瞻集）。
  回溯集仅用于功效分析与方法开发，**不进入主分析**。
- **敏感性分析集**：回溯集 + 前瞻集合并（明确标注为探索性）。
- 排除规则：结构无效（InChIKey 不匹配、立体缺失）、out_of_domain 但无 AD 分数者；
  排除必须在解盲前按 `inputs/EXCLUSION_RULES.md` 冻结，不得事后调整。

### 5.2 指标与估计量
- 主指标：配对效用差 Δu = median_i [u(S4)_i − u(S1)_i]，i 为随机种子（20 seeds/代价点/端点）。
- 区间：paired bootstrap（seed=20261103，B=10000，百分位法），报告 95%CI。
- 多样化的端点结论用 Holm–Bonferroni 控制 FWER（m=3），报告校正后 p 与 adj CI。
- 弃权率、覆盖率、风险-覆盖曲线作为共同二级描述，不做显著性声称。

### 5.3 多重比较与选择性报告
- H1 为唯一 primary（3 端点族内 Holm 校正）。
- H2/H3 为 secondary exploratory，全部扫描点完整报告，不挑最优。
- 任何"某些端点有效"的表述必须附 Holm 校正结果（编码于红线 9 endpoint_plurality）。

### 5.4 停止规则
- 固定样本：前瞻集达到每端点 n≥30 有效标签后解盲一次，不做事后加样。
- 若因标签获取困难未达 n≥30，按 `guards.sample_size_guard` 降级为定性结论，不作显著性声称。

### 5.5 失败判据（预注册，防止事后改口径）
- 若 H1 的 3 端点中 ≥2 个 CI 下界 ≤ 0 → 判定 H1 不被支持，接受零假设（负结果）。
- 若 G13 判定任何端点 estimand 仍 NOT_BOUND → 该端点的推断性结论自动撤销，只描述不推断。

### 5.6 盲法与时序
- Stage 1 在 OSF 时间戳锚定后才解封前瞻数据；锚定日期必须早于任何前瞻标签的获取日期。
- 若事后补锚（post_hoc_anchor），`Prereg.anchor_status()` 返回 claim_allowed=False（已代码化），
  材料不得声称"已预注册"。

---

## 6. 执行交接清单（需真人操作，决策已定）

**网址（均已实测 HTTP 200，2026-11-18）**：
- OSF 注册入口：**https://osf.io/registries** ；新建：**https://osf.io/registries/osf/new**
- OSF 预注册指南：**https://help.osf.io/article/626-simplifying-the-preregistration-process**
- COS 注册报告说明：**https://www.cos.io/initiatives/registered-reports**
- PLOS ONE 发表标准（确认接受负结果）：**https://journals.plos.org/plosone/s/criteria-for-publication**

**需要真人完成的步骤**：
1. 用实名账号登录 OSF → Registries → New registration → 选 "OSF Preregistration"（或期刊指定模板）。
2. 把本文件 §1–§5 原文填入对应字段（题名/假设/方法/分析计划）。填表字段通常包括：
   - Title / Authors / Description
   - Primary hypotheses & predictions（→ §3）
   - Primary outcome variables / measures（→ §5.2）
   - Sample size & stopping rule（→ §5.4）
   - Exclusion criteria（→ §5.1）
   - Analysis plan（→ §5.2–5.5）
   - Registration type（Preregistration / Registered Report）
   无需验证码；注册默认公开，也可设 embargo（≤4 年）。
3. 上传本文件 + `references/ENDPOINT_ESTIMAND_CARDS.yaml` + `references/POSITIONING_EVIDENCE_2026-11-18.md` 作为附件。
4. 提交后记录 OSF 分配的 DOI 与时间戳，回填 `adt.prereg.Prereg.attach_anchor({"registry":"OSF","doi":...})`
   ——注意：务必用 `register_criteria(external_anchor=...)` 在标准登记时一并锚定，
   或明确接受事后锚定会被标 `post_hoc_anchor=True / claim_allowed=False`（不授予已预注册资格）。
5. 把 OSF DOI 写入论文 methods："This study was preregistered on OSF (DOI: ...) prior to data access."

**我方已完成、真人无需重做**：命题冻结、SAP、estimand 绑定、负结果处置规则、
跨量纲禁令的代码化（G13）、独立复现包（`FROZEN_SPEC.md`）。

---

## 7. 与本包配套的文件

- `PAPER_STAGE1_v4.28.md` — 按本包组织的投稿就绪论文草稿
- `references/STRATEGIC_DECISIONS_2026-11-18.md` — 5 项策略裁决依据
- `references/ENDPOINT_ESTIMAND_CARDS.yaml` — estimand 卡（G13 blocker）
- `logs/peer_review_20261117/second_replicator/FROZEN_SPEC.md` — 外部复现冻结规范
