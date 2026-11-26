# 端点三级分级的文献依据（黑榜第 6 项）

> 背景：评审指出「把 DILI/Ames/致癌性 标为 not_recommended」主要靠自家实测，
> 缺外部依据，容易被读成「我们的模型在这些端点上不行，所以说不该用」。
>
> 本文件补上外部依据，并把逻辑倒过来：
> **不是因为模型差才不建议裁决，而是因为这些端点的二值标签本身不构成可裁决的真值。**
>
> 写这条界限时必须同时说清反面：即使标签噪声只有 10%，模型 80% 的一致率**仍然是模型的问题**，
> 不能拿标签噪声当免责声明。下面 §4 专门写这一点。

## 1. 判定标准（先定标准，再引证据）

一个端点可以进 `adjudicable`（允许输出 PASS/FAIL），需同时满足：

| 条件 | 含义 | 可检验的形式 |
|---|---|---|
| A. 真值稳定 | 同一化合物在不同来源/不同实验室的标签不冲突 | 标签冲突率有公开估计，且 ≤ 可接受上限 |
| B. 端点定义单一 | 「阳性」在各数据集里指同一件事 | 存在公认的判定规则（如 OECD TG 471 的 2 倍规则） |
| C. 噪声底已知 | 知道多好算「已经到顶」 | 有重复性/一致性数据可作天花板 |

三条中任一不满足 → 最多 `qualitative_only`；A 与 B 同时不满足 → `not_recommended`。

## 2. Ames：噪声底 ~10%，天花板已知

- **重复性估计**：基因毒性试验指南的不确定性综述（*Arch Toxicol* 2025,
  doi:10.1007/s00204-025-04277-9, Table 14）汇总 Ames 二分类结果的平均一致性约 **90%**，
  来源为 Benigni & Giuliani (1988, 42 化合物 / 12 实验室)、Piegorsch & Zeiger (1991, 209 化合物)、
  Sushko et al. (2010, 1680 化合物)。
- **不一致不是随机的**：Benigni & Giuliani（*J Am Coll Toxicol* 1988,
  doi:10.1080/15287398809531194, PMID 3418743）在 12 家实验室中发现 **2 家系统性偏离**，
  疑与代谢活化（S9）方案差异有关 → 说明"同一化合物不同结论"有**方法学来源**，不是抽样噪声。
- **实验内/间变异**：*Mutation Research* 1984（doi:10.1016/0165-1161(84)90004-9）
  在标准化协议下测得背景重复变异平均 **26%**，剂量相关变异在实验间 28–54%、
  实验室间 44–127%。
- **结论**：Ames 满足条件 C（天花板 ≈ 90% 一致性），但**部分不满足 A**（同一化合物可因
  活化方案不同而结论相反）。因此本框架把它放在 `not_recommended` 是**偏保守**的：
  更准确的档位是 `qualitative_only`（可给"致突变信号强弱"，不做二值裁决）。
  **本版不改档**，理由见 §4。

## 3. DILI：二值标签在文献层面就互相冲突

- **同一化合物标签相反**：*Arch Toxicol* 2020（doi:10.1007/s00204-020-02763-w）明确给出
  **11 个化合物在文献中同时被标为 DILI 阳性与阴性**。原文举例：吡格列酮
  （Pioglitazone）被 Chen et al. (2016) 归为「Less DILI severity」，被 Garside (2014)、
  Proctor (2017)、Gustafsson (2014) 归为体内 DILI 阳性，而被 O'Brien (2006)、Xu (2008)、
  Dawson (2012)、Persson (2013) 判为无 DILI 潜力。
- **数据集层面的系统性局限**：*J Med Chem* 2026, 69(13):14992 的综述归纳四条：
  ① 早期数据集（Cruz-Monteagudo / Xu / Greene）依赖病例报告与异质因果评估，
  DILIrank / DILIst 虽更标准化但仍在演化，**不同模型实际在学习不同甚至冲突的"阳性"定义**；
  ② 负标签质量不确定——"没有报道肝毒性"不等于"安全"，尤其对新药或罕用药；
  ③ 几乎所有数据集**缺剂量/暴露信息**，编码的是"危害"而非"风险"；
  ④ 机制标注稀疏。
- **二值化是人为选择**：DILIst（Thakkar et al.）把多源注释映射成 1279 个化合物的
  二值标签（768 阳性 / 511 阴性）；DILIrank 2.0 覆盖 1336 个化合物并**重访了原注释**——
  "重访"本身就说明旧标签会变。
