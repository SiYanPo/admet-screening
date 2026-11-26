# 未解决项收口 v4.3（2026-11-01）

> 对象：v4.2 红黑榜黑榜里"仍未解决"的 4 类项（B4 前瞻盲测、第三方独立复现、
> 第三方模型训练集不公开、近邻泄漏归因"结构上无法拆解"）。
> 处理原则（三条，逐条可核对）：
>
> 1. **换了测法 ≠ 问题解决。** 每项必须标明现在是「关闭」「降级」还是「仍开」，
>    降级的必须写清"降成什么假设 + 降级后允许/禁止的措辞"。
> 2. **必须给产物路径 + 数字。** 只有代码没有产物的一律记 🟡（沿用 v4.2 台账规则）。
> 3. **不许把外部文献当挡箭牌。** 文献只能为"用替代设计"提供合法性，
>    不能替代实测；每条文献后面必须跟本仓库自己的数字。

---

## 0. 总览

| # | 原未解决项 | 处置 | 结果 | 产物 |
|---|---|---|---|---|
| 1 | B4 前瞻预注册盲测（需 OSF 账号 + 等待） | 换设计：post-cutoff 时间留出 + TRIPOD+AI/Sheridan 的设计合法性 | **降级**（结论方向为**否定**） | `out_ext/external/herg_holdout.json` |
| 2 | 第三方独立复现（需"未见本仓库的人"） | 换成"多分析者 + 第二实现 + 挑战包" | **仍未关闭**（结构性阻塞） | `replication/`、`out_blacklist/` |
| 3 | ADMET-AI / ADMETlab3 / ProTox3 训练集清单不公开 | 换判据：不追清单，改按 PROBAST 风险偏倚条目评"数据重叠= unclear/high" + 用 Lo-Hi 口径量自己能量的那一半 | **降级**（"源间独立"从断言 → 假设） | `out_ext/tdc/leakage_attribution.json` |
| 4 | 近邻泄漏"结构上无法拆解" | 换代理：内部可测的"近重复组 vs 新颖组"误差相关差 | **关闭（部分）**：2/3 端点可读，方向不一致 | `out_ext/tdc/leakage_attribution.json` |

**一句话**：4 项里 **1 项部分关闭、2 项降级、1 项仍开**。
**没有一项是靠"再写一段免责声明"处理的**——每一项都新增了一次实测。

---

## 1. B4 前瞻预注册盲测 → post-cutoff 时间留出

### 1.1 为什么"换设计"是可辩护的，而不是偷懒

B4 想要的是"模型没见过这些分子"。这个目标在方法学上有**公认的替代设计**，不是我们发明的：

- **Sheridan 2013**（*J Chem Inf Model* 53(4):783–790, doi:10.1021/ci400084k）直接比较了三种切分对
  "真实前瞻预测"的逼近程度：随机切分**过于乐观**、leave-class-out **过于悲观**，
  **时间切分（time-split）最接近真实前瞻**。这是"用时间留出替代前瞻"的原始依据。
- **TRIPOD+AI**（Collins GS et al. *BMJ* 2024;385:e078378, doi:10.1136/bmj-2023-078378）把
  外部验证明确分为"**later period (temporal)**"与"another hospital or country (geographic)"两类，
  并明确"**there is no such thing as a validated prediction model**"——即任何单次验证都只是
  一个时点/一个域上的证据。
  中文清单见 EQUATOR：https://www.equator-network.org/reporting-guidelines/tripod-statement/

所以本轮做的是**temporal external validation**（TRIPOD+AI 认可的设计），
而不是"假装完成了预注册"。差别我们照实写在 §1.4。

### 1.2 设计与数据

