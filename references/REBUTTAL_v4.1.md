# 逐条答辩（R42 / 对 C1–C13 · V1–V9 · A1–A5）

> 每条给四样东西：**批评原文要点 / 本轮处置 / 证据位置 / 是否真的解决了**。
> "解决了"只写 ✅；部分解决写 🟡 并写清缺什么；**不能解决的写 ⛔ 且说明为什么**——
> 把 ⛔ 写成 ✅ 是这份文件最没价值的行为。

## 1. §3.1 已确认问题（C1–C13）

| # | 批评要点 | 本轮处置 | 证据位置 | 判定 |
|---|---|---|---|---|
| **C1** | 核心命题不可证伪——没有"有/无准入层"的决策质量对照 | 建**基石实验**：4 策略（S1 朴素多数 / S2 AD-guard / S3 校准+conformal / S4 完整准入）× 3 端点 × **20 种子**，主指标为**代价加权效用**，并做弃权成本与 false_PASS 的二维代价扫描 | `run_keystone.py`；`out_keystone/results.json`；`replication/expected.json` | ✅ 命题现已可证伪，**且结果不利于我们**：参考代价下 S4 在 hERG（Δu=−0.197）与 BBB（−0.223）**显著更差**，DILI 仅 +0.013。只在 `c_abstain ≤ 0.2` 或 `c_false_PASS ≥ 5` 区间 8–9/9 显著更好 → 主结论改写为**区间条件命题** |
| **C2** | n=2 的"与独立真值一致"被当作有效性证据 | 删除该叙述（两处），改为"仅 2 个可裁决单元做过点对点核对，n=2 不构成验证"；并加自动护栏按 n 分级拦截 | `外部评审材料_v4.0-dev.md` 样例 1 说明段；`run6/FULL_PIPELINE_REPORT.md`；`adt/phrasing.flag_truth_consistency_claim`；`tests/test_p4_p5.py` | ✅ |
| **C3** | `n_eff=1/(1+max(ρ,0))` 与标准式 `k/(1+(k−1)ρ)` 不一致且不含 k | 改为标准式（k=2 时逐位兼容旧结果）；相关矩阵推广用 `n_eff = k²/1ᵀR1`。**并纠正评审建议**：评审给的 `(Σλ)²/Σλ²` 并不退化为标准式（它给 `k/(1+(k−1)ρ²)`），故不采用 | `adt/independence.py`；`tests/test_independence_v41.py`（含两条互相印证的回归断言） | ✅ |
| **C4** | ρ 权重用点估计、不传播不确定性 | `weight_ci(k,ρ,lo,hi)`、`rho_posterior_weights`、`bayes_contraction`（相关矩阵 Ledoit-Wolf 收缩 + MC 后验）；输出新增 `weight_ci95` 与 `verdict_stability` | `adt/independence.py`；`independence_groups.csv` 新列；`adt/cli.py indep-bayes` | ✅ |
| **C5** | "CI 下界>0"在 n=14 功效崩塌，系统性漏检真相关 | 显式功效报告：`correlation_power(n,ρ,α)` / `min_detectable_rho` / `correlation_power_report`；**n<20 直接禁用独立性判定**，归因 `insufficient_power`（结构性），权重回退 1.0 而非"装作独立" | `adt/independence.py`、`adt/stats_ci.py`、`adt/cli.py indep-power`；`tests/test_independence_v41.py`（n=14 被拦） | ✅ |
| **C6** | ρ 混淆"共享训练数据"与"方法不独立"；P1 闭环声明排序错误 | ①全文 ρ 只表述为**输出相关（成因未拆解）**；②`references/EVIDENCE_DAG.md` 显式声明 TDATA 节点 `status: pending`，并**禁止**在 TDATA 落地前把 ρ 归因为"方法不独立"；③材料中"P1 已代码闭环"降级为"只闭到公式/传播层" | `references/EVIDENCE_DAG.md`；材料版本行与附录状态表；`release_gate G7` | 🟡 成因拆解本身**没有解决**（需要训练数据重叠度这类数据，本机没有）；只做到"不再错误归因 + 不再宣称闭环" |
| **C7** | P8 以随机无关分子对为零假设，可能奖励对活性悬崖无感的模型 | 重构为 **MMP 校准检验**：单切 matched pair 的经验 Δlabel 分布 + TOST 等价检验 + 正/负对照；真实 hERG held-out 上抽出 **127 对 / 47 核心** | `adt/mmp.py`；`run_p8_mmp.py`；产物见讨论 | ✅ **且结论反转**：经验标签变化率 13.4%、模型翻转率 **0.0%** → 判 `insensitive`。旧逻辑（instability_ratio 0.076 = 好）会夸这个模型 |
| **C8** | 156 判定仅 7 条可执行；gate 无灵敏度/特异度验证 | gate 审计：覆盖率/风险/误放率/误杀率 + 把 gate 当"可预测性分类器"算 ROC/PR + actionability summary | `adt/gate_audit.py`；`run_gate_audit.py` | ✅ **且证实评审的怀疑**：hERG 上 gate-as-classifier **AUC=0.58**（近随机），误杀率 **0.826**，域外强制预测准确率 = 域内准确率 = 0.826 → 现有 PASSTHRU 多数是"过度保守"而非"精准识别不可信" |
| **C9** | 最优弃权率 0.000 与"高风险层 27.3% 错误"并存未解释 | 分数强制经校准层，risk–coverage 只在校准分数上算；补代价敏感弃权曲线（代价网格）而非单一阈值 | `adt/selective.risk_coverage_calibrated`（断言分数类型）、`cost_sensitive_abstain`；`tests` | 🟡 方法已改；"整体最优弃权率 0"的**具体数值解释**要等 S4 在 20 种子下的 coverage 稳定后再写（当前 S4 覆盖率仅 0.182±0.056，已不是原口径） |
| **C10** | 所有基准单次运行、无种子误差棒 | 全部关键实验改 20 种子，报 median[IQR] 与配对 bootstrap CI；容差由种子方差反推 | `run_keystone.py --seeds 20`；`replication/expected.json`（每项带 `seed_sd`/`n_seeds`）；`adt/replication.tolerance_from_seeds` | ✅ |
| **C11** | smoke 69/69 属自证，且被列为成功标准第 1 条 | 成功标准重排：**S1 第二实现者可复现**（挑战包）> S2 不确定性 > S3 负结果 > … > **G 构建门槛（明确不是成功标准）** | 材料 §成功标准；`replication/`；`README_CN.md` 推广策略 3 | ✅ 排序已改；但"第二实现者"本身 ⛔ 未到位，故 S1 只能标 🟡 |
| **C12** | 无分级合规决策树；NC/GPL 源无代码级隔离开关 | 4 档 profile（academic-internal/shared/pre-commercial/commercial）+ 许可映射 + **适配器基类强制检查**（绕过 CLI 直接实例化也拦）+ BioTransformer 默认关 | `adt/compliance.py`；`adt/adapters/base.py`；`--profile`；`tests/test_input_compliance_v41.py` | ✅ |
| **C13** | 名称→SMILES 入口已致一次立体事故，未改 InChIKey 强制锚定 | 输入硬化：`FIELD_PRIORITY`（SMILES>Isomeric>Canonical，`ConnectivitySMILES` 永不作首选）、InChIKey 锚点、立体缺失即 fail；`normalize` 产出 `input_gate.csv`，`--strict-input` 返回码 3；名称检索降为交互辅助且走快照层 | `adt/pubchem.py`；`adt/cli.py cmd_normalize`；`tests/test_input_compliance_v41.py` | ✅ **且实测又抓到两例**：run6 输入的 Terfenadine / Donepezil 均含未指定手性中心（须声明消旋体） |