- **结论**：DILI 同时不满足 A（标签冲突）与 B（定义不单一），故 `not_recommended`。

## 3.1 致癌性：重复实验一致率只有 57%（比 Ames 低一个档）

- **直接证据**：Gottmann、Kramer、Pfahringer & Helma（*Environ Health Perspect* 2001,
  109(5):509–514, doi:10.1289/ehp.01109509, PMID 11401763）把 **Carcinogenic Potency Database
  (CPDB)** 中来自 NCI/NTP 与文献两部分的 **121 组重复**啮齿类致癌性实验做了对照，
  得到整体致癌性分类一致率 **57%**；并且**加入物种、性别、品系、靶器官等生物学信息后
  一致率没有实质提升**。作者结论：啮齿类致癌实验的可重复性"远低于此前预期"。
- **为什么这条对分级最致命**：一致率 57% 意味着**同一化合物两次"独立"实验给出相反结论的
  概率接近抛硬币**。条件 A（真值稳定）在这一水平上**明确不满足**——不是"噪声略大"，
  是"真值本身不稳定"。
- **与 Ames 对比**（§2 的 ~90%）：同为"实验室测出来的端点"，致癌性的天花板比 Ames 低
  33 个百分点。因此 Ames 只是"偏保守"，而致癌性 `not_recommended` 是**有直接依据**的。
- **本框架采用的口径**：即使标签一致率只有 57%，也**不构成"计算模型做不到就是端点不行"的
  免责**（见 §4），我们只是据此说明"在这个端点上要求 PASS/FAIL 缺乏可裁决的真值"。

## 3.2 nr_ar_lbd：单测定确实脆，但"通路级"证据反过来不支持 `not_recommended`

这一类端点的证据是**分裂**的，必须两条一起写，只引前一条就是选择性引用：

**(a) 支持"单测定不可裁决"的证据**

- Huang et al.（*Environ Health Perspect* 2011, 119(8):1142,
  doi:10.1289/ehp.1002952, PMID 21543282）用 Tox21 pilot 库约 3,000 个环境化学品，
  对 10 个核受体（含 AR）做 qHTS 复孔重现性评估，结论是：
  **agonist 模式的重现性优于 antagonist 模式**，后者主要受**细胞毒干扰**；
  该研究还按数据质量把测定分为 A–D 级，**C/D 级测定需要换细胞类型、换技术
  （luciferase 替代 bla）或换读出方式**来替代。也就是说，"某一条 NR 报告基因测定的
  活性判读"在 Tox21 自己的质量体系里就是**可被降级/替换**的对象。
- Klimenko（*Toxicol Appl Pharmacol* 2020, doi:10.1016/j.taap.2020.115338,
  PMID 33217376）对 Tox21 库约 8,300 个化合物、**35,328 条 AR 激动剂量-反应曲线**做复核，
  发现存在**非单调剂量-反应（NMDR）**（含已知拮抗剂如醋酸环丙孕酮），并系统研究了
  **细胞毒与萤光素酶干扰**带来的偏倚。NMDR + 干扰意味着"active/inactive 二值化"
  这个动作本身会丢信息。
- Tox21 的 AR 数据本身来自**两套不同测定**（BLA：大鼠 AR-LBD + β-内酰胺酶报告；
  MDA：MDA-kb2 AR-luc 萤光素酶报告），跨测定合并时必须靠规则消解分歧
  （见 *Front Pharmacol* 2019, 10:1044, doi:10.3389/fphys.2019.01044）。

**(b) 反向证据：通路级模型表现很好，削弱了"端点不可裁决"的说法**

- Kleinstreuer et al.（*Reprod Toxicol* 2018, 81:272–280,
  doi:10.1016/j.reprotox.2018.08.017, PMID 30205137）用 **39 个体内效应可重复的参考化学品**
  检验基于 **11 条 AR 通路测定**的 ToxCast/Tox21 AR 模型：总体一致率 **66%（19/29）**，
  另有 10 个"不确定"，但**阳性预测值 100%（无假阳性）**——凡模型给出确定结论的化合物，
  体内均一致。作者据此认为体外 AR 模型在"识别 AR 特异性相互作用"上可以优于体内
  Hershberger 试验（后者自身可重复性亦差）。
