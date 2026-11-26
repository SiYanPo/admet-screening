# Prior-art 更新（2026-11-23）—— 必须并入投稿 related work

> 本文件是 `PRIOR_ART_2026_SCAN.md`（2026-11-19）的**修正与增补**。旧版漏掉了 4 篇最接近的工作，
> 其中 2 篇（Honest ADMET / Trustworthy ADMET Benchmark）直接冲击"选择性预测 + 多端点"叙事。
> 完整检索记录与差异化矩阵见工作区报告：
> `D:\WorkBuddy\本地文件\2026-11-22-01-17-12\ADMET_Skill_架构新颖性_中英文文献检索与差异化终裁_2026-11-23.md`

## 1. 新增的 6 篇逼近工作（一手/预印本，均已在 2026-11-23 核实）

| # | 工作 | 出处 / DOI | 与本 skill 的重叠 | 必须写的差异 |
|---|---|---|---|---|
| 1 | **Honest ADMET** (Imdad, 2026-06-16) | Zenodo [10.5281/zenodo.20710324](https://doi.org/10.5281/zenodo.20710324) | 22 TDC 端点；AD 效应；选择性预测；conformal 欠覆盖；弃权收益与 gap 不相关 ρ=0.07 | 对象=**样本级弃权**且问"能否补回 split gap"；本工作问"**源级准入的净收益符号在哪随代价翻转**"（cABS 0.2–0.5） |
| 2 | **Trustworthy ADMET Benchmark** (Jiang, NTU, 2026-07-16, v1.1.2 11-16) | Zenodo [10.5281/zenodo.21374237](https://doi.org/10.5281/zenodo.21374237) | 22 端点 × 5 模型 × 5 seed；model selection reliability regret；校准/AD/敏感性 | 它评**选型**，本工作评**组合前源准入**；不得再以"多模型多端点矩阵"为卖点 |
| 3 | **AdmitOR** (Lian et al., arXiv:2608.15565 v6) | [arXiv](https://arxiv.org/abs/2608.15565) | admit/abstain/escalate + FDR 界 + **完整报告负结果** | 对象=LLM 优化轨迹；判据=FDR；"负结果一等输出"**不再是本工作 novelty** |
| 4 | **SciForge** (arXiv:2607.16038) | [arXiv](https://arxiv.org/abs/2607.16038) | Evidence-DAG、review gates、claim→provenance | 元科学基础设施**不再是 novelty**；差异在有可证伪实验与精确 p |
| 5 | **PACT** (arXiv:2609.01662v2) | [HTML](https://arxiv.org/html/2609.01662) | provenance-conserving 多视图融合 + typed action admission；源关系决定能否互证 | 领域=机器人；本工作有统一代价 + chemotype 白名单 + 代价边界 |
| 6 | **PRML / falsify.dev** | [spec](https://spec.falsify.dev/pre-registration) | 预注册 + 负结果=确定性退出码 10 + hash 链 | 方法学规范层已被提出；本工作遵循而非发明 |

补充：FinAbstain（arXiv:2607.24875，时间安全证据准入 + 多 agent + conformal + risk-coverage）、
SSRN 7441664（resolve–admit–decide + 拒绝代价比较）也覆盖"时间/代价依赖准入"，均需在 related work 提及。

## 2. 创新性裁决（改稿用）

- **不可再声称**：弃权/错误同尺度；负结果一等输出；Evidence-DAG 审计；conformal+AD+选择性预测；多模型多端点矩阵。
- **可声称（窄）**：**以预测源为准入单位、先于经典组合器、用统一代价函数扫描出准入何时有害的代价边界**，
  并以精确符号翻转置换 + Holm 给出定量边界（当前结果：cABS≤0.2 三端点全正，cABS≥0.5 全负，
  ref=0.5 恰在失效侧；H1 不成立但 H2 强力成立）。
- **论文定位句（替换旧句）**：
  > 既有工作分别解决样本级弃权（Chow/Geifman/Honest ADMET）、无金标准源可靠性（Dawid–Skene）、
  > 源准入与溯源融合（AdmitOR/PACT）以及可审计科研流程（SciForge/PRML）；本文在同一决策框架内
  > 把它们下推到**多源 ADMET 的源级准入**，并用统一代价函数给出**准入收益随代价翻转的边界**，
  > 该边界以预注册判据和精确置换检验量化。

## 3. 立即改稿清单

1. `PAPER_STAGE1_v4.28.md` §1.2 prior-art 段：加入上述 6 篇（Honest ADMET 与 Trustworthy Benchmark 必须放最前）。
2. `references/POSITIONING.md` / `POSITIONING_EVIDENCE_2026-11-18.md`：删除"首创负结果/首创审计"表述，改为"遵循 2026 规范"。
3. 新增 `references/SOURCE_DEPENDENCE.md`（待做）：逐源声明是否共享训练数据/基础模型/描述符，防 data-incest 批评。
4. 把 Table H2 的主命题从"负结果"改写为"代价依赖边界"（已在 `PAPER_TABLE2_MAIN_RESULTS.md` 与 `PAPER_TABLE_H2_COST_SWEEP.md` 实装）。
