# 模块地图 · 运营流程 · 交叉印证关系（v4.21）

> 这份文件回答三个问题：**这个 skill 现在由什么组成？它怎么跑？模块之间凭什么互相信任？**
> 写法上刻意区分三件事：`做了什么`（能力）、`凭什么可信`（证据）、`什么时候不许说`（边界）。
> 任何一条声称都能在 `adt/` 或 `references/` 里找到对应实现，找不到的就是没做。

---

## 0. 一句话定位

本 skill 不是一个"ADMET 预测工具箱"，而是**一条证据准入 + 证据组合 + 措辞封顶的裁决流水线**：
外部预测源给的是**候选证据**，能不能进票、能不能被写进结论，由本框架的准入门与红线决定。

因此模块分四层，**层间是单向依赖**（上层不得反向改写下层）：

```
L0 结构与状态层   把"输入是不是这个分子、在什么状态下"钉死
L1 证据采集层     多源预测 + 实测回填 + 规则引擎代谢（只产证据，不产结论）
L2 裁决层         准入 → 独立性 → 计票 → 弃权 / 饱和 / 域外
L3 交付层         暴露与裕度、PK/PD、措辞封顶、可复现与审计
```

---

## 1. 模块清单（按层，含"意义"与"失效后果"）

### L0 结构与状态层（错了后面全废）

| 模块 | 意义 | 不做的后果 |
|---|---|---|
| `normalize.py` | 去盐/中和/互变异构，产出 `calc_smiles` 作为**唯一结构键** | 同一个分子在 Sug/盐/构象上被当成三个化合物，批次内自相矛盾 |
| `ionization.py`（v4.14） | 认出可电离基团，给 pH 7.4 下的**电离分数区间 / 净电荷区间 / logD 位移区间** | 把 logP 当 logD 用；把离子态当可透膜；转运体底物类型判反 |
| `guards.py` | 结构真实性 gate（InChIKey 三级 / 糖基切片 / 取代位 / 立体） | 名字对、结构错——所有后续预测都是别的分子的 |
| `acyl_glucuronide.py` | 酰基葡糖苷酸结构警示（羧酸+α-碳取代+共轭） | 漏掉一整类生物活化风险（本化学类的重点） |
| `glycoside_hydrolysis.py` | 糖苷键水解分级 | 把"前药/苷"的稳定性当成原药 |
| `uptake_heuristic.py` / `efflux_heuristic.py` | BBB 摄取/外排的**结构假设**（不进计票） | 把"有药效团"误读成"是底物" |

### L1 证据采集层

| 模块 | 意义 | 边界 |
|---|---|---|
| `adapters/*` + `web.py` | ADMET-AI / ADMETlab3 / ProTox3 / vNN / ChEMBL 等真实源适配 | 源是否可用由 `02_source_registry.yaml` 的 `verified_*` 记录决定，不看首页能不能打开 |
| `readback.py`（v4.20） | **无 API 工具**（SwissADME/AOMP/Graph-pKa/CardioSafe/MicrobeTCM…）的人工导出 → 长表 | 结构必须对齐（不符进 `unmatched`）；未映射列逐列报出；`measured` 必须有显式引文；**禁写** `out_of_domain/saturated/error` |
| `gut_microbiome.py`（v4.19） | BioTransformer `HGUT` 菌群代谢 + `biosystem` 过滤 + 反应标注一致性 QC | `reaction_type/enzymes` 是规则名会串底物类（实测 9/17 矛盾）→ 只可引用 smiles/inchikey |
| `biotransformer` 适配器 | 人源/菌群代谢产物 | 0 产物 = `out_of_domain`，不是"无代谢" |
| `external.py` | 外部公开数据接入（OpenADMET / NPASS）+ RDKit 基线 | 只能在"外源集"上评估，不得当作实测真值来源 |
| `pubchem.py` / `chembl` | 结构锚定与邻居活性 | ChEMBL 邻居给不了 ADMET 实测（本化学类实测 0 条） |

### L2 裁决层（这个 skill 的核心贡献所在）