| 项 | 取值 |
|---|---|
| 数据源 | ChEMBL API，target `CHEMBL240`（hERG），`standard_type=IC50`，`document__year__gte=2023` |
| 库版本 | ChEMBL_37（release 2026-05-01） |
| 取回活性记录 | **19130 条**（20 页全取，非抽样） |
| 剔除删失值（`>`/`<`） | 5087 |
| 剔除 ChEMBL 自标无效（`data_validity_comment`） | 304 |
| 剔除无 SMILES | 38 |
| 有 pChEMBL 值的分子 | 9628 |
| 剔除与 TDC hERG 完全相同 | 122 |
| 剔除与 TDC 任一分子 Tanimoto ≥ 0.9 | 63 |
| **最终外源留出 n** | **9443** |
| 外源分子到 TDC 的最大 Tanimoto 中位数 | **0.241** |
| 标签口径 | pIC50 ≥ 5（IC50 ≤ 10 μM）= blocker，与 TDC hERG 一致；同分子多值取中位数 |
| 模型 | 两个，同管道同超参（RF 400 树，Morgan-2048，seed=0）：**① 域内参照** = train_val(523) 训练 / TDC test 评估；**② 外源** = train_val+test(655) 全量训练 / post-cutoff 评估 |

`median max Tanimoto = 0.241` 是一个硬事实，值得单独说：**0.241 < 本框架 AD 锚点 0.35**。
也就是说，按本框架自己的门，这 9443 个分子几乎全部会被判"域外、拒答"。
本次实验测的是"**如果强行预测，会发生什么**"。

### 1.3 结果

**（a）判别力与阈值的分解**

| 指标 | TDC 内部 test (n=132) | post-cutoff 外源 (n=9443) | 差 |
|---|---|---|---|
| 阳性率 | 0.735 | 0.679 | −0.056 |
| **AUC** | **0.792** | **0.581** [0.569, 0.593] | **−0.211** |
| 阈值 0.5 下 sensitivity | 0.979 | 0.969 | −0.010 |
| 阈值 0.5 下 specificity | 0.400 | **0.051** | −0.349 |
| 阈值 0.5 下 accuracy | 0.826 | 0.674 | −0.152 |
| always-positive 基线 accuracy | 0.735 | **0.679** | — |

**（b）先验漂移检验（排除"只是阈值搬错了"这一解释）**

| 项 | 值 |
|---|---|
| 训练集阳性率 | 0.689 |
| 外源集阳性率 | 0.679 |
| → 先验漂移 | **仅 −0.010，可忽略** |
| 先验匹配阈值（p 的 0.321 分位） | 0.661 |
| 该阈值下 sens / spec / acc | 0.707 / 0.382 / **0.603** |

**（c）三条结论**

1. **判别力掉了 0.211 个 AUC。** 内部 0.792 → 外源 0.581。这是"换到全新骨架"的代价，
   不是种子噪声（外源 CI [0.569, 0.593] 与 0.792 完全不重叠）。
   **也不是训练量不足**：外源模型用了 train_val+test **全部 655 个** TDC 分子训练，
   比域内参照模型（523 个）看到的数据**更多**。
2. **0.5 阈值不能搬，但换阈值也救不回来。** 外源集上 specificity 0.051 意味着模型几乎全判阳性；
   换成先验匹配阈值后 specificity 升到 0.382，但 accuracy 反而从 0.674 掉到 **0.603**。
   → **不是阈值问题，是排序能力本身不够。**
   而且这里的先验几乎没变（训练 0.689 vs 外源 0.679，差 **0.010**），
   所以"几乎全判阳性"**不能**归因于先验漂移——这一点是排除法得出的，不是猜的。
3. **accuracy 0.674 < always-positive 0.679。** 这一条最刺眼：在外源集上，
   "全部判 blocker"这个零成本基线**比模型还准**。

方向：**否定**。这份实测**不能**用来支持"模型可外推"；它只能说明
"本框架的 hERG 模型在全新骨架上不具备可用的排序能力"。

### 1.4 与 B4 的真实差距（不许混同）

