# 9. 可靠性方法的生态位：证据准入先于证据组合

> 工作包 K（v3.1.0）。本文件回答审稿人必问的一句：
> **"你的框架与 conformal、适用域（AD）、DST/证据组合、多数投票相比，到底解决什么不同的问题？"**
> 答案不是"我们更准"，而是：**我们处理的是"某个证据体是否应该被赋予非零权重"，
> 这是所有下游组合/校准/区间方法的前置条件。**

## 9.1 分工表（可直接放进论文 Discussion）

| 策略 | 它解决什么 | 它不解决什么 | 与本框架的关系 |
|---|---|---|---|
| 多数投票 / 共识聚合 | 多个预测的机械汇总 | 源间分歧的结构性解释；域外源仍投票 | 本框架在分歧/域外区域**拒绝**强行共识 |
| 适用域（AD）/ 相似性 | 单个模型的外推检测 | 多源之间的独立性与准入资格 | AD 信号是本框架的**输入之一**，不是替代 |
| Conformal prediction | exchangeability 下的有限样本覆盖 | 分布偏移下的覆盖失效；证据准入 | 本框架的弃权**不依赖** exchangeability；conformal 区间可作为分数型基线 |
| 校准（Platt/isotonic/Brier） | 单模型概率可信度 | 多源单位异构、版本漂移、域外 | 校准前必须先过**单位/版本/域外**准入 |
| Dempster-Shafer / WoE（TOXTRUST） | 已知证据体之间的冲突组合 | 某个证据体是否应被赋予非零 mass | 本框架是**组合的前置层**：先做资格判定，再做组合 |
| **本框架** | **证据准入**：结构 gate、域外 block、单位守卫、独立组计票、伪共识检测 | regulator-grade PBPK、湿实验真值、晶型/生殖毒性 | 组合/校准/区间的**上游** |

## 9.2 一句话论证链

1. **问题不是"哪个源更准"**，而是"在给定化学类与端点下，哪些源有资格参与裁决"。
   （OneADMET, JMC 2026：多平台反复使用 Tox21/TDC/2000–2015 数据集，多平台 ≠ 多来源。）
2. **资格判定不能由组合算法代劳**：把域外源赋 ignorance（θ=1）在 Dempster 下是单位元，
   与"排除"等价；真正制造过度裁决的是"已登记域外但仍投概率票"的源。
3. **本框架的贡献是准入层**：`apply_class_blocks`、`out_of_domain` 强制无值、单位守卫、
   独立组计票、伪共识检测——这些是**结构性预防**，不是调参。
4. **准入层的价值可被四类外部证据检验**（v3.1.0 已给出可执行入口）：
   - 行为证据：`selective` 的 risk–coverage / 留一源 holdout；
   - 决策论证据：`decision-value` 的固定预算期望效用；
   - 概念合法性：`certainty` 的 GRADE 维度映射；
   - 工程可靠性：`failure-modes` 的检测 precision/recall（有标签时）。

## 9.3 什么时候本框架不适用

- 只要单分子 logP/logS：直接用 RDKit，跑本框架是过度工程。
- 需要 regulator-grade PBPK：用 Simcyp/GastroPlus；本框架只给量级。
- 没有多源、没有域外、没有单位异构的"干净"批次：准入层退化为恒真，
  价值下降——此时应直接用单源 + AD，不必上本框架。
- 需要"一个综合分排名"：本框架默认拒绝排名；要排名必须过四条件守卫。

## 9.4 与 20 篇文献的对接（新增部分）

| 文献 | 用途 |
|---|---|
| OneADMET (JMC 2026) | "多平台 ≠ 多来源"的问题锚点；支撑独立组计票 |
| Parrondo-Pizarro et al. (J Cheminform 2025) | 公开 ADME 数据错位/不一致；支撑单位与版本守卫 |
| Jeffreys (1946) / Agresti & Coull (1998) | **u(k) 伪计数平滑的真实出处**（C4 更正） |
| Clark (2014, Clark RD et al. J Cheminform 6:34) | 协议 step 7 显式使用 `(err+0.5)/(n+1)` 连续性修正 → **合法次级引用**；但其 headline 方法是 beta-binomial 拟合并非本式（C4 已查原文，2026-11-03） |
| Fleiss (1971) | 多评分者一致性 κ |
| Vickers & Elkin (2006) | 决策曲线 / 净收益 |
| GRADE Guidelines 30 | 模型证据确定性分级的维度映射 |
| OpenADMET blind challenges (2026) | 前瞻性裁决层验证的候选数据（非本项目数据） |
| NPASS 3.0 三工具基准 (2026) | 中等规模公开演示的候选数据（天然产物空间） |
| Honest ADMET (2026) | 分布偏移下 conformal 失效、弃权信号模型依赖 |

> **2026-11-25 经 Zenodo API 一手核实**（record 20710324，2026-06-16，Imdad Suleman，CC-BY-4.0，GitHub real1900/honest-admet）：
> 真实标题为 **"Honest ADMET: When the Generalization Gap Appears, Why, and Whether Selective Prediction Recovers It"**。此前稿件参考文献 15 曾写成 "selective prediction and applicability-domain effects across 22 endpoints"，属**编造副标题**，已改回真实标题。
> 可直接引用的四条实证：①split-conformal 在 cluster shift 下 under-cover；②covariate-shift weighting 是 verified no-op，不恢复覆盖；③最佳弃权信号 model-dependent；④**per-endpoint abstention benefit 与 optimism gap 不相关（Spearman rho = 0.07, n.s.）**。
> 第④条与本 skill 的「c* 跨端点 4.3 倍」互为独立佐证：弃权收益既不能由泛化差距预测，其临界价格更不能由任何模型级指标推导，只能逐端点实测。方向一致但**不构成互相验证**（它是样本级/22 端点，本工作是源级/5 端点，且两为事后选取）。
| TOXTRUST / DST | 证据组合的对照基线；本框架定位为准入前置层 |

