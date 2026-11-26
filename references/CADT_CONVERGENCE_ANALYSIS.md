# CADT 趋同性分析：把最强威胁改写为外部佐证（2026-11-24）

> 结论先行：CADT（Yalcin Ozkat, Pharmaceuticals 2026, 10.3390/ph19091445）表面上是最危险的逼近工作，
> 但它在**同一数据族（TDC）上独立得到了与本文同向的结论**——这可以作为"结论可复现"的外部佐证，
> 前提是严格写清差异（样本级 vs 源级）。这份分析给出可直接写进 Discussion 的段落。

## 1. 两篇工作的逐项对照（全部来自一手摘要/正文，未推测）

| 维度 | CADT（2026-09-11） | 本 skill（Stage 1） | 关系 |
|---|---|---|---|
| 数据 | Therapeutics Data Commons（开放许可） | TDC + FDA DILIrank 2.0 独立队列 | 同数据族，本工作多一层异源外部队列 |
| 决策单位 | 化合物-靶标对（**样本级**） | 预测源在化学类/端点上的资格（**源级**） | **kind 差异，非 degree** |
| 门控信号 | 集成亲和力估计 + 认知不确定性 + AD check + ADME-T 软标志 | AD 域门（kNN Tanimoto）+ 源独立性审计（29 源→14 独立组） | 信号不同：CADT 用不确定性，本文用域与来源独立性 |
| 下游 | 分子对接（昂贵物理计算） | 投票/BMA/stacking（统计组合） | 决策层不同 |
| 分割 | 3 split × 5 seed（含 cold-target/cold-drug） | 20 seed 配对 + 时间留出 + FDA 独立队列 | 都做了非随机分割 |
| 评估 | CI 0.866±0.006；ADME-T AUROC 0.65–0.91；对接减少 86%、保留 61% 强结合物 | 精确符号翻转置换 2^20 + Holm；9 代价点 × 3 端点；化合物级 bootstrap | CADT 报保真率，本工作报代价边界 |
| 核心结论 | "uncertainty and AD terms act as an **abstention mechanism rather than accuracy gain**, and abstention is **not free**" | "价值来自弃权不来自准入；准入净收益符号在 cABS 0.2–0.5 翻转" | **同向** —— 独立复现 |
| 代价函数 | 无统一三价代价；以"送入对接比例"为成本代理 | 统一 c_false_PASS / c_false_FAIL / c_abstain，扫描 9 点 | **本文独有** |

## 2. 可直接写进 Discussion 的段落（英文成稿）

> Independently of our framework, CADT (Yalcin Ozkat, 2026) reached the same qualitative conclusion on the
> same public data ecosystem: in a confidence-gated docking triage, ensemble uncertainty and
> applicability-domain checks acted as an abstention mechanism rather than an accuracy gain, and the
> authors explicitly noted that this abstention is not free. We regard this convergence as external support
> for our framing — but also as a boundary on our priority claim. The two studies differ in kind: CADT
> gates individual compound–target pairs before an expensive physics calculation, whereas we gate
> *prediction sources* before statistical combination, and we quantify the cost region in which such
> source-level admission ceases to pay for itself (cABS ≈ 0.2–0.5, with the preregistered reference point
> on the failing side). CADT's cost proxy is the fraction of compounds routed to docking; ours is a shared
> three-valued utility over false PASS, false FAIL and abstention. The agreement of the qualitative
> conclusion across these two different units of decision suggests that the abstention trade-off is a
> property of the decision layer rather than of one particular application.

## 3. 必须同时写明的三条边界（防止被判为蹭热点）

1. **不得声称 CADT 验证了本文的 cABS 边界**——CADT 没有统一代价函数，只报"送入对接比例 86%/保留 61%"；
   两者结论同向但不共享数值刻度。
2. **不得声称 CADT 是前瞻验证**——它是回溯对接模拟，其作者自己写"a prospective docking study would turn
   projected savings into measured ones"。本文同样是 Stage 1 回溯，两者都不构成前瞻证据。
3. **必须承认priority**：CADT 先发表（2026-09-11），"abstention is not free"这句表述归它；本文的增量是
   把该结论下推到源级并给出代价边界。

## 4. 由此得到的一个新实验设计（Stage 2 优先项）

ADMET-EvO（arXiv:2609.10121）采用 **source-held-out** 才解除外部观测隔离；本文已有 29 源/14 独立组的
来源独立性审计（`references/SOURCE_DEPENDENCE.md`）。两者结合可设计一个比现有 20-seed 配对更强的验证：

- **设计**：按 `independence_group` 做分组留出（group-fold），每次留出 1 个独立组，在该组上评估
  "准入层是否仍改变决策排序"；
- **判据**：与本文 H2 同口径——在 cABS ∈ {0.05, 0.1, 0.2, 0.5, 1.0} 上，S4−S1 的符号是否在多数
  held-out 组上一致；若符号跨组翻转，则失效边界不具备跨来源可推广性，**必须如实报告**；
- **价值**：这直接回应"data-incest / 重复计数"的最强批评，也是 ADMET-EvO 之外把 source-held-out
  用在同一决策层的首个设计；
- **可执行性（2026-11-24 实测）**：**当前不能执行**。已核实 `out_ext/tdc/gate_scores_{hERG,DILI,BBB_Martins}.csv`
  的列只有 `idx, y_true, model_prob, model_pred, model_correct, sim, gate_passed`——**没有 source / 来源组字段**，
  无法把分子映射到 `SOURCE_DEPENDENCE.md` 的 14 个独立组。

**边界（必须保留）**：本条是设计提案，不是已完成结果。逐分子表无来源标识，因此本条正式降级为
**"Stage 2 重跑预测管线时必须逐条记录 prediction_source 与 independence_group"**的前置要求；
在此之前不得引用任何 source-held-out 结果，也不得暗示该验证已做。