| 维度 | OSF 前瞻预注册 | 本次 post-cutoff 时间留出 |
|---|---|---|
| 时点关系 | 注册在前，数据在后 | 数据已存在，只是**晚于训练集文献年份** |
| 抗选择性报告 | 强（分析计划锁定后才见数据） | **弱**（阈值/口径在见到数据后确定） |
| 抗数据泄漏 | 强 | 中（已剔完全相同 + Tanimoto≥0.9 近重复） |
| 抗"事后改指标" | 强 | 弱 |
| 结论强度 | 可写"前瞻验证" | **只能写"temporal external validation 表现"** |

**允许措辞**：
- ✅ "在 ChEMBL_37 的 post-cutoff（文献年份 ≥2023）hERG 留出集（n=9443，到训练集中位最大 Tanimoto 0.241）上，
  AUC 0.581 [0.569, 0.593]，显著低于 TDC 内部 0.792。"
- ✅ "该设计属 TRIPOD+AI 定义的时间型外部验证，**不是**前瞻预注册。"

**禁止措辞**：
- ❌ "前瞻验证通过 / 通过外部盲测"（无预注册）
- ❌ "模型可外推到新骨架"（实测方向相反）
- ❌ "外源上 accuracy 0.674 说明可用"（低于 always-positive 0.679）

### 1.5 这一条顺带证实了什么

它把 v4.2 的两个悬空说法接上了：
- AD 门在 hERG 上 **`passthru_unfounded`**（`GATE_AND_P8_MMP_v4.2.md` §1.5）——
  当时只能证明"域内外准确率无差异"，没法说明域外到底行不行；
- 现在有了：**域外确实不行（AUC 0.581）**，而门的 AUC 判别力也是 0.58。
  两者是不同的量（一个是"门能不能预测模型对错"，一个是"模型能不能排序"），
  数值接近是巧合，**不得**互相引用为证据。但**结论方向一致**：hERG 上"域外可以放心预测"没有依据。

---

## 2. 第三方独立复现 → 多分析者 + 第二实现 + 挑战包

### 2.1 为什么这一项不能靠文献"解决"

文献能给的是**替代设计的合法性**，不是替代品本身：

- **Silberzahn et al. 2018**（"Many Analysts, One Data Set", *Adv Methods Pract Psychol Sci* 1(3):337–356）
  让 29 个团队分析同一份数据，结论从"有"到"无"都有 → 说明"一个人复现自己"几乎无信息量。
- **Steegen et al. 2016**（"Increasing Transparency Through a Multiverse Analysis",
  *Perspect Psychol Sci* 11(5):702–712）→ 把分析选择空间显式化，比"再跑一遍同一个脚本"更有价值。

这两条的意思很直接：**独立复现的核心是"独立"，不是"再跑一次"**。
本机做不到"未见本仓库的人"，所以这一项**只能是仍未关闭**。

### 2.2 已经做到的替代（不是空话）

| 替代措施 | 现状 | 位置 |
|---|---|---|
| 第二实现（同题不同代码路径） | 已做：hERG / DILI / BBB 三端点的第二份实现与差异比对 | `out_blacklist/tables.md`、`second_impl*.log` |
| 复现挑战包（只给指标 + 容差，不给中间产物） | 已做 | `run_replication_pack.py`、`replication/` |
| 容差由种子方差反推（防游戏化） | 已做（R30） | `adt/replication.py`、`tests/test_v43_measures.py` |
| 环境指纹 + 锁版 | 已做（R02/R06） | `env_fingerprint.json`、`requirements.lock` |

### 2.3 结论

**状态：仍未关闭（结构性阻塞）**。

阻塞点不是技术，是**人**：真正的第三方复现要求执行者事先未见过本仓库的设计与阈值。
这一点在本机会话内无法伪造，**任何"我自己复现成功了"的说法都不构成该项证据**。

因此该项的处理是"**把它变成一道不可绕过的发布门**"，而不是"解决它"：
`v4.0` 标签授予条件（SKILL.md R32）里"外部独立复现"是硬门槛——
在它满足之前，版本号只能是 `4.0-dev`。**这条现在仍然成立。**

