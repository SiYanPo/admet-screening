# U9 阈值来源普查表（22-阈值普查，评审 v4.0）

> 对应处方：U9 / P12。状态：✅ 本批完成普查（真实枚举 SKILL.md 中的决策阈值，附来源行号与稳健性标注）。
> 说明：评审原估"22 阈值"，实际在 SKILL.md 中可枚举的**决策阈值**已超过 22 个，下表为去重后的权威清单。
> 稳健性：`anchored`=有实证/文献锚点；`ad hoc`=分析选择，须补 ±20%/±50% 敏感性分析（见判据速查表"阈值稳健性"）。

| # | 阈值 | 含义 / 用途 | SKILL.md 行 | 稳健性 |
|---|---|---|---|---|
| 1 | 0.35 | kNN Tanimoto **饱和**判据（域判别诚实定位） | 31, 468 | anchored；**敏感性已实测（2026-11-23）**：网格 [0.25…0.50] max\|Δacc\| = 0.142/0.194/0.193（hERG/DILI/BBB），产物 `out_sensitivity/knn_threshold_sensitivity.json` |
| 2 | 0.7 | kNN Tanimoto **污染筛查**阈值（≥0.7 视为同化学个体） | 31, 468 | anchored；**敏感性已实测**：网格 [0.60…0.90] max\|Δacc\| = 0.080/0.250/0.367，同产物文件 |
| 3 | 0.5 | Gate 标准化门（去盐/电荷中和/互变，保立体） | 55, 71 | anchored（化学标准化惯例） |
| 4 | 0.90 | 源独立性：组内正相关 ρ≥0.90 → 降为半票 | 202, 398 | anchored（工作包 A；OneADMET 多平台≠多来源） |
| 5 | 0.70 | 源独立性：0.70–0.90 线性降权区间下界 | 398 | anchored |
| 6 | 0.65 | 结论支持档：AUC≥0.65 且 中位比≥1.2 | 344 | ad hoc（分析选择，待敏感性） |
| 7 | 1.2 | 结论支持档：中位比≥1.2 | 344 | ad hoc |
| 8 | 0.35 | 结论反向档：AUC≤0.35 | 344 | ad hoc |
| 9 | 0.90 | 端点无区分度：≥90% 同向 | 366 | anchored（饱和扫描经验） |
| 10 | 0.05 | 端点无区分度：概率极差 <0.05 | 366 | ad hoc |
| 11 | 0.30 | 源不可用：覆盖率 <0.30 | 368 | anchored（vNN 0.17 vs 官方 0.73 实测反例） |
| 12 | 10 | 源不可用：≥10 分子取 ≤2 个不同值 | 368 | ad hoc |
| 13 | 30 | 可排名：候选 ≥30 | 369 | anchored（统计效力下限） |
| 14 | 30% | 可排名：最大同类簇 <30% | 369 | ad hoc |
| 15 | 40 | 适用域邻居判据：Tanimoto ≥40 | 372 | anchored（真 M：T40 有 537 邻居） |
| 16 | 70 | 适用域：≥70 档常=0 会误判"无参考" | 372 | anchored（实测最近邻 0.676） |
| 17 | 5% | 源注册门（F1, Clopper-Pearson 95%CI 上界≤5%） | 380 | anchored（统计门，真实算力曲线见 STATISTICAL_POLICY §1.1） |
| 18 | 0.6 | 肠肝循环边界：fbile≤0.6 | 388 | anchored（C86 不变量 fre=0≡无 EHR） |
| 19 | 0.8 | 肠肝循环边界：fre≤0.8 | 388 | anchored |
| 20 | 0.20 | 阈值稳健性：±摄动翻转率 >0.20 → `fragile` | 394 | ad hoc（判据约定） |
| 21 | 0.50 | 阈值稳健性：>0.50 → `threshold_critical` | 394 | ad hoc |
| 22 | 0.5 | 结构噪声：ratio≥0.5 即"源间分歧含结构伪影" | 402 | anchored（工作包 C；C4/C5） |
| 23 | 0.6 / 0.7 / 0.8 | 去污染三档阈值敏感性 | 614 | anchored（评审推荐档 + 松/严对照） |
| 24 | 5 | 校准计票：某源 n<5 标 insufficient（Jeffreys u=(err+0.5)/(n+1)） | 399 | anchored（**Jeffreys 1946 / Agresti & Coull 1998**；Clark 2014 仅为启发来源，C4 更正） |

## §B 代码常量普查（可机器校验，C6 / 2026-11-03）

上表是**文档层**的决策阈值；本节是**代码层**的模块级阈值常量。两者必须双向可查：
文档上表不能出现代码里不存在的阈值，代码里也不能有未登记的阈值常量。
`tests/test_threshold_census.py` 用 AST 扫描 `adt/*.py` 的模块级常量，
要求每个名字都出现在本文件中——新增常量不登记即测试红。

