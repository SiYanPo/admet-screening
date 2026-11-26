# 定位与对标证据链（2026-11-18 联网核实）

> 来源：两轮联网文献核查（PubMed/DOI/出版社/官方政策页逐条解析），非记忆。
> 用途：为"证据准入先于证据组合"方法学命题的**定位、创新性声明与投稿策略**提供可引用链。
> 纪律：每条给权威链接；找不到的一律标注"未检索到"，禁止编造。本文件是**证据清单**，
> 不是已发表论文；引用前请作者二次核对出版社页面（链接可能失效）。

## 1. 创新性定位判断（决定论文能否成立）

**判定：(b) 有部分覆盖，但缺乏"独立可审计准入层 + 归因 + 代价同尺度"的组合。**

- **不是 (a) 常识**：没有任何一篇把"准入必须先于组合"作为通用原则论证。
- **不是 (c) 完全新颖**：每个构件都有成熟 prior art（下表 1a–1f、2a–2c、4a、5a）。
  声称"完全新颖"会被审稿人用这些文献直接驳回。
- **真正创新点**：组合与层级顺序——在 Dawid–Skene 之上增设**证据源级、可审计、带归因的准入门**，
  把 Chow/Vickers 式同尺度代价下推到"接纳 vs 弃用一条证据"的决策，且明确该门**先于**投票组合。

**给编辑/审稿人的定位句**：
> 既有工作分别解决了"何时弃权"（Chow/Geifman/Hendrickx）、"AD 是否可信"（Sahigara/Mora/Norinder）
> 与"无金标准如何加权"（Dawid–Skene），但没有人把证据源级、可归因、代价同尺度的准入判定
> 置于证据组合之前；本文填补的正是这一层级缺口。

## 2. 方法学对标文献（已核实）