| 模块 | 意义 | 关键约束 |
|---|---|---|
| `saturation.py` | 饱和扫描：某端点在全化学类上无区分度 → **可判不可排序** | 饱和端点不投票（否则整类假共识） |
| `reliability.py` | 逐端点可靠性：可用源、域外、饱和、分歧 | 只给 PASS/FAIL/UNDETERMINED，不给"综合分" |
| `independence.py` | 独立性分组与权重（Spearman/κ、伪共识、有效票数） | 同一算法族只算 **1 个独立票**（A1：同源两源误差相关 α=0 时已 0.655） |
| `source_rho.py` / `source_admit` | 源准入：Clopper–Pearson CI 上界 ≤5% 才进票 | 不知道源能不能信，就不要投票 |
| `certainty.py` | GRADE 式确定性分档 + 可解决性归因 | "不可解决"不得包装成"证据不足待补" |
| `selective.py` | risk–coverage：结构性弃权 vs 分数型弃权 | 弃权率必须报出（AURC 只在代码自检层面用） |
| `conformal*.py` | 有限样本覆盖率区间 + 难度尺度 | 覆盖率保证只在 exchangeability 成立时有效 |
| `calibration.py` | 概率端点校准（Brier/BSS/斜率/ECE） | 只对概率量纲启用 |
| `dst.py` | Dempster–Shafer 对照（all-in vs 准入） | 用来证明"准入层不是自说自话" |
| `failure_modes.py` / `ablation.py` / `perturbation.py` | 受控失效注入与结构扰动 | 消融必须能"把已知坏输入拦住"，否则测试是假的 |
| `flag_audit.py` | `domain_flag` 写入点白名单（**信任根**） | 谁能写这个字段，谁就能改判决——所以写入点必须逐点登记理由 |

### L3 交付层

| 模块 | 意义 | 边界 |
|---|---|---|
| `pbpk.py` | 12 状态灌注限制 PBPK → C(t)、Cmax、AUC | 只给量级与敏感性，**不是** regulator-grade |
| `pbpk_qualify.py`（v4.17） | AFE/AAFE/2 倍内 + 三条拒绝条件 | 阈值标 `convention`；2 倍内比例高 ≠ 机理正确 |
| `pd_link.py`（v4.16） | Hill/Emax、效应室 ke0、`fT>EC50`、最小 TMDD | TMDD 缺参直接抛错；未做疾病进展/ORd |
| `cardiac_panel.py`（v4.15） | hERG+Cav1.2+Nav1.5 的**覆盖率闸门 + 通道级裕度** | 不做 ORd 净效应；"三通道全 LOW"≠安全 |
| `interop.py`（v4.18/v4.21） | PK-Sim 参数表/OSP 快照、NONMEM 数据集、nlmixr2 骨架 | 导出物必须能被真工具读进去（已实测，见 §4） |
| `phrasing.py` | 措辞封顶：哪些话在有几条证据时才允许说 | 防止"预测"被写成"实测" |
| `reporting.py` / `governance.py` | TRIPOD+AI 自查、model card、QAF/PROBAST | 交付材料的合规骨架 |
| `snapshot.py` / `manifest.py` / `ledger.py` / `prereg.py` | 快照、运行清单、台账、预注册 | 没有它们，"可复现"只是口号 |
| `release_gate.py` / `claims_audit.py` | G1–G12 发布门禁 + 主张登记表字面校验 | 主张必须能在产物里字面命中，否则不许写 |
| `rank.py` / `desirability.py` / `tiers.py` | 排名（默认拒绝 underpowered）、几何平均打分、项目级结论封顶 | 候选 <30 或同簇 >30% → 只给 Pareto front |

---

## 2. 运营流程：主链 + 三条分支

### 2.1 主链（一批 hit 从进来到出结论）

```
① 输入           compounds.csv（结构 + 可选实测）
   ↓
② Gate 0 / 0.5   guards → normalize → ionization
                 不通过 = 整批终止（不是"打个折"）
   ↓
③ 证据采集       adapters（真实源并发） + readback（人工导出回填） + gut_microbiome（菌群）
                 每行必须落 schema.measurement()，带 source / domain_flag / provenance_url
   ↓
④ 饱和扫描       saturation：整类无区分度的端点 → saturated（可判不可排序）
   ↓
⑤ 可靠性裁决     reliability（域外/饱和/分歧） → independence（独立性分组）
                 → source_admit（CI 准入） → certainty（确定性分档）
   ↓
⑥ 暴露与裕度     pbpk → Cmax,u → margin；cardiac_panel（若有三通道数据）
   ↓
⑦ PK/PD 连接     pd_link（fT>EC50 / 效应室）→ pbpk_qualify（能不能用这套模型）
   ↓
⑧ 交付           desirability（几何平均）→ rank（默认拒排）→ phrasing（措辞封顶）
                 → reporting（TRIPOD+AI）→ interop（把参数与数据交给 PK-Sim/NONMEM/nlmixr2）
   ↓
⑨ 审计           manifest / snapshot / ledger / claims_audit / release_gate（G1–G12）
   ↓
⑩ 实测回写       新实测回到长表 → 重算源权重、重算域中心、连续 2 批恶化自动降级
```

