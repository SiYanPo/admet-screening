# 主文骨架 + OSF 预注册清单（v4.4）

> 来源：第三轮评审 §H——"这个 skill 的科学内容已经够发论文了——它现在缺的是**停止做实验、
> 开始写论文的决断**"。本文档就是那个决断的可执行形式：**每张图对应一个已存在的产物文件**，
> 没有一个"待做实验"的空位。
>
> 纪律：**本文档只允许出现已经存在于仓库里的产物**。任何"待补"的图必须显式标 ⛔。

---

## 一、标题与核心命题

**工作标题**：*Evidence admission before evidence combination: a testable, self-falsifying
decision layer for ADMET prediction*

**命题（可证伪形式）**：在给出任何 PASS/FAIL 裁决之前，必须先回答"这个证据体是否应被赋予非零权重"；
该层**不是**组合器内部的一个权重项，而是独立、可审计、可被推翻的前置决策层。

**三条可证伪预测**（写进 Introduction 与预注册）：
1. 在域内，加入准入层**不会**优于纯置信度弃权（因为它没有可增加值）——**已证实**（S4 vs S1）。
2. 【2026-11-04 **已撤回**】~~在域外，准入层会拒答；而强行预测会显著劣于平凡基线
   ——已证实（三切点）~~。**撤回理由**：唯一量化支点是 `auc < always_positive_accuracy`
   的跨量纲比较（C01）；正确双轨口径下 `accuracy_below_majority_class` =
   True/False/True，三切点为嵌套子集不构成独立复现；且 hERG 端点 estimand 未定义，
   AUC/accuracy 均不承载决策含义（外审 B）。**不得翻转为「有弱排序能力」**。
   见 `references/RETRACTION_NOTE.md`。
3. 【2026-11-04 **已撤回**】~~准入层的条件性价值可用弃权代价刻画，无差异点存在且
   可估计——已证实（c\* 0.21–0.26）~~。**撤回理由**：外审 A 独立复算得
   Δu(c)=a−q·c（R²=0.9999995、q=0.8189、c\*=0.2598），「无差异点」是
   线性函数零点的**会计恒等式**，代价参数 `costs` 在 `pick_threshold` / `strategies`
   函数体内零引用（AST 已证），不进入决策掩码 → 不可证伪。见 C18 / B6 与
   `references/IRREDUCIBLE_LIMITS.md`；重构方案见 `references/ESTIMAND.yaml`。

---

## 二、图目录（每张图 = 一个现有产物）

| 图 | 内容 | 产物（仓库内路径） | 状态 |
|---|---|---|---|
| **Fig 1** | 框架数据流与"准入层"在管线中的位置（单向、可审计、带归因） | `references/EVIDENCE_DAG.md`、`SKILL.md` §核心贡献 | ✅ 可直接画 |
| **Fig 2** | 基石实验：4 策略 × 9 代价点 × 20 种子的 Δutility | `out_keystone_v43/results.json`、`out_blacklist/tables.md` 表1 | ✅ |
| **Fig 3** | **无差异曲线**：c\* 的定位（hERG 0.26 / BBB 0.2091 / DILI 未识别） | `out_ext/keystone_indifference.json` / `.md` | ✅ |
| **Fig 4** | **规格敏感性**：216 规格的方向分布 + 翻转率 0.398 | `out_ext/keystone_spec_multiverse.json` / `.md` | ✅ |
| **Fig 5** | gate 判别力的**端点依赖**：0.580 / 0.669 / 0.514 + 多判据四法全 <0.65 | `out_ext/tdc/gate_audit{,_DILI,_BBB_Martins}.json`、`out_ext/tdc/ad_multicriteria.json` | ✅ |
| **Fig 6** | 【**RETRACTED 2026-11-04 / C01**】~~外源三切点：AUC vs 平凡基线~~。改画**双轨并列图**：左轨 AUC + 95%CI 对照 0.5；右轨 accuracy@0.5 对照 prevalence + 逐分子差配对 bootstrap CI；并标注三切点为嵌套子集、`inference_revoked_pending_estimand` | `out_ext/external/external_cuts_summary_v2.json`（旧 `external_cuts_summary.json` 已标 `superseded_by`，仅作审计证据） | ❌ **撤回，不得入稿** |
| **Fig 7** | **独立性梯度**：α 0→1 时 ρ_within 与 vote_gain 的背向而行 | `out_ext/tdc/independence_gradient.json` | ✅ |
| **Fig 8** | MMP 双向检验：悬崖召回 vs 守静特异度（含 DILI 的 `insufficient_power`） | `out_ext/tdc/p8_mmp_results*.json`、`gate_audit*.json` | ✅ |
| **Fig 9** | **Ames 双方法层**：放行错误率 0.2685 → 0.177 与放行率代价 | `out_ext/tdc/ames_alerts.json` | ✅ |
| Table 1 | 端点分级与文献依据（含 ICH M7(R2) 条款） | `references/ENDPOINT_TIER_EVIDENCE.md` | ✅ |
| Table 2 | 主张×产物×字面量（可复算清册） | `references/CLAIMS_REGISTRY.yaml`（19 条） | ✅ |
| Table S1 | 阈值 census（11 条，含来历与冻结状态） | `references/THRESHOLD_REGISTRY.yaml` | ✅ |
| Fig S1 | 近邻泄漏归因（含 BBB −0.212 **未解释**） | `out_ext/tdc/leakage_attribution.json`、`leakage_confound_check.json` | ✅ |