### Srivastava & Kassetty 2026（arXiv:2611.01512，**一手核实 2026-11-25**）

- 完整标题：*Abstention Spends Its Budget on Local Label Variance More Than on Novelty: Auditing Conformal Calibration and Selective Prediction under Molecular Scaffold Shift*
- 作者顺序：**Arnav Srivastava, Krishna Kassetty**；2026-11-01（v1）；arXiv:2611.01512 [cs.LG]，cross-list stat.ML；DOI 10.48550/arXiv.2611.01512；12 页/4 图/6 表；**预印本，未同行评审**
- 设计：单一 gradient-boosted fingerprint 模型；lipophilicity（回归）+ **BBBP（分类）**；Bemis-Murcko scaffold split；固定模型与评测分子，只变 calibration fold（18 replicates）
- 五条可引实证：
  1. 覆盖依赖 calibration provenance：lipophilicity 上训练支架校准低于名义（PICP 0.841 @ 0.90），novel-scaffold 校准恢复（0.904）；BBBP 各 regime 均高于名义
  2. **split CQR 的 conformal 校正是常数 → conformalization 不改变 abstain 对象**
  3. abstention score（CQR 宽度；BBBP 上实为 ensemble variance）**追踪 local label variance 而非化学 novelty**（控制后偏相关仅 0.067 / 0.047）
  4. 固定 assay 预算下，interval width / ensemble variance 门控**从未**超过按 point prediction 排序（预设点 + 20 个探索设置）
  5. conformal selection 的 FDR 控制依赖 provenance（探索性）
- 结论原句：*conformalization earns its keep through guarantees whose validity hinges on calibration provenance, not by choosing what to abstain on*
- **对本工作的两处用法**：
  - 共形预测分工：既然 conformal 层不选择 abstain 对象，选择必须来自别处，而 c* 正是给这个"别处"定价 → 两者是同一部署的**前后两问**（覆盖是否成立 / 是否付得起），非平替
  - R1 的经验对应物：设计者以为 gate 作用的信号（novelty/domain）与它实际作用的信号（label variance）可以不同；与本文"相似度定义的 gate 与相似度基线同源"的构造性论证合成双重支撑
  - **同端点交叉**：其 BBBP = 本文 BBB_Martins。该文 uncertainty gate 不胜过 point ranking；本文该端点 c*=0.209、参考价 0.50 落在失败侧。同端点、不同机制、同向——但不可当作互相验证（其门控为化合物级，本文为源级）
- 边界：单模型族、两端点、单一 scaffold split（作者自述 §5）；预印本


> 注（v3.2.0）：OpenADMET-ExpansionRx（CC-BY-4.0）与 NPASS 3.0 curated 子集（CC-BY-NC 非商业）
> **已随包分发**在 `assets/external/`；接入命令 `external` + `baseline`。
> `baseline_*` 是本项目训练的 Ridge 基线，不是外部工具；PASS/FAIL 阈值是分析选择。
> 评审提到的"NPASS 三工具 201,905 化合物"表不在官方 NPASS 下载包中，未随包分发。


### Zhao et al. 2026, J Cheminform 18:95（**一手核实 2026-11-25**）

- 完整标题：*Revisiting ADMET prediction reliability under real-world challenges in the foundation model era*
- 作者（9 位）：Donghai Zhao, Yuchen Zhu, Zhenxing Wu, Yue Wan, Xiaonan Liu, Shuaiyan Li, Hongxia Xu, Tingjun Hou, Chang-Yu Hsieh
- 2026-05-18；Vol 18, article 95；Research；开放获取；doi:10.1186/s13321-026-01217-2
- 内容：四大真实挑战基准（数据稀缺/OOD、类别不平衡、bRo5 化学空间、活性悬崖），评测 KPGT、Uni-Mol、TabPFNv2 等
- 主要发现：TabPFNv2 在 few-shot/OOD 常优于定制分子基础模型；欠采样集成缓解极端类不平衡；KPGT 在 bRo5 环肽渗透性最好；**所有模型类别都难以识别活性悬崖**
- 提出的诊断工具：**分子属性景观粗糙度指数**（MODI/SARI/ROGI），用于低成本筛选候选基模型
- **原文明确限定**：*since the roughness index is calculated over the global chemical space of the entire dataset, it inherently cannot predict performance degradation caused by OOD shifts between specific training and test sets*

> ⚠️ **常见误引警告**：有二手评审把它概括为"Zhao 等人展示了 ADMET 模型可靠性不能被内部指标预判"。**这不准确**。Zhao 的实际主张是：可靠性可由**数据端的景观粗糙度指数**做低成本预筛（MODI 在 MoleculeACE 上 r=0.92），并自认该指数**无法**预测特定 train/test 之间的 OOD 偏移。所以它是"外部诊断量"路线的先例，不是"不可预判"的证明。引用时必须带那句限定。
>
> 与本文 c* 的正确关系（不同层级的外部诊断量）：粗糙度指数刻画**化学空间在选模型之前可不可建模**；c* 刻画**模型已存在后某个决策设计在什么价格下值得**。二者都拒绝从模型内部指标推断部署可靠性，但诊断对象不同，**互不替代**。