### 2.2 分支 A：只有"一批 SMILES"，没有任何实测

这是最常见的情况。此时**允许做的事**与禁止做的事被写死：
- 允许：结构 gate、饱和扫描、证据缺口清单、**UNDETERMINED + 该补哪个实验**；
- 禁止：任何"安全/可口服/进脑"的肯定表述；Margin 不给小数。

### 2.3 分支 B：某个端点三个源分歧

不是"取平均"，也不是"信最新的那个"：
1. 先看是不是**化学类 blocked**（`reliability.apply_class_blocks`）→ 是则整类 `out_of_domain`；
2. 再看是不是**同一独立性组**（`independence`）→ 是则只算 1 票，分歧不构成"2 对 1"；
3. 仍分歧 → 该端点 `UNDETERMINED`，并在 `action` 里写"补哪个湿实验"（`04_decision_funnel.md` §5）。

### 2.4 分支 C：要给外部建模软件（PK-Sim / NONMEM / nlmixr2）

`interop` 是唯一出口，且要求"真工具能读进去"才算完成：
- 参数表 `pk_sim_compounds.csv`（人读）+ OSP 快照 `pk_sim_snapshot.json`（机器读）；
- NONMEM 数据集 `nonmem_dataset.csv` + **`nonmem_id_map.csv`**（ID 必须整数，见 §4.3）；
- nlmixr2 骨架 `nlmixr2_skeleton.R`（`nlmixr2_fit_passed`；初值由 `pk_initials` 推得，仍不是估计结果）。

---

## 3. 模块之间如何相互印证（这是"可信"的真正来源）

**先说清一件事**：本 skill 不把"两个源给出相同答案"当成印证（A1 已实测：同族两源 α=0 时误差相关 0.655，两源均值增益 ≤0）。
**真正的印证是：A 模块的假设，被 B 模块的独立机制检验。** 下表每一行都写着"如果对不上，应该怎么处理"。

### 3.1 结构 → 一切（硬前置）

| 上游 | 下游 | 印证方式 | 对不上时 |
|---|---|---|---|
| `guards` InChIKey | 所有采集模块 | 源返回的结构必须与 `calc_smiles`/InChIKey 一致 | 进 `unmatched` 报表并丢弃，**绝不按名字硬配** |
| `normalize` | `ionization`/`pbpk`/`interop` | 三者都用同一个 `calc_smiles` | 任一处用了不同结构 → 该批次作废重跑 |

### 3.2 理化状态 ↔ 暴露 ↔ 通道（一条"浓度轴"上的三方对账）

| 上游 | 下游 | 印证方式 | 对不上时 |
|---|---|---|---|
| `ionization` pKa | `interop` → PK-Sim `PkaTypes` | 用官方 Midazolam 模型对账：官方 Base 6.2 / Acid 10.95，我们的咪唑类 6.0（Δ0.2 log） | 若 Δ>1 log，说明基团识别错（如把嘌呤 N 当咪唑）→ 该分子不写 pKa |
| `ionization` logD 位移 | `pbpk` 分布 | logP−logD 位移大 → 组织分布与 fu 方向应一致 | 方向相反 → 说明 fu 源与结构状态不自洽，标 `sign_conflict` |
| `pbpk` Cmax,u | `cardiac_panel` margin | `margin = IC50 / Cmax,u`；缺 Cmax 则**不得分档**（v4.21 修：此前误报"无通道数据"） | 缺暴露 → `undetermined_missing_exposure`，action = 去补 Cmax |
| `pbpk.herg_evidence_route` | `cardiac_panel` 表述封顶 | 只有 hERG → `herg_only_*`，措辞硬禁"已排除风险" | 想升级表述 → 必须先补 Cav1.2/Nav1.5 |
| `pbpk` 曲线 | `pd_link` | `fT>EC50` 必须由同一条 C(t) 算出，不能另算一条 | 曲线来源不同 → 指标不可比 |

### 3.3 代谢 ↔ 代谢（两套系统必须分开算）

