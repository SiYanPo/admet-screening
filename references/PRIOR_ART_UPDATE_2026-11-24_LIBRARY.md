# Prior-art 二次更新（2026-11-24）—— 学校图书馆检索新增 4 篇高危逼近工作

> 本文件是 `PRIOR_ART_UPDATE_2026-11-23.md` 的**增补**。修正来源：河南中医药大学图书馆学校数据库
> （CNKI 中文库四组检索 + 迈特思创 FMRS/MEDLINE 精确检索 + PubMed 引文链追踪）。
> 原始检索日志与证据见工作区 `lib_search/LIBRARY_SEARCH_EVIDENCE.md`、`lib_search/CNKI_SEARCH_LOG.md`。
> **投稿前必读**：本文的 4 篇比 11-23 那 6 篇更危险，其中 ADMET-EvO 几乎占满了 skill 的治理层。

## 1. 新增 4 篇逼近工作（2026-11-24 一手核实）

| # | 工作 | 出处 / DOI | 与本 skill 的重叠 | 必须写的差异 |
|---|---|---|---|---|
| 1 | **ADMET-EvO: a self-evolving scientific agent**（Zhou, Wang, …, Hou, Zhang，2026-09-09/10） | [arXiv:2609.10121v2](https://arxiv.org/abs/2609.10121) | evidence-gated agent；可证伪假设；22 TDC 端点；可 abstain；source-held-out 才解除外部观测隔离；falsification 定量证据门；hash-chained Evidence Ledger；SHA-256 冻结 recipe 后再加载 test；≥5 seed + held-out evaluator；coverage–error 与端点 bootstrap CI | 核心是**agent 自我进化与证据累积**，不是"源级准入 + 统一代价"；无 false-PASS/false-FAIL/abstain 三价同尺度下的失效边界。**治理层（哈希链/冻结/弃权/源留出）已被它占位，不得声称首创** |
| 2 | **CADT: Confidence-Gated Triage**（Yalcin Ozkat，Pharmaceuticals 2026-09-11） | [10.3390/ph19091445](https://doi.org/10.3390/ph19091445)；PMID 42797490 | 置信度门控 + 认知不确定性 + applicability-domain check + ADME-T 软标志；TDC；3 split × 5 seed；407 对对接验证；结论原文"uncertainty and AD terms act as an abstention mechanism rather than an accuracy gain, and that abstention is not free" | 准入单位=**化合物-靶标对**（样本级），下游是分子对接；skill 准入单位=**预测源**（源级），下游是投票/BMA/stacking；结论方向一致但层级不同。**"弃权不是免费的""AD 作为弃权非增益"已被它先说，必须引用并差异化** |
| 3 | **MIRAGE-DTA: conflict-aware multimodal evidence arbitration**（Bioinformatics 2026） | [10.1093/bioinformatics/btag812](https://doi.org/10.1093/bioinformatics/btag812)；PMID 43006892 | 可靠性导向证据仲裁层；当前样本链 + 训练集检索链双链；模态掩码进融合；交互门解决证据分歧；10-seed 配对；cold-start/缺失模态/时间偏移；risk@80%coverage | 领域=药物-靶标亲和力；仲裁在融合**旁**且为编码器服务；skill 在组合**前**且以统一代价判"源是否有资格投票" |
| 4 | **NeuroBACE-ML**（J Mol Graph Model 2026） | [10.1016/j.jmgm.2026.109415](https://doi.org/10.1016/j.jmgm.2026.109415)；PMID 42008960 | reliability-aware 筛选；严格二值标签排除灰区；Morgan + XGBoost + Optuna；固定留出 AUROC 0.986 | 可靠性用于单模型筛选排序；无源准入、无代价边界 |

## 2. 中文库（CNKI）检索结论 —— 证据强度升级

学校 CNKI 代理（`kns.cnki.net-s.dres.hactcm.edu.cn`，浏览器会话认证）四组主题检索：
`多源预测+适用域+弃权`、`适用域+选择性预测`、`ADMET+多模型融合`、`置信度+拒识`。

- 四组均**未见**"源级准入 + 组合前判定 + 统一弃权/错误代价 + 代价依赖失效边界"架构。
- 相关中文概念散落在互不相交的三圈：① 多模型融合（影像/遥感）；② 拒识/开集识别（语音/故障诊断，见哈工大学报、控制与决策）；③ 网络药理学（中药）。无一进入 ADMET 决策准入。
- 结论措辞：可写"经 CNKI 四组检索未发现相同架构"，**仍不得写"不存在"**（主题字段宽匹配 + 依赖中文译法）。

## 3. 二次收窄的 novelty 裁决（投稿前以本条为准）

**不可再声称（本轮新增项加粗）**：弃权/错误同尺度；负结果一等输出；Evidence-DAG 审计；conformal+AD+选择性预测；多模型多端点矩阵；**弃权机制/AD 非增益与"弃权不免费"**；**证据门 + 哈希链账本 + SHA-256 冻结 + 多 seed held-out**；**source-held-out 与 coverage–error 报告**。

**唯一可声称（极窄）**：以**预测源**为准入单位、先于经典组合器、在**统一 false-PASS / false-FAIL / abstain 三价代价**下扫描出"准入收益何时翻转为有害"的**代价依赖边界**，并以精确符号翻转置换 + Holm 给出定量边界（cABS≤0.2 全正、cABS≥0.5 全负、ref=0.5 落在失效侧；H1 不成立、H2 强力成立）。

**推荐 related work 定位句（替换 11-23 版）**：
> 近期工作已从多个方向逼近可信 ADMET：样本级置信度门控与适用性域弃权（CADT）、可靠性感知的证据仲裁（MIRAGE-DTA）、
> 可靠性筛选（NeuroBACE-ML）、以及带证据账本与哈希冻结的自我进化 agent（ADMET-EvO）。本文与之 differ in kind：
> 准入的决定单位是"预测源"而非分子或样本，判定发生在投票/BMA/stacking 之前，且以统一代价函数给出
> 准入净收益随代价翻转的定量边界——该边界以预注册判据与精确置换检验量化。

## 4. 必须做的改稿动作

1. `PAPER_STAGE1_v4.28.md` §1.2：加入本节 4 篇；CADT 与 ADMET-EvO 必须排最前，并逐条写明上面的差异句。
2. `references/COVER_LETTER_DRAFT.md` 版本 A 的 prior-art 句：现列 5 篇，须改为至少 7 篇（加入 CADT、ADMET-EvO）。
3. `references/REVIEWER_REBUTTAL_PACK.md`：新增"攻击 9：CADT/ADMET-EvO 已经做了弃权与审计"的回应。
4. 任何宣传性文字：删除"首创""首次"用于负结果、审计链、弃权、AD、source-held-out 的表述。