| # | 常量 | 值 | 位置 | 含义 | 稳健性 / 敏感性 |
|---|---|---|---|---|---|
| B1 | `QUALITATIVE_ONLY` | 10 | `guards.py` | n<10：只允许定性结论，禁止报率/差/排序 | ad hoc（统计效力惯例）；±20%（8/12）翻转率待补 |
| B2 | `SMALL_N_BANNER` | 30 | `guards.py` | n<30：打横幅、禁称"稳健"、默认禁排序 | anchored（与上表 #13 同源：可排名的统计效力下限） |
| B3 | `GATE_AUC_WORKPOINT` | 0.65 | `guards.py` | gate-as-classifier 的**约定工作点**（**已降级：不再是红线判据**，C3） | ad hoc；红线判据改为"必须给 95% CI" |
| B4 | `GATE_AUC_FLOOR` | 0.65 | `gate_audit.py` | 同上工作点的第二处定义（仅供 `gate_audit` 报告分档） | ad hoc；**必须与 B3 相等**（测试断言，防漂移） |
| B5 | `PROB_SPREAD_MAX` | 0.30 | `reliability.py` | 概率类端点源间极差 >0.30 判分歧→UNDETERMINED | ad hoc（由 0.5 下调，因 0.369 极差被误判"一致"）；±20% 必测 |
| B6 | `RATIO_SPREAD_MAX` | 3.0 | `reliability.py` | 连续类端点 max/min >3 判分歧 | ad hoc；±20%（2.4/3.6）必测 |
| B7 | `AXIS_COVERAGE_MIN` | 0.5 | `desirability.py` | 轴级可判覆盖率 <0.5 不参与 Pareto 比较 | ad hoc；±20%（0.4/0.6）必测 |
| B8 | `PROB_MIN_RANGE` | 0.05 | `saturation.py` | 概率极差 <0.05 视为端点饱和（无区分度） | ad hoc（与上表 #10 同一阈值，代码层实现） |
| B9 | `QUALITATIVE_MIN_SOURCES` | 2 | `endpoints.py` | 定性端点（AMES 等）双方法层的最低独立源数 | anchored（ICH M7 两法原则） |
| B10 | `DEFAULT_FLOOR` | 0.30 | `background.py` | 背景率下限（小样本背景估计的收缩地板） | ad hoc；建议 ±50% 敏感性 |
| B11 | `DEFAULT_MIN_BG` | 5 | `background.py` | 背景率估计的最小样本数 | ad hoc |
| B12 | `TOL_FLOOR_ABS` | 1e-4 | `replication.py` | 复现容差的绝对下限（避免 0 容差） | anchored（浮点等价性） |
| B13 | `GATE_AUC_MIN` | =B3 | `guards.py` | B3 的兼容别名，**语义已降级**，禁止再作判据 | 见 B3 |

**本节的制度含义**：`ad hoc` 项必须在结论中标注"待实测确认"（与上表结论一致），
且不得作为"门"去淘汰分子；只有 `anchored` 项允许参与硬判定。

> 注：本普查为**文档/方法学闭环**，不改变代码；与 P12 样例1 边界声明（14 同系物仅演示）共同构成评审 U9/P12 的诚实交付。

## 普查结论（v4.5 更新，2026-11-03）

- **文档层阈值 24 项**：anchored 16 / ad hoc 8（项 6/7/8/10/12/14/20/21）。
- **代码层常量 13 项**（§B）：anchored 2（B2 与 #13 同源、B9、B12）/ ad hoc 9 / 别名 1（B13）。
- **两层合计 37 个阈值**，其中 ad hoc 共 17 个——**这 17 个是结论的软肋**：
  它们不能作为"门"去淘汰分子，只能在报告里标"待实测确认"。
- **已消解的重号风险**：0.65 在仓库里出现三处（文档 #6、`guards.GATE_AUC_WORKPOINT`、
  `gate_audit.GATE_AUC_FLOOR`）。现规定：三处语义必须一致（gate 判别力工作点，
  **非**红线判据），且后两处数值相等由测试断言（`test_threshold_census.py`）。
- **2026-11-23 已闭合**：项 1/2 的 Tanimoto 一维网格敏感性（`adt/knn_sensitivity.py`，真实 637 分子；未用 SALib，理由见模块头：单旋钮 Sobol 退化）；
  回归端点的 TOST 等效界敏感性（`tools/ratio_margin_sensitivity.py`，12 格中 11 格判定翻转）。
- **仍待补**：ad hoc 项的 ±20%/±50%
  翻转率批跑（`adt.cli sensitize` 已具备执行能力，见 SENSI 产物）。

## 附录：命名误撞登记（2026-11-11）

`adt/interference.py` 的模块级常量 **`FLAG_WEAK_ONLY`** 被
`tests/test_threshold_census.py` 的 PAT 正则（匹配带 ONLY 后缀的大写名）扫入代码层常量清单。
**它不是数值阈值**：值为字符串 `"weak_only"`，是结构干扰红旗层的**枚举标签**，
含义为「仅命中弱规则（BRENK/NIH 开发性警报，或 α,β-不饱和羧酸/酯 GRAS 子类）」，
用途是把该类分子标为 `proceed_with_caveat`（单列需实验确认，不折减结论）。

| 项 | 性质 | 来源 | 稳健性 | 敏感性状态 |
|---|---|---|---|---|
| `FLAG_WEAK_ONLY` | 枚举标签（非数值阈值） | RDKit FilterCatalog 来源分档 + `alerts.py` 已知过判 / C87 教训 | 规则型，anchored 于 catalog 条目与结构判据 | **not_applicable**：无数值可摄动；分档边界由 catalog 条目与 SMARTS 决定，变更须重跑 `tests/test_interference.py` 的正负对照 |

此处登记是为了满足「新增常量必须留痕」的纪律，**刻意不重命名绕过扫描器**，
也不把它计入 §B 的数值阈值总数（文档层 24 / 代码层 13 的口径不变）。