> **【2026-11-04 C01 撤回】Fig 6 旧画法已作废，禁止再画 "AUC vs 平凡基线"。**
> 旧画法把 AUC（随机基线 0.5）与 always-positive accuracy（= prevalence，分类
> 准确率基线）放在同一坐标轴比较，属跨量纲错误，且是旧主文合成句的唯一量化支点。
> 新画法（若重估后仍允许入稿）：左轨 AUC + 95%CI vs 0.5；右轨 acc@0.5 vs
> prevalence + 配对 bootstrap CI；同图标出桶级趋势不稳健与三切点嵌套关系。
> **在 hERG 端点 estimand 卡（`references/ENDPOINT_ESTIMAND_CARDS.yaml`）绑定实验
> 金标准之前，本图不得承载任何「门该不该拒答」的决策结论**（外审 B）。
> 只画 mixed 的 0.581 与一条上升曲线 = 选择性呈现；画 AUC 与 0.679 比大小 = 量纲错误。

---

## 三、章节骨架

1. **Introduction**
   - 现有 ADMET 集成框架把"源资格"隐含在组合器内（多数投票 / 适用域 / 校准 / D-S）；
   - 命题：资格判断是**前置**问题；给出三条可证伪预测。
2. **Methods**
   - 2.1 决策层定义与数据流（Fig 1）；三态裁决 + 归因码 + 计票账目；
   - 2.2 独立性感知权重（`n_eff = k²/(1ᵀR1)`，含红 6 更正）；
   - 2.3 统计规范：CI / 配对 / 功效驱动弃权 / 中位数口径（`STATISTICAL_POLICY.md`）；
   - 2.4 复现骨架：命令 → 数据 hash → 环境指纹 → 结论（四元组）。
3. **Results**
   - 3.1 域内：准入层**不优于**纯置信度弃权（Fig 2）；~~但存在条件性优势区（Fig 3、Fig 4）~~ **【2026-11-04 撤回 / C18 + 外审 A】**：该「条件性优势区」来自 Δu(c)=a−q·c 会计恒等式，代价未进入决策，不是可证伪结论；Fig 3 / Fig 4 须重画或删除。
   - 3.2 域外：门是唯一合格组件，但**门不精确**（Fig 6）；
   - 3.3 判别力的端点依赖（Fig 5）+ MMP 的功效边界（Fig 8）；
   - 3.4 唯一的行为改变：Ames 双方法层（Fig 9）。
4. **Discussion（必须包含的四条限制，缺一条即不诚实）**
   - L1 三源仍是"同一训练集上的三个模型"；A1 显示**方法同源**才是独立性瓶颈（Fig 7）；
   - L2 外源只有**一个数据源**的两个年份切点，不是第二个端点；
   - L3 BBB 近邻归因的 −0.212 **未解释**；
   - L4 阈值多为文献惯例，未实测标定（Table S1 明示 `frozen:false`）。
5. **Conclusion**：把"成年礼"写成一句——**科学命题的成年礼不是被证明，是被正确地限定。**

---

## 四、OSF 预注册清单（一个下午能填完）

| 项 | 现在就能填的内容 | 需要决定的事 |
|---|---|---|
| 研究问题 | 三条可证伪预测（上文；#2 / #3 已于 2026-11-04 撤回） | **禁止**把「条件性优势区」作为主假设（C18）；主假设须在 ESTIMAND.yaml 中重新绑定 estimand |
| 主结局 | Δutility(S4−S1) 在 ref 代价点（**仅探索性描述**） | ~~副：c\*~~ **已撤回**（会计恒等式零点，不可证伪）；主结局须重新定义 |
| 分析计划 | 20 种子配对 bootstrap；216 规格 multiverse；三端点并列 | 是否预注册"翻转率 >0.20 即判 fragile" |
| **外部验证** | 明确写："外源为**时间留出**（≥2021 / ≥2023），非前瞻盲测" | 是否承诺追加**第二端点**（DILI）作为真正的前瞻盲测 |
| 停止规则 | 三切点方向不一致即不下结论（已在脚本里代码化） | — |
| 数据与代码 | 全包 sha256 + `MANIFEST.internal.sha256` | 选 Zenodo 还是 OSF 附件 |
| 版本纪律 | `4.0-dev` → 只有外源盲测完成后才允许 `v4.0` | 谁能授予标签（建议：第三方） |
| 利益冲突 | 无 | — |

**最关键的一条**：预注册表里必须写清 **"本工作已经知道域内结果"**。
否则前瞻部分会被读成"事后补的预注册"——这正是本包批评别人的地方，不能自己犯。

---

## 五、写作顺序（评审建议的执行顺序，不再改）

1. 先写 Methods 的 2.1 + 2.3（不依赖任何新数据）；
2. 再写 Results 的 3.1（Fig 2/3/4 全部现成）；
3. 然后写 3.2（Fig 6，注意 §二的警告）；
4. Discussion 的 L1–L4 **最后写**，但**必须先写**——它是全文的诚信底线；
5. Introduction 最后写（此时才知道自己接在哪条线上）。

---

## 六、这份骨架**没有**解决的事（诚实登记）

- ⛔ **第二数据源/端点的外源复制**：没有 → Discussion L2 必须写明；
- ⛔ **第三方实现者**：`submission.json` 是自检（`submitted_by` 已诚实标注），不构成独立复现；
- ⛔ **阈值实测标定**：需要湿实验数据，本包没有；
- 🟡 **Ames 规则表的完整性**：只覆盖官能团级最小集，不等价于 Derek/Sarah 全表（`ames_alerts.json::caveat`）。

> 这四条写进 Limitations 后，主文的可发表性**不依赖**它们被解决；
> 但如果不写，任何一条被审稿人翻出来都会推翻整篇的可信度。