| 上游 | 下游 | 印证方式 | 对不上时 |
|---|---|---|---|
| `biotransformer`（人源） | `gut_microbiome`（菌群） | 同一分子两套产物集**不允许合并计数**；`biosystem` 必须过滤（实测会混入 `Human`） | 混入 → 人体代谢被算成菌群代谢，整批重跑 |
| `gut_microbiome` 阳性对照 | 该批所有菌群结论 | APAP → 3 个代谢物才算对照 PASS | 对照不过 → 该批菌群结论只作背景，不得跨批比较 |
| `gut_microbiome` 质量差 QC | `reaction_type/enzymes` 字段 | 每条转化的 Δm 必须与反应类型相符 | 不符 → 只能引用 smiles/inchikey（实测 17 条里 9 条不符） |
| `readback`（MicrobeTCM/GutBugDB） | 计票 | 数据库注解 = 文献级证据，`predictive_value=none` | 被当成预测投票 → 制造"菌群代谢有 2 票支持"的假象 |

### 3.4 模型 ↔ 模型（"能不能用"必须先答）

| 上游 | 下游 | 印证方式 | 对不上时 |
|---|---|---|---|
| `pbpk` C(t) | `pbpk_qualify` | 与观测配对：AFE/AAFE/%2fold + 三条拒绝条件 | n<5 或每化合物 <2 时点 → 拒绝评估，不给结论 |
| `pbpk` 参数 | `interop` → PK-Sim | 快照能被 `PKSim.CLI snap -p` 转成 `.pksim5`，且往返后数值逐位一致（已实测 32/32） | 转换"成功"但化合物数变少 → 视为失败（PK-Sim 会静默丢内容） |
| `interop` 数据集 | `pharmpy` / nlmixr2 | 真工具读入并给出 subjects/obs/doses 计数 | 读不进去 → 数据集契约不合格（ID 必须整数，v4.21 修） |
| `pd_link` 指标 | `phrasing` | `fT>EC50` 是"机理假设下的推演"，不得写成疗效 | 想写疗效 → 必须先有体内药效数据 |

### 3.5 结论 ↔ 产物（不许"说了但没算"）

| 上游 | 下游 | 印证方式 |
|---|---|---|
| 任何写进材料的数字 | `claims_audit` + `CLAIMS_REGISTRY.yaml` | 主张必须能在产物里**字面命中**，否则 G10 红 |
| 任何"新能力" | `tests/` + `release_gate` | 没有测试与门禁的功能等于不存在（v4.13 起：`test_every_test_file_is_registered` 专门抓"写了但没跑"） |
| 任何"源可用" | `02_source_registry.yaml` 的 `verified_*` | 首页 200 不算可用（pkCSM 前端全活、预测引擎 8/8 500） |

---

## 4. 本轮（v4.21）实测得到的六条硬结论

### 4.1 外部软件"装上了"与"能读进去"是两件事，而"能读进去"又分好几级

| 工具 | 安装方式（官方来源） | 实测闭环程度 |
|---|---|---|
| **PK-Sim 12.3.173** | OSP 官方 GitHub Releases 的 **Portable ZIP**（免安装、免 UAC） | `pk_sim_cli_snap_passed`：`snap -p` 把我们的快照转成 `.pksim5`，**往返后 32/32 化合物、数值逐位一致**。**仅化合物层** |
| **MoBi 12.3.136** | 同上（Portable ZIP） | 仅 GUI（无 CLI），随包带 `Diclofenac/4-Hydroxy-Diclofenac.pkml` 与模板 |
| **Pharmpy 2.3.0** | 官方 PyPI | `pharmpy_dataset_ok`：`create_datainfo` + `read_dataset_from_datainfo` 真读 11228 行 / 12 列 / 28 受试者 |
| **R 4.5.3 + nlmixr2 5.0.0 + rxode2 5.0.2** | conda-forge（`micromamba`，用户态，免 UAC） | `nlmixr2_fit_passed`：模型**编译成功**、FOCEI **收敛**（bobyqa 正常退出） |

所以 `validated_against_tool` 从布尔值改成**三级**。一个 `False` 会把
"PK-Sim 化合物层已经往返一致"和"nlmixr2 连编译都没过"抹平成同一件事——那是**信息损失**，不是诚实。

### 4.2 PK-Sim 会**静默丢内容**，所以"转换成功"不能当验收

用官方 Midazolam 快照（37 个仿真）做 snap 往返时，`snap -p` 返回码 0、日志写 "Project saved"，
但项目里 **Simulations 变成 0 个**（Individuals/Compounds 还在）。随后 `export --run` 报
`Simulation was not found in project`。已排除 `ParameterIdentifications` 空引用与 `ObservedData`
两个诱因（清空后仍丢）。
→ 验收标准必须是**产物计数**（`compounds=32`、`simulations=1`），不是退出码。

### 4.3 NONMEM 数据集：字符串 ID 会让真工具直接拒绝