| # | 作者年份 | 出处 | DOI/链接 | 核心主张 | 与本 skill 关系 |
|---|---|---|---|---|---|
| 1a | Chow 1957 | IRE Trans. EC 4:247–254 | 见 ACM 参考 [1](https://dl.acm.org/doi/abs/10.5555/3295222.3295241) | 首个最优拒判规则 | 支撑"弃权是合法第三选项" |
| 1b | Chow 1970 | IEEE Trans. IT 16(1):41–46 | [10.1109/TIT.1970.1054406](https://doi.org/10.1109/TIT.1970.1054406) | 误差-拒判最优权衡 t=(Cᵣ−C𝚌)/(Cₑ−C𝚌) | **强支撑**代价同尺度（对象是单分类器） |
| 1c | Geifman & El-Yaniv 2017 | NeurIPS 30 | [PDF](https://proceedings.neurips.cc/paper_files/paper/2017/file/4a8423d5e91fda00bb7e46540e2b0cf1-Paper.pdf) | 风险-覆盖曲线；SGR | 支撑"先按风险设门"；挑战：单模型 post-hoc |
| 1d | Geifman & El-Yaniv 2019 | ICML 2019 PMLR 97:2151 | [arXiv:1901.09192](https://doi.org/10.48550/arXiv.1901.09192) | SelectiveNet 端到端联合优化 | 挑战"准入需独立可审计" |
| 1e | **Cortes–DeSalvo–Mohri 2016**（非 DeCoste/2010） | NeurIPS 29:1660 | [NYU PDF](https://cs.nyu.edu/~mohri/pub/rboost.pdf) | 同时学预测函数 h 与拒判函数 r | 支撑"拒判可独立于预测"；挑战：模型内部函数对，非源级审计 |
| 1f | Hendrickx et al. 2024 | Mach Learn 113(5):3073 | [10.1007/s10994-024-06534-x](https://doi.org/10.1007/s10994-024-06534-x) | rejector 综述；§7 多拒判器组合 | **最接近**"准入先于组合"；但组合的是 rejector 非多源证据，无归因/无金标准投票/无 DCA |
| 2a | Norinder et al. 2014 | JCIM 54(6):1596 | [10.1021/ci5001168](https://doi.org/10.1021/ci5001168) | CP 作为 AD 替代；0.8→≤20%误差 | 支撑可解释可调准入；挑战：单模型预测集有效性 |
| 2b | Alvarsson et al. 2021 | J Pharm Sci 110(1):42 | [10.1016/j.xphs.2020.09.055](https://doi.org/10.1016/j.xphs.2020.09.055) | AD 内禀绑定底层 ML 模型 | **直接挑战**"独立准入层"——必须论证为何 CP/AD 不够 |
| 2c | Xu et al. 2024 | ACS Omega 9(27):29478 | [10.1021/acsomega.4c02017](https://doi.org/10.1021/acsomega.4c02017) | QSAR 场景 CP 有效性/效率基准 | 提供基线；仍是单模型 |
| 3a | Sahigara et al. 2012 | Molecules 17(5):4791 | [10.3390/molecules17054791](https://doi.org/10.3390/molecules17054791) | AD 是可靠预测前提（OECD 原则 3） | 共识支撑；AD 是模型属性非证据准入层 |
| 3b | Mora et al. 2024 | JCAMD 38(1):9 | [10.1007/s10822-024-00550-8](https://doi.org/10.1007/s10822-024-00550-8) | 误差分析揭示 AD"可靠"误标；呼吁更严格指南 | 强支撑独立可审计准入；仍单模型 |
| 3c | Gadaleta et al. 2024 | J Cheminform 16(1):145 | [10.1186/s13321-024-00931-z](https://doi.org/10.1186/s13321-024-00931-z) | 12 工具×17 性质×41 数据集基准 | ADMET 按 AD 内/外分层；是基准非准入层 |
| 4a | Dawid & Skene 1979 | JRSS C 28(1):20 | [10.2307/2346806](https://doi.org/10.2307/2346806) | 无金标准多观察者错误率 EM 估计 | **直接支撑**无金标准多源投票；挑战：默认合并全部观察者，无弃权门/归因 |
| 5a | Vickers & Elkin 2006 | Med Decis Making 26(6):565 | [10.1177/0272989X06295361](https://doi.org/10.1177/0272989X06295361) | Net Benefit 汇率 pₜ/(1−pₜ) | **强支撑**代价同尺度；评价的是输出策略非两级结构 |

**prior-art 风险排序（论文须逐条显式区分）**：
1. **Hendrickx 2024 §7**——若"准入层"被读成另一个 rejector，新颖性即 collapse；必须强调准入对象是**多源证据/投票**而非单模型输入，且输出**归因**。
2. **Mora 2024**——若被读成"又一个 AD 验证流程"，需强调处理的是**跨源可靠性**与**组合前时序**。
3. **Alvarsson 2021**——它明确说 AD 与模型内禀绑定；"独立层"必须论证为何不能只靠 CP/AD（CP 只给边际覆盖保证，不给源级归因与无金标准错误率估计）。

## 3. 负结果 / 失效边界的发表出口（已核实）

| 项 | 结论 | 链接 | 含义 |
|---|---|---|---|
| PLOS ONE 负结果政策 | ✅ 存在；"Studies reporting negative results"在范围 | [criteria](https://journals.plos.org/plosone/s/criteria-for-publication)、[Missing Pieces](https://blogs.plos.org/everyone/2015/02/25/positively-negative-new-plos-one-collection-focusing-negative-null-inconclusive-results/) | (b) 栏目落点；仍要求结果"照亮已有文献" |
| Scientific Reports 政策 | ✅ 15 周年专集 "The Value of Null Findings"；编辑标准=科学严谨非新颖性 | [collection](https://www.nature.com/collections/aaecfeegff) | 同上 |
| "Scientific Reports 8172 政策" | ❌ **未检索到**，勿引用 | — | 从稿件删除 |
| Elsevier《Journal of Negative Results》 | ❌ **无此现存续刊**（相关刊已停） | [CASRAI 指南](https://casrai.org/guides/where-to-publish-negative-and-null-results) | 不以"投专门刊"为主策略 |
| Springer JONNPR | ⚠ 存在但非 Springer（西班牙 PROEDITIO），ISSN 2529-850X | [jonnpr.com](https://jonnpr.com/) | 小众出口，索引/声望弱 |
| PeerJ | ✅ CASRAI 确认 soundness 模型欢迎负结果 | 同上 CASRAI | (b) 候选 |
| Nature Methods 标准 | novelty+validation+benchmarking+general applicability | [s41592-022-01558-4.pdf](https://www.nature.com/articles/s41592-022-01558-4.pdf)、[nmeth.2471](https://www.nature.com/articles/nmeth.2471) | 纯负结果不宜硬投旗舰方法刊 |
| APS Registered Replication Report | ✅ 先审方案、无论结果发表、OSF 存档 | [APS](https://www.psychologicalscience.org/index.php/replication)、DOI 10.1177/1745691614543974 | 解决 estimand 未绑定的制度模板 |
| Results-blind review | ✅ COS 期刊清单；Locascio 2017 两阶段法 | [COS](https://www.cos.io/initiatives/registered-reports)、[Elsevier](https://elsevier.com/connect/results-masked-review-peer-review-without-publication-bias)、PMID 29780193 | 判据在结果前锁定 → 负结果被制度保护 |
| 计算/化学信息学 RR 刊 | ⚠ 无专门刊；Nat Hum Behav 2026 论证 ML 适合 RR；Elsevier 30+ 刊接受 | [s41562-026-02586-2](https://www.nature.com/articles/s41562-026-02586-2) | 可走 RR，但要选对刊 |
| TRIPOD+AI 2024 | ✅ Collins BMJ 2024;385:e078378；27 条目/52 项，**是报告规范不规定设计** | [10.1136/bmj-2023-078378](https://doi.org/10.1136/bmj-2023-078378)、[EQUATOR](https://www.equator-network.org/reporting-guidelines/tripod-statement/) | 透明报告背书，非"预指定"硬依据 |
| PROBAST+AI | ⚠ **2025**（非 2024），确切 DOI/PMID 未核实 | [BMJ](https://bmj.com/bmj_countries/switch/uk?destination=node/1095803) | 引用写 2025 |
| OSF 不可篡改时间戳 | ✅（措辞需限定："immutable"指快照固定+变更留痕，非密码学绝对） | [COS](http://centerforopenscience.org/our-products/osf-registries/)、[OSF help](https://help.osf.io/article/626-simplifying-the-preregistration-process) | pre-specification 可引用锚点 |
| Lange et al. 2025 Stat Med | ✅ 方法学研究探索/确证连续谱，带时间戳注册为确证核心 | [10.1002/sim.70303](https://doi.org/10.1002/sim.70303) PMID 41213159 | 方法学论文本身以预注册为可信度核心的实例 |

**明确找不到（禁止引用）**：Scientific Reports"8172 政策"；Elsevier《Journal of Negative Results》现存续刊；
"方法学论文必须陈述可证伪命题"的明文编辑指南；PROBAST+AI 确切 DOI/PMID。

## 4. 投稿策略建议（对用户）

**推荐 (d) 组合策略，两条路线**：

- **路线 1（维持现状 4.0-dev，estimand 未绑定）→ (b)+(c)**：
  硬投 Nature Methods 类胜率低（其要求正面贡献+benchmarking）。落点：PLOS ONE / Scientific Reports
  null-findings 专集 / PeerJ / BMC Research Notes，定位为"失效边界清单 + 可复用基准/诊断数据"。
  必须写清"比较了哪些方法、什么判据、S4≤S1 的效应量与不确定性"，否则 soundness 刊也拒。

- **路线 2（补做，收益最高）→ (a)+(d)，用 Registered Report 把负结果升级为确证结论**：
  致命伤不是"结果负"而是"estimand 未绑定"。一旦结果前锁定假设/判据 + OSF 时间戳锚定，
  负结果即被制度保护（Locascio 2017；Lange 2025）。把"S4 不优于 S1"改写为 Stage 1 可证伪命题
  （如"条件 X 下 Δ∈[−δ,δ]"），投接受 RR 的期刊，再发 Stage 2。正面贡献落在"失效边界检测框架"。

**学术品味分歧（文献无法判定，需用户/旗舰模型定夺）**：
1. 负结果是否重新包装为"正面贡献"（失效边界检测框架）——framing，无客观答案。
2. 是否值得为 RR 再投入——文献只证降偏倚，不保证引用/声誉回报。
3. 旗舰刊 vs 专门负结果刊的声望—命中率权衡。
4. "estimand 未绑定"定位为致命缺陷还是诚实声明的探索性限制——Lange 2025 允许探索性但需标注。
5. JONNPR 等小众刊的索引/声望风险。

---

## 【2026-11-19 重要更新·必读】本文件定位判断已被新证据压缩

本文件 11-18 的"(b) 部分覆盖、层级缺口真实"判断**仍然成立**，但 11-19 的完整 prior-art 扫描发现
三篇**本文件当时未纳入**的强趋同工作，**不得再对外用"首创/无人做过"措辞**：

1. **TRUST-ADMET**（Zenodo 10.5281/zenodo.20997792，2026-06-28，一手已验）——开源软件，
   功能含 Classical ML+GNN+ChemBERTa+Calibration+AD+Conformal+Explainability+External Validation。
2. **SciForge**（arXiv:2607.16038，2026-07，一手已验）——Evidence-DAG 审计 sidecar + review gates +
   claim-to-provenance 链 + 分子优化案例，直接冲击"元科学基础设施"叙事。
3. **AdmitOR**（arXiv:2608.15565，v6 2026-11，一手已验）——label-free 独立准入门 +
   accept/abstain/escalate + FDR 界，覆盖 5 构件中的 4 个。

**修订后的创新性表述**（ replaces 本文件 §1 的定位句）：
> 据我们所知，首次将**源级准入判定、弃权-错误同尺度代价、chemotype→源白名单**整合进一个面向
> 多源 ADMET 的可审计决策层；各单独构件及部分集成已有在先工作（TRUST-ADMET / SciForge / AdmitOR /
> Chow 1970 / Dawid-Skene 1979 / Hendrickx 2024 等，逐条引用）。贡献在层级顺序与统一代价下的组合，
> 非任一构件的发明。

完整扫描、逐构件对比、战略情报与" FDA 排除药物发现阶段"说法的更正见
`references/PRIOR_ART_2026_SCAN.md`（= `admet-screening_文献对标与战略情报分析_20261119.md`）。