**允许措辞**：✅ "已提供复现挑战包 + 第二实现比对，**外部独立复现未完成**。"
**禁止措辞**：❌ "已通过独立复现"／❌ "复现性已验证"（把"我跑通了"说成"独立复现"）。

---

## 3. 第三方模型训练集清单不公开 → 改判据，而不是继续要清单

### 3.1 原要求本身有问题

原诉求是"拿到 ADMET-AI / ADMETlab3 / ProTox3 的训练集清单，才能算源间重叠"。
这个要求有两处错：

1. **商业/半商业模型不会公开训练清单**，这是常态而非例外。把它当成"待办"会永久挂着，
   变成一句免责话——正是本台账最想避免的模式。
2. 即使拿到清单，"重叠"也不是一个能靠清单算干净的量（近重复、同源文献、同批测定）。

**正确的做法换成"风险偏倚评估"框架**：
- **PROBAST**（Wolff RF et al. *Ann Intern Med* 2019;170(1):51–58）把"分析域 / 数据来源与重叠"
  列为**风险偏倚条目**，允许评为 low / high / **unclear**，而**不要求**取得原始数据。
  即在信息不足时，规范动作是**判 unclear 并降级结论**，不是无限期等待数据。
- **TRIPOD+AI**（同上）要求报告数据来源、可用性与重叠情况，同样允许"受限/不可得"作为如实陈述。

### 3.2 可执行的替代测量：只量自己能量的那一半

**Lo-Hi**（*NeurIPS 2023 Datasets & Benchmarks*）用"测试分子在训练集里存在 Tanimoto>0.4 邻居的比例"
量化基准泄漏，这个口径**只需要我们自己手里的数据**，不需要对方清单。

我们的实测（`out_ext/tdc/leakage_attribution.json`，20 种子，阈值 0.4/0.7）：

| 端点 | n_test | 近邻泄漏率（≥0.4 有邻居） | Δ(r_error) = 近重复组 − 新颖组 |
|---|---|---|---|
| hERG | 132 | **0.621** | **+0.002** |
| BBB_Martins | 406 | 0.443 | **−0.212** |
| DILI | 96 | — | 不可算（近重复组样本不足） |

读法见 §4.3。这里只用它说明一件事：**我们能给的是"本框架自身三源之间的重叠上界"，
给不出"与外部三家之间的重叠"**。

### 3.3 因此"源间独立"必须降级

| 原表述 | 现在 |
|---|---|
| "四源相互独立，可作独立证据投票" | **假设**，不是断言；且已由 PROBAST 口径评为 **unclear** |
| 权重方案里按独立处理 | 必须同时给 **`shrink`（最保守收缩）** 结果作并列主结论；`equal` 只能作参考 |

**允许措辞**：
- ✅ "四源间独立性**无法验证**（对方训练集不公开），按 PROBAST 判为 unclear；
  故权重结论并列报告 `equal` 与 `shrink` 两套。"
**禁止措辞**：
- ❌ "四个独立模型投票"（"独立"未验证）
- ❌ "已排除训练集重叠"（没排除，只排除了我们能看到的重复）

---

## 4. 近邻泄漏"结构上无法拆解" → 内部代理可测

### 4.1 原说法错在哪

v4.1 写的是"源间误差相关有多少来自共享训练数据，结构上无法拆解"。
这句话把**一个可测的经验问题**说成了**原理性不可能**——而实际上只要换一个变量就能测：
不问"记忆占多少比例"，问"**如果共享误差是记忆驱动的，那么越靠近训练集的分子，源间误差相关应该越高**"。
这是一个可在本框架内部完成的比较，不需要对方训练集。

### 4.2 代理设计