- **必须承认的读法**：这是**多测定通路模型**的结论，不能直接搬到"单条 nr_ar_lbd 测定"上；
  但它足以证明**"AR 这一生物学轴不可计算"是错的说法**。

**结论**：`nr_ar_lbd` 维持 `not_recommended` 的现有理由只有 (a)，而 (b) 指向相反方向。
诚实的表述是：**单测定二值化不可裁决，通路级多测定可裁决**。因此本框架的档位
**偏保守**，合理档位应为 `qualitative_only`（给"AR 通路活性方向"，不做单测定二值裁决）。
**本版不改档**，与 Ames 同理（见 §4），但必须把"保守"写在明处，不能包装成"有文献依据"。

### 3.3 监管指南（最硬的一类依据）：ICH M7(R2) 直接规定了 Ames 该怎么用

前面 §2 的"噪声底"是文献证据，它只能说明"这个端点难"；**ICH M7(R2) 是监管指南，
它直接规定"这个端点必须怎么用"**，性质不同，不能混为一谈。

**指南原文要求（§6，逐条对应）**：

1. 用 (Q)SAR 预测细菌回复突变性时，必须采用**两种互补的预测方法**：
   一种**基于专家知识规则**（expert rule-based），另一种**基于统计学**；
2. 两类方法均须符合 **OECD (Q)SAR 验证原则**（明确终点／明确算法／确定适用域／
   拟合优度与稳健性／预测能力）；
3. **两种方法均无警示结构时**，方可判该物质"无致突变关注"（Class 5），
   无需进一步试验；
4. **Q&A 6.2**：两种模型中**任一**给出"域外 / 未覆盖"结果时，**不得**据此判 Class 5，
   必须补充评估（类似物 read-across、专家复核、或另一个已验证模型）。

**对本框架的直接后果（这是本轮改档的唯一依据）**：

本框架原有三个源（RF-Morgan / Ridge-描述符 / RF-MACCS）**全部是统计模型**。
按上面第 1 条，它**根本不满足**双方法要求——所以 ames 被登记为 `not_recommended`
在方法上是**正确的**，只是当时的理由写错了（写成"计算侧域外"，实际是"方法链不全"）。

本轮补齐第一法：新增 `adt/alerts.py` 结构警示层（17 条官能团级规则，可逐条审计），
并提供 `two_method_verdict()` 把上面 4 条规则实现成代码（v4.3 作为库与基准存在；
**生产接线在 v4.4 由 `reliab --enable-alerts` 完成**，见章末说明）。实测（TDC AMES test，n=1457，
阳性率 0.597，`out_ext/tdc/ames_alerts.json`）：

| 方法 | 敏感性 | 特异度 | PPV |
|---|---|---|---|
| 结构警示层（含弱规则） | 0.672 | 0.567 | 0.697 |
| 结构警示层（仅核心 16 条） | 0.659 | 0.589 | 0.704 |
| 统计模型（RF-Morgan） | 0.821 | 0.724 | 0.815 |

| 策略 | 判 PASS（Class 5 方向） | 占全体 | **放行错误率**（被放行的真致突变物 / 放行数） |
|---|---|---|---|
| 只看统计模型 | 581 | 39.9% | **0.269** |
| ICH M7 双方法 | 226 | 15.5% | **0.177** |

**三个必须一起读的结论**：

1. **双方法确实有用**：放行错误率从 0.269 降到 0.177（相对降 34%），代价是放行率从
   39.9% 压到 15.5%。这不是"我们的模型变好了"，是"ICH 指南要求的保守性起了作用"。
2. **警示层单独很弱**：特异度 0.567，几乎等于基率。所以它**只能**用于"命中即升级"，
   **绝不能**用于"未命中即放行"——这条已写进模块 docstring 与档位理由。
3. **0.177 仍高于本框架自己定的目标风险 0.15**。所以 ames 即便升为 `qualitative_only`，
   其 PASS 结论**不得**进入目标风险 <0.177 的决策，更不得推导任何限量数值。
   这也是"仅定性"三个字的实际含义，不是修辞。



1. **噪声底 ≠ 免责线**。Ames 天花板 ~90%，若模型只有 80% 一致率，那 10 个百分点是模型的问题，
   必须报出来。本框架的做法是：**同时报模型一致率与已知噪声底**，让读者自己算差距，
   而不是只报"标签有噪声"。