`pharmpy` 读 `ID=A-1` 抛 `ValueError: invalid literal for int()`。
原 `validate_nonmem` 只看 EVID/MDV/排序，抓不到这一条——**契约校验漏了最基础的一条**。
修法：`nonmem_id_map()` 生成稳定整数映射并落 `nonmem_id_map.csv`；`validate_nonmem` 增加"ID 必须为整数"硬校验。

### 4.4 给药与观测同腔，会让 NONMEM 把血浆浓度当胃肠道浓度

原实现只用一个 `default_cmt`，给药行与观测行都是 `CMT=1`。nlmixr2 单端点模型不按 CMT
匹配输出，所以"看起来能跑"；但 NONMEM `ADVAN2` 里 **CMT=1 是胃肠道**，观测会被读成胃内容物，
吸收相直接消失、表观分布容积荒谬地小，而 RSE 依然"好看"。
修法：拆出 `obs_cmt`（口服默认给药 1 / 观测 2），新增 `cmt_layout()` / `cmt_split_ok()`，
`validate_nonmem(expect_cmt_split=True)` 硬拦，并补两组成对断言。

### 4.5 把"数值零"当观测，会得到**收敛但错误**的拟合

pbpk 曲线在 12–30 h 已衰减到 0，之后约 370/400 个时点的 DV 是 **ODE 的数值零，不是测量值**。
把它们当真实观测喂进去：目标函数被零主导、加性残差被压到接近 0，结果是
**FOCEI 报 bobyqa 正常退出，但 tcl 停在初值 6.0 不动、tv 估成 2978 L（t½=344 h，
而曲线实际 t½≈1.6 h，差 200 倍）**。
→ 这是本轮最重要的一条：**"收敛"不等于"算对"**。
修法：`mask_nonpositive_obs()` 把非正观测置 `MDV=1` 并**报出条数**（本例 8037 条），
`validate_nonmem` 新增"非正观测参与拟合"检查。真做 BLQ 要走 `CENS=1` 删失似然，
本模块不假装能做。

### 4.6 就算数据干净，也只有 V 是可辨识的

屏蔽数值零（剩 3163 条有效观测）后重跑，结果：

| 参数 | 估计 | RSE | 判定 |
|---|---|---|---|
| **V** | **1433 L** | **3.8%** | 可估（95%CI 1330–1540） |
| CL | 605 L/h | 3.6e3% | 不可辨识（CI 跨四个数量级） |
| ka | 1.07 /h | 2.0e6% | 不可辨识（flip-flop） |
| F | 1.00 | 2.0e6% | 不可辨识（与 V 的经典混淆） |

原因有两个，都必须写进报告：① 口服单次给药下 F 与 V 不同时辨识；
② 曲线几乎无噪声时 ka 与 CL 走 flip-flop。**骨架默认只应报 V，其余固定或标注不可估。**
另一个必须说清的前提：数据集里 **ID = 化合物，不是人体受试者**，
所以 eta 是"化合物间变异"，**不得**当 IIV/BSV 报（实测 eta_cl 收缩 −427% 就是这个原因）。

---

## 5. 读这份文件的人最容易犯的三个错

1. **把模块数量当能力**：`adt/` 有 70+ 模块，但决定结论质量的只有三处——源准入、独立性、
   措辞封顶。加一个预测源通常不提升决策质量（A1/S4 已证），补一个结构性缺口才提升。
2. **把"交叉印证"理解成"多源投票"**：同族多源是伪共识。印证是**不同机制**互检（结构↔状态、
   暴露↔通道、模型↔观测、结论↔产物）。
3. **把"能跑通"当"结论成立"**：跑通只证明管道没断；结论成立还要求准入、独立性、域内、
   措辞四关都过，并且能通过 `release_gate` 的 G1–G12。

---

## 6. 2026-11-22 补丁：治理扩展层（实验性）

`adt/governance_ext/`（31 模块）是同行评审后的实验层，**不进入主决策链**：
split_audit（四分分割）、ood_monotonicity（偏移单调性）、zk_audit（盲化审计）、
regulatory_seal（联合封印/审计链）、stratified_monitor（CUSUM+算子库）、
trust_inheritance（lineage）、uncertainty_quantification（UQ）、dependency_guard（版本绑定）、
chained_exemption（带镣铐豁免）等。

接入纪律：先用真实 endpoint 数据标定 → SHADOW 只记录 → 误报率达标 → ENFORCE；
不得把实验层输出直接写进 T2/T3 结论或论文主表。