1. 对每个测试分子算"到 fit 集的最大 Tanimoto"；
2. 按阈值（0.4 / 0.7）切成"近重复组"与"新颖组"；
3. 两组分别算 20 个种子下**源间误差相关系数 ρ_error**；
4. 报 Δ = ρ(近重复组) − ρ(新颖组)。

判读：若 Δ 明显 > 0 → 共享误差部分由记忆驱动，ρ 的归因偏向"数据重叠"；
若 Δ ≈ 0 → 共享误差与近邻泄漏无关，更可能来自同源训练范式与方法相似。

### 4.3 结果

| 端点 | 近重复组 ρ | 新颖组 ρ | **Δ** | 判读 |
|---|---|---|---|---|
| hERG | — | — | **+0.002** | 与 0 不可区分 → **不支持"记忆驱动"** |
| BBB_Martins | — | — | **−0.212** | 新颖组反而更相关 → **方向相反** |
| DILI | 近重复组样本不足 | — | 不可算 | 不判 |

（精确 ρ 值与分组样本数见 `out_ext/tdc/leakage_attribution.json` 的 `by_group` 与 `per_seed`。）

**结论**：这一项**部分关闭**，且结论是**不支持原始担忧**——
在 2 个可读端点上，共享误差**没有**随着分子靠近训练集而上升（一个 ≈0，一个反号）。
但：

- **只有 2/3 端点可读**，且方向不一致（一个 ≈0、一个负），因此**不能**给出统一归因；
- 这个代理只覆盖"本框架三源之间"，**不覆盖**"与外部三家的重叠"（见 §3）。

**允许措辞**：
- ✅ "用近重复/新颖分组代理检验，hERG Δ=+0.002、BBB Δ=−0.212；
  共享误差未随近邻泄漏上升，故 ρ 的归因不偏向'记忆'。"
**禁止措辞**：
- ❌ "已证明共享误差与数据重叠无关"（只测了 2 个端点、只覆盖内部三源）
- ❌ 引用 DILI 的任何 Δ（近重复组样本不足）

---

## 5. 本轮由实测逼出来的两条判定修正

### 5.1 回归端点的 R 判据必须与符号一致率合读（→ 新增 `compressed` 方向）

原 `analyze_regression()` 只判 R = median|Δpred| / median|Δlabel|：
`R 的 CI 上界 < 0.5 → insensitive`。

问题：**任何"回归到均值"的模型都必然 R<1**。幅度被压缩是数学必然，
不等于"对结构不敏感"。实测把这个坑踩出来了：

| 端点 | 对数 | 模型 | R [95%CI] | 符号一致率 | 旧判 | **新判** |
|---|---|---|---|---|---|---|
| Caco2 | 220 | rf_morgan | 0.417 [0.318, 0.553] | 0.575 | inconclusive | `inconclusive` |
| Caco2 | 220 | rf_maccs | 0.234 [0.166, 0.329] | 0.540 | insensitive | `insensitive` |
| Caco2 | 220 | ridge_desc | 0.170 [0.138, 0.221] | 0.530 | insensitive | `insensitive` |
| Caco2 | 220 | ensemble | 0.286 [0.204, 0.331] | 0.541 | insensitive | `insensitive`（方向确实无信息） |
| 脂溶性 | 4636 | rf_morgan | 0.400 [0.386, 0.420] | **0.668** | insensitive | **`compressed`** |
| 脂溶性 | 4636 | rf_maccs | 0.405 [0.384, 0.425] | **0.673** | insensitive | **`compressed`** |
| 脂溶性 | 4636 | ridge_desc | 0.373 [0.359, 0.390] | **0.734** | insensitive | **`compressed`** |
| 脂溶性 | 4636 | ensemble | 0.323 [0.313, 0.340] | **0.730** | insensitive | **`compressed`** |
| 溶解度 | 5684 | rf_morgan | 0.534 [0.506, 0.577] | 0.642 | equivalent | `equivalent` |
| 溶解度 | 5684 | rf_maccs | 0.623 [0.590, 0.667] | 0.706 | equivalent | `equivalent` |
| 溶解度 | 5684 | ridge_desc | 0.516 [0.493, 0.547] | 0.775 | inconclusive | `inconclusive`（CI 跨 0.5 界） |
| 溶解度 | 5684 | ensemble | 0.486 [0.465, 0.518] | 0.759 | inconclusive | `inconclusive` |