2. **不许用本条把实测失败改写成"端点不可用"**。run6 的 7 条可执行判定全部落在 DILI/Ames，
   被端点政策清零（0 PASS / 0 FAIL）——这是**框架当初就不该在这些端点上承诺裁决**，
   不是"模型其实很好但端点太差"。
3. **致癌性 / nr_ar_lbd 已补逐条引文（2026-10-31 更新）**。致癌性属于"证据支持
   `not_recommended`"（§3.1，一致率 57%）；nr_ar_lbd 属于"证据分裂、现有档位偏保守"
   （§3.2）。两者的性质不同，**不得合并成一句"这两个端点都有文献依据"**。
   旧版把两者都标成"缺引文"，该缺口已关闭。
4. **引文可核验性**：本文所有 DOI/PMID 均来自公开检索结果，未逐篇下载全文核对原文措辞。
   引用时请以期刊页面为准；若与原文有出入，以原文为准。

## 5. 对分级表的直接后果

| 端点 | 当前档位 | 依据强度 | 备注 |
|---|---|---|---|
| hERG / BBB_Martins / 溶解度 / 渗透性等 9 项 | `adjudicable` | 中（本次未系统核查） | 属"工程可用"，非"标签无争议" |
| **Ames** | **`qualitative_only`（本轮改档）** | **强**（§2 + §3.3 指南） | ICH M7(R2) 允许双 (Q)SAR 替代；`reliab --enable-alerts`（v4.4 默认开）已接线，扫描 SMILES 做真实双方法合成；基准放行错误率 0.177 |
| DILI | `not_recommended` | **强**（§3） | 标签冲突有直接文献 |
| 致癌性 | `not_recommended` | **强**（§3.1） | CPDB 121 组重复一致率 57%，证据支持现档位 |
| nr_ar_lbd | `not_recommended`（**理由已改写**） | **分裂**（§3.2） | 单测定脆、通路级 PPV 100%；本框架无多测定聚合能力，故仍不推荐——但**不得**再写"与计算表征脱节" |

> 这张表的作用是让"不推荐"变成**可反驳的**：任何人可以指出某端点其实满足 A/B/C 三条，
> 我们就应当把它升档。反过来，若某端点被证明连 C 都不满足，则应保持在最低档。
>
> **本轮据此做了一次升档**（Ames → `qualitative_only`）。
> v4.3 补了 `adt/alerts.py`（专家规则层）、`two_method_verdict()`（ICH M7 四条规则），
> 以及 `apply_tier_policy()` 里"必须启用专家层"的**拒绝约束**；但**该约束在生产管线里
> 从未被满足**——`reliab` 当时并未调用 alerts.py、`expert_rule_layer` 在生产流中永不被设置，
> 导致 ames 在真实 `reliability.csv` 里**仍全 UNDETERMINED**。这是外部评审反复抓到的
> "文档声称（已补专家规则层 / 已升档）≠ 实际行为（永远不判）"的脱节实例。
> **v4.4（2026-11-02）真正补上接线**：`reliab --enable-alerts`（默认开）+ `--compounds`
> 现在对每个 ames 成分用 SMILES 跑 alerts.py、置 `expert_rule_layer=True` 并做双方法合成，
> 华山参实测 ames 由 59 全 UND 变为 **9 PASS / 15 FAIL / 35 UND**
> （与独立双方法计算 100% 一致，0 错配）。
> 教训：**"补了库 + 写了拒绝约束"不等于"已接线"**——必须有生产流把约束真正满足、
> 并有回归测试（`tests/test_ames_alerts_wired.py`）锁住，否则就是"用指南当挡箭牌"。

## 6. 参考（按出现顺序）

1. *Arch Toxicol* 2025. Variability and uncertainty of data from genotoxicity test guidelines.
   doi:10.1007/s00204-025-04277-9（Table 14 汇总 Ames ~90% 二分类一致性）
2. Benigni R, Giuliani A. 1988. Computer-assisted analysis of interlaboratory Ames test
   variability. doi:10.1080/15287398809531194, PMID 3418743
3. *Mutation Research* 1984. Statistical evaluation of inter- and intra-laboratory variations
   of the Ames test. doi:10.1016/0165-1161(84)90004-9
4. *Arch Toxicol* 2020. The evolution of strategies to minimise the risk of human DILI in drug
   discovery and development. doi:10.1007/s00204-020-02763-w（11 个化合物双标签；吡格列酮实例）
