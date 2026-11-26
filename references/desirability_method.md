# desirability 的方法学依据与使用纪律

> 本文件解释 `adt/desirability.py` 里每个设计选择的**文献出处**，
> 免得审稿人问"为什么用几何平均""为什么不是加权和"时只能答"经验"。

## 1. 几何平均的出处：Derringer-Suich (1980)

Derringer G, Suich R. *Simultaneous Optimization of Several Response Variables.*
J Qual Technol. 1980;12(4):214–219.

原文的三步法：

1. 把每个响应 y_i 映射到 [0,1] 的个体 desirability d_i（本 skill 的 `shape`
   就是这一步：`up`/`down`/`window` 对应原文的 larger-the-better /
   smaller-the-better / nominal-the-best）。
2. 用**加权几何平均**合成总 desirability：

   ```
   D = ( ∏ d_i^{w_i} ) ^ ( 1 / Σ w_i )
   ```

3. 优化 D。

**关键性质（本 skill 依赖它）**：只要任一 d_i = 0，则 D = 0。
换句话说"**不能有致命短板**"不是一句口号，而是几何平均的数学后果。
若改用加权算术和，一个端点 0.99 可以补偿另一个端点 0.10——
这正是本项目实测到的 MPO Spearman ρ=0.024（排序几乎随机）的成因之一。

## 2. w_i 是**指数**，不是线性系数

这是最容易写错的一处。在 D = (∏ d_i^{w_i})^{1/Σw_i} 中：

- w_i = 2 表示"该响应的重要性相当于两个等权响应"；
- **不是**"该响应的得分乘 2"。

把 w_i 写成线性乘子会破坏"任一为 0 则总和为 0"的性质，也就不再是
Derringer-Suich 的方法。`adt/desirability.py::_geo(vals, weights)` 严格按指数实现，
并在任一 d=0 时直接返回 0（而不是靠 `log(0) → -inf` 的数值巧合）。

未声明 `weight` 时取 1.0 → **与旧版等权实现逐位一致**（向后兼容）。

## 3. 工业先例：CNS MPO（Wager 2010）

Wager TT, Hou X, Verhoest PR, Villalobos A.
*Moving beyond Rules: The Development of a CNS Multiparameter Optimization (CNS MPO)
Approach To Enable Alignment of Druglike Properties.*
ACS Chem Neurosci. 2010;1(6):435–449. DOI: 10.1021/cn100008c

CNS MPO 用 6 个理化参数各给 0–1 分、相加得 0–6 的总分，被工业界广泛采用。
它给本 skill 的两点借鉴：

1. **分档比排序可靠**：MPO 的用法是"≥4 视为 CNS 友好"，而不是"排名第几"。
   这与本 skill 的立场一致——`rank` 默认拒绝 underpowered 排序，只给档位/前沿。
2. **参数分组要有机制理由**：CNS MPO 的 6 个参数分别对应渗透、外排、代谢、安全，
   不是凑数。本 skill 的 `axis`（exposure/safety/efficacy）分组同理：
   同一轴内的端点才允许几何平均，跨轴不合并（避免"用安全性换暴露"这种隐含交易）。

## 4. 本 skill 的三条使用纪律

1. **同轴内才聚合**：跨轴不合成单一分数。`axis_scores.csv` 就是"每轴一个数"。
2. **UNDETERMINED 不进分子、但进分母**：既不当 1（"没证据=好"是最危险的默认），
   也不当 0（把"数据不够"和"分子差"混为一谈）。覆盖率 < 0.5 时该轴分数留空并标
   `insufficient_coverage`（v2.7.0 修 F6：此前会写 `geo_mean=1.0`，等于"满分安全"）。
3. **Pareto 前沿替代排名**：在没有排名资格时，只报"不被任何其他分子在所有轴上
   同时超越"的集合。它是**偏序**，不需要假设分数可比。

## 5. 什么时候**不能**用 desirability

- 端点的阈值本身是 provisional（本项目 23 个质量端点全部如此）→
  desirability 的绝对值不能当"安全概率"，只能做同批分子间的相对比较；
- 轴覆盖率 < 0.5 → 不计算（见纪律 2）；
- 需要"哪个更好"的强结论 → 先过 `tier`（T2 及以上）与 `sensitize`
  （阈值翻转率 < 0.20），否则只能说"排序不稳"。