修订（`adt/mmp.py`）：新增符号一致率与二项符号检验，`sign_z ≥ 3.0`（单侧 p<0.0014，**约定值**）
且 R 判 insensitive 时，改判 **`compressed`**，并给出专属解释与禁止措辞。

理由很直接：**把"压缩"写成"迟钝"，和 P8 旧版把"迟钝"写成"稳定"是同一类错误的镜像**，
只是一个美化、一个丑化。两个方向都必须堵。

**同时它也说明了回归支不是"一律否定"**：
- 溶解度 4 个模型里 2 个 `equivalent`、2 个 `inconclusive`，**没有一个**是 `insensitive`/`compressed`；
- 脂溶性 4 个模型**全部** `compressed`（方向对、幅度约 1/3）；
- Caco2 3/4 `insensitive`（方向接近随机，这才是真迟钝）、1 个 `inconclusive`。

**逐端点、逐模型报，不许合并成一句"回归端点也迟钝"。**

### 5.2 去掉 `tdc` 包的硬依赖（新增 `adt/tdc_local.py`）

**故障**：`run_p8_mmp_regression.py` 与 `run_external_holdout.py` 三个端点全部
`ModuleNotFoundError: No module named 'tdc'`——而 TDC 数据其实早已缓存在
`out_ext/tdc_cache/admet_group/<name>/{train_val,test}.csv`。

**处置**：新增 `adt/tdc_local.load_split(cache, name)`：优先用官方 `tdc` 包（保证口径一致），
不可用时直接读本地 CSV。7 个 `run_*.py` 全部改走该入口。

**验证**：本地读取的切分规模与文档记载逐一吻合（hERG 523/132、DILI 379/96、BBB 1624/406、
Caco2 728/182、脂溶性 3360/840、溶解度 7985/1997、Ames 5821/1457）。

这条属于"复现性基础设施"，不是科学结论——但它决定别人能不能跑起来，
所以照台账规则必须留痕。

---

## 6. 现在的总账

| 项 | v4.2 状态 | v4.3 状态 | 依据 |
|---|---|---|---|
| B4 前瞻预注册盲测（R11） | ⛔ 外部阻塞 | 🟡 **降级为 temporal external validation，已实测，结论否定** | §1 |
| 第三方独立复现 | ⛔ 外部阻塞 | ⛔ **仍未关闭**（结构性：需要未见本仓库的人） | §2 |
| 外部三家训练集清单 | 🟡 待取得 | 🟡 **改为 PROBAST "unclear" + 权重并列 `shrink`** | §3 |
| 近邻泄漏"结构上无法拆解" | ⛔ 声称不可能 | ✅ **部分关闭**（2/3 端点可读，方向不支持原担忧） | §4 |
| 回归端点未实跑（R14 尾巴） | 🟡 只有接口 | ✅ **关闭**（3 端点 × 4 模型实跑，新增 `compressed` 判定） | §5.1 |
| AD 只测单一判据 | 🟡 只覆盖默认门 | ✅ **关闭**（4 判据 × 3 端点 × 5 种子，全部 <0.65） | `ad_multicriteria.json` |
| 负面结论是否"基线过强" | 🟡 未做对照 | ✅ **关闭**（新增 S5 未校准基线，S4−S5 三端点全部显著更差） | `out_keystone_v43/results.json` |
| Ames 档位偏保守 | 🟡 只写"保守" | ✅ **关闭**（ICH M7(R2) → `qualitative_only` + 专家规则层，放行错误率 0.269→0.177；**v4.4 完成 reliab 生产接线**，此前仅基准层、生产流仍全 UND） | `ames_alerts.json` |