5. *J Med Chem* 2026, 69(13):14992. Machine Learning-Based Models to Predict DILI to Assist
   Medicinal Chemistry（DILI 数据集的四项系统性局限）
6. Thakkar et al. DILIst（1279 化合物，768/511）
7. DILIrank 2.0（1336 化合物，重访原注释）
8. Gottmann E, Kramer S, Pfahringer B, Helma C. 2001. Data quality in predictive toxicology:
   reproducibility of rodent carcinogenicity experiments. *Environ Health Perspect*
   109(5):509–514. doi:10.1289/ehp.01109509, PMID 11401763（CPDB 121 组重复实验，一致率 57%）
9. Huang R, Xia M, Cho MH, et al. 2011. Chemical genomics profiling of environmental chemical
   modulation of human nuclear receptors. *Environ Health Perspect* 119(8):1142.
   doi:10.1289/ehp.1002952, PMID 21543282（Tox21 10 个 NR；agonist 重现性优于 antagonist；
   A–D 分级与 C/D 级替换策略）
10. Klimenko K. 2020. Examining the evidence of non-monotonic dose-response in Androgen
    Receptor agonism high-throughput screening assay. *Toxicol Appl Pharmacol*.
    doi:10.1016/j.taap.2020.115338, PMID 33217376（35,328 条 AR 激动曲线；NMDR 与干扰偏倚）
11. Kleinstreuer NC, Browne P, Chang X, et al. 2018. Evaluation of androgen assay results using
    a curated Hershberger database. *Reprod Toxicol* 81:272–280.
    doi:10.1016/j.reprotox.2018.08.017, PMID 30205137（11 测定 AR 通路模型：66%，PPV 100%）
12. *Front Pharmacol* 2019, 10:1044. doi:10.3389/fphys.2019.01044（Tox21 AR 的 BLA 与 MDA
    两套测定、四类标签规则与"inconclusive"的产生方式）
13. **ICH M7(R2) 2023**：Assessment and Control of DNA Reactive (Mutagenic) Impurities in
    Pharmaceuticals to Limit Potential Carcinogenic Risk（§6 要求两种互补 (Q)SAR 方法：
    专家规则 + 统计；须符合 OECD 验证原则；两者均阴性方可判 Class 5）。
    国家药监局 2024-01-05 公告适用该指导原则。
    原文（TGA 托管 PDF）：https://www.tga.gov.au/sites/default/files/2024-07/International-Scientific-Guideline-ICH%20M7-R2-Guideline-assessment-control-DNA-reactive-impurities-pharmaceuticals-limit-potential-carcinogenic-risk-adopted.PDF
14. **ICH M7(R2) Q&A（Step 3, 2022）Q6.2**：两种模型中任一为"域外/未覆盖"时，
    **不得**判 Class 5，需 read-across／专家复核／另一已验证模型。
    https://database.ich.org/sites/default/files/M7R2_QAs_Step3_2022_0517-Error%20Corrected.pdf
15. **OECD (Q)SAR 验证原则与 QMRF**（明确终点／算法／适用域／拟合优度与稳健性／预测能力）。
    ICH M7(R2) §6 与 Q&A 6.1 均要求按此提交 QMRF。
16. Lo-Hi: A Practical ML Drug Discovery Benchmark. *NeurIPS 2023 Datasets & Benchmarks*.
    https://papers.nips.cc/paper_files/paper/2023/file/cb82f1f97ad0ca1d92df852a44a3bd73-Paper-Datasets_and_Benchmarks.pdf
    （以"测试分子在训练集中存在 Tanimoto>0.4 邻居的比例"量化基准泄漏：MoleculeNet HIV 56%、
    TDC CYP2D6_Veith 78%。本仓库 §references/UNRESOLVED_CLOSEOUT_v4.3.md §3 采用同一口径）
17. Norinder U, et al. 2020. Predicting With Confidence: Using Conformal Prediction in Drug
    Discovery. *J Pharm Sci* 109(1):1519. doi:10.1016/j.xphs.2020.03.003
    （conformal p-value 天然可作为适用域度量）
18. Hosni Z, Gillet VJ, Marchese Robinson RL. 2025. Explicit Applicability Domain Calculations
    Can Help Determine When Uncertainty Estimates Are Less Reliable. PMC12854501
    （nUNC kNN-AD 与 conformal/Venn-ABERS 联合使用；援引 Hanser 的
    applicability → reliability → decidability 三步）