## 2. §3.2 需验证疑点（V1–V9）——它们原本要"读源码"，现在给结论

| # | 原疑点 | 核实结果 | 证据位置 |
|---|---|---|---|
| **V1** | `n_eff_votes` 是否另处理 k | **既有处理也确有缺陷**：旧式 `1/(1+max(ρ,0))` 完全不含 k（2 源与 8 源同权重），现已修正为标准式 | `adt/independence.py`；`tests/test_independence_v41.py::test_k_enters_formula` |
| **V2** | Clopper-Pearson 门的 ε/n/目标功效未给出 | 给出真实计算表：真失败率 3%、n=100 时通过概率仅 **4.8%**，n=500 才 56.8%；结论是小源会被系统性拒之门外，故改为"带 CI 标注进入"而非二值拒绝 | `references/STATISTICAL_POLICY.md` §1.1；`adt/stats_ci.gate_pass_probability` |
| **V3** | `risk_coverage_report` 的效用/代价参数 | 代价已**显式预注册**：`COSTS={"hERG":(5,1,0.5),"DILI":(5,1,0.5),"BBB":(3,1,0.5)}`，并做 `c_abstain∈{0.05,0.1,0.2,0.5,1.0}` × `c_false_PASS∈{2,5,10}` 扫描 | `run_keystone.py`；`out_keystone/results.json → cost_sweep` |
| **V4** | 适用域判据形态；PASSTHRU 58% 是否由此导致 | Tanimoto kNN（0.35 饱和 / 0.7 污染），且**已审计其判别力**：hERG 上 gate AUC 0.58、误杀 0.826 —— 即 PASSTHRU 之多的**主要成因是 gate 过严**，不是"域外真的不可判" | `adt/gate_audit.py`；`run_gate_audit.py` |
| **V5** | RF 基线是否固定种子、脚本是否支持多种子 | 现支持 `--seeds 20`，每种子独立切分并记录；种子列表写入 `spec.seeds` | `run_keystone.py`；`replication/expected.json → spec` |
| **V6** | ρmax=0.9429 的样本量与端点；24 对单位异构能否换算而非丢弃 | ①ρ 一律带 Fisher z CI 与 n；②单位侧改为**能换算就换算**：同族线性（uM↔nM）、百分比包裹（45%↔0.45）、`log10(M)↔M`；`class vs probability` 判为**语义差异**拒绝换算（C78）。**实测结论**：run6 那 24 对属于后者，不是量纲差异，因此"跳过"是正确处置而非信息浪费 | `adt/units.py`；`tests/test_input_compliance_v41.py::test_unit_conversion_and_semantic_refusal` |
| **V7** | TDC 官方切分 2026 现状 | 已实测：本版依赖可正常读取并使用官方切分；版本与可用性记录在 `requirements.lock` 与 `references/TDC_ALIGNMENT.md`；状态从 🟡 升 ✅ 并附实测数字 | `references/TDC_ALIGNMENT.md`；`requirements.lock` |
| **V8** | 新依赖版本在他机可获得性 | 已按实测版本钉版（RDKit **2026.3.6**、numpy 2.5.4 等），并记录本机 pip 源（阿里云镜像）实测可拉全量；**未做**的是干净机器 + 纯官方源的独立验证 → 归入外部复现者任务 | `requirements.lock`；`adt/release_gate.py G1/G4` |
| **V9** | `class_blocks`(C82) 规则集出处/版本/验证状态 | 规则源在 registry（`references/02_source_registry.yaml` 的 `blocked_endpoints_in_class`），已接进 `reliab`（此前只登记不读取，是 C82 的真 bug）；验证状态：有回归测试，**无外部验证** | `adt/reliability.apply_class_blocks`；`tests/test_class_blocks.py`；`reliab` 输出的 `out_of_domain` 计数 |