**仍非 ✅ 的只剩 3 项**：B4（🟡 降级，结论否定）、外部三家训练集清单（🟡 降级为 PROBAST unclear）、
第三方独立复现（⛔ 结构性阻塞）。三者**都是"需要第三方 / 第三方数据"型，不是"我们还没做"型**。
其余 5 项均已关闭并附产物。

**版本号仍是 `4.0-dev`**，因为标签授予条件里"外部独立复现"这一条仍未满足——这一条不因本轮工作而改变。

---

## 7. 复现

```bash
# 需要：TDC ADMET_Group 缓存已在 out_ext/tdc_cache/（离线可跑）
python -m pytest tests/test_gate_mmp_v42.py tests/test_v43_measures.py -q

# ① post-cutoff 外源时间留出（首次联网取 ChEMBL，之后走缓存；约 5 min）
python run_external_holdout.py
#   -> out_ext/external/herg_holdout.json

# ② 近邻泄漏归因（约 1 min）
python run_leakage_attribution.py
#   -> out_ext/tdc/leakage_attribution.json

# ③ 多判据 AD（4 判据 × 3 端点 × 5 种子，约 3 min）
python run_ad_multicriteria.py
#   -> out_ext/tdc/ad_multicriteria.json

# ④ 回归端点 MMP（3 端点 × 4 模型，约 5–15 min）
python run_p8_mmp_regression.py --endpoint caco2_wang
python run_p8_mmp_regression.py --endpoint lipophilicity_astrazeneca
python run_p8_mmp_regression.py --endpoint solubility_aqsoldb
#   -> out_ext/tdc/p8_mmp_reg_*.json

# ⑤ 基石 + S5 未校准基线（20 种子 × 3 端点，约 20 min）
python run_keystone.py --seeds 20
#   -> out_keystone_v43/results.json
```

---

## 8. 参考（本节新增，按出现顺序）

1. Sheridan RP. 2013. Time-Split Cross-Validation as a Method for Estimating the Goodness of
   Prospective Prediction. *J Chem Inf Model* 53(4):783–790. doi:10.1021/ci400084k
   （时间切分比随机切分更接近真实前瞻；随机切分过于乐观）
2. Collins GS, Moons KGM, Dhiman P, et al. 2024. TRIPOD+AI statement: updated guidance for
   reporting clinical prediction models that use regression or machine learning methods.
   *BMJ* 385:e078378. doi:10.1136/bmj-2023-078378（外部验证含"later period (temporal)"类型；
   明确"不存在'已验证的'预测模型"）
3. Wolff RF, Moons KGM, Riley RD, et al. 2019. PROBAST: A Tool to Assess the Risk of Bias and
   Applicability of Prediction Model Studies. *Ann Intern Med* 170(1):51–58.
   （数据重叠/分析域列为风险偏倚条目，允许评 unclear）
4. Silberzahn R, Uhlmann EL, Martin DP, et al. 2018. Many Analysts, One Data Set: Making
   Transparent How Variations in Analytic Choices Affect Results.
   *Adv Methods Pract Psychol Sci* 1(3):337–356.
5. Steegen S, Tuerlinckx F, Gelman A, Vanpaemel W. 2016. Increasing Transparency Through a
   Multiverse Analysis. *Perspect Psychol Sci* 11(5):702–712.
6. Lo-Hi: A Practical ML Drug Discovery Benchmark. *NeurIPS 2023 Datasets & Benchmarks*.
   https://papers.nips.cc/paper_files/paper/2023/file/cb82f1f97ad0ca1d92df852a44a3bd73-Paper-Datasets_and_Benchmarks.pdf
7. ICH M7(R2) 2023，§6 与 Q&A 6.2（Ames 双方法要求）——见
   `references/ENDPOINT_TIER_EVIDENCE.md` 参考 13–14。