## 3. §3.3 学术分歧（A1–A5）——这些不是"错误"，是要给立场

| # | 分歧 | 我们的立场（本轮明确化） |
|---|---|---|
| **A1** | ρ 的处置哲学：惩罚收缩 vs 冗余折扣/BMA | **不再宣称唯一正确**。收缩是可解释的下界做法（保守），BMA 需要源级似然（我们没有）。已在 `references/BAYESIAN_DECISION.md` 与 `independence.py` 中把收缩写成"**一种可选先验下的近似**"，并把结论强度绑定在 `weight_ci95` 上——即"分歧未裁决前不给强结论" |
| **A2** | "扰动下应稳定"是否公理 | **撤回公理地位**。改为 MMP 校准的经验期望位移作合格线（TOST），并把"对悬崖敏感"当**可能的正确行为**而非缺陷：`adt/mmp.analyze` 的判定词是 `equivalent / insensitive / oversensitive / inconclusive`，**`insensitive` 才是问题，稳定本身不是优点** |
| **A3** | 大规模弃权的价值取向 | 接受"按端点分设不对称代价"的批评。代价矩阵已端点特异（hERG 5:1 vs BBB 3:1）并做扫描；同时新增"弃权成本"维度，使"UNDETERMINED 洪流"的代价可被定价而不是免费的道德姿态 |
| **A4** | RF+Morgan 作治理基线是否足以外推 | **不外推**。材料明确"治理层横向有效性证据，不与 SOTA 混比"；基石实验的三源（RF-Morgan / Ridge-RDKit / RF-MACCS）只用于比较"有/无准入"，不用于比较"预测多准" |
| **A5** | sha256 链的防篡改强度被高估 | 接受。已实现第三方锚定接口（`Prereg.anchor_status`），并规定**未锚定时 `claim_allowed=False`、脚注印 `UNANCHORED`、不得声称完成预注册**；发布门禁 G9 阻止在未锚定时摘掉 `-dev` |

## 4. 本轮仍然"没有解决"的清单（诚实边界）

1. **C6 的成因拆解**：需要训练数据重叠度（TDATA），本机不可得 → 只做到"不错误归因"。
2. **C11 的第二实现者**：挑战包已就绪，但**没有外部人跑过**，S1 只能标 🟡。
3. **R11 外源前瞻盲测**：需要预注册时点之后的数据 + 第三方时间戳，⛔ 外部阻塞。
4. **V8 干净机器复现**：只在本机验证过依赖可装，未在无缓存环境实测。
5. **C9 的具体数值解释**：口径已变（S4 覆盖率 0.182±0.056），旧的"最优弃权率 0.000"不再可比，
   新口径的解释要等更长种子/更大样本。
