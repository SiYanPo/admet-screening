# ADMET 评估 skill —— 使用说明与现状

> release **0.9.0** / capability **4.0-dev** / evidence level **内部证据分层（非监管结论）**
>
> **本 skill 的定位是 auditable decision layer（可审计的决策层），不是 SOTA ADMET 预测器。**
> 它回答"这批 hit 的哪些结论有证据支撑、哪些必须弃权、证据强度如何"，
> 不承诺在独立外部测试集上击败任何预测模型；把它包装成预测 SOTA 属误用。
> T0–T3 是**内部证据分层（internal evidence tier），不是任何监管机构的 determination**；
> 不得映射为 FDA/EMA 或任何法域的审批等级。

## 已实现机制 vs 已外部验证结论（禁止混写）

| 类别 | 内容 | 证据状态 |
|---|---|---|
| **已实现机制（工程治理，可审计）** | 结构真实性 gate、InChIKey 锚定、长表数据契约、化学类→源白名单、单位校验、独立方法组计票、源级准入/弃权、manifest/snapshot/release-check G1–G14、措辞封顶、零引用 API 门禁、默认测试接入 14 个原生测试 | 代码 + 回归断言在库，本机能复现 |
| **已外部验证结论（有限，带边界）** | OpenADMET 25 265/10 738 行、ChEMBL hERG 外部留出 9 443/959 上的 ablate/prospect/conformal-class/cross-class 结果；见 SKILL.md v4.35 段 | 真实数据实跑一次，**未做** 5 端点×3 分割×3 模型预注册、外部多队列、prospective |
| **尚未验证（不得写成结论）** | 5 端点×3 分割×3 模型性能、cluster 偏移下 conformal 覆盖、时间外推、PBPK/ORCA/R 外部腿、真实湿实验/前瞻队列 | 仅为计划或实验层（governance_ext，SHADOW 未接主 CLI） |

对外材料引用本 skill 时，上表三行必须整体引用；禁止只取"已实现机制"行去支撑"预测性能"主张。

这是"虚拟筛选命中物 ADMET 分层评估"的可执行骨架。
方法学底稿见项目里的两份文档：
`admet-pipeline/ADMET评估补全方案_v1.md`（自建）与
`ADMET评估补全方案_v2_对照Kimi.md`（与 Kimi 方案对照后的合并版，**以 v2 为准**）。

## 现在能跑的三件事（都已实测）

### 1) 状态标准化（Gate 0.5）

```bash
# 可移植写法：不要写死任何一台机器的解释器路径（换机复现见 SETUP_REPRODUCE.md）
PY="${PYTHON:-python}"
$PY -m adt.cli normalize --in <你的输入SMILES文件> --outdir out
```

产出 `out/compounds.csv`，其中 `calc_smiles` 才是后面所有源要用的 SMILES。
内置立体保护：真 M 走一遍仍是 `MPZFXDIZHZVXBJ-SGKFEUNSSA-N`
（不加保护会变成 `...-DMLMUOLJSA-N`，双键 E/Z 丢失）。

### 2) 全端点饱和扫描（QA gate #11）

```bash
$PY -m adt.cli saturate --wide <你的ADMETlab宽表.csv> --outdir out
```

实测输出：108 个数值端点 → **usable 42 / 集合内无区分度 66 / 数值无效 0**。
注意三种判定是分开的：`saturated_in_set` 只是不能排序，**绝对阈值仍然有效**；
`invalid` 才是连阈值都不能用（本项目 ADMETlab 里一个都没有；
DeepPurpose 的 `caco2_mpnn = −13.4` 会被判 invalid，可作反向自检）。

### 3) 代谢产物（BioTransformer REST）

```bash
$PY -m adt.cli bt --in out/compounds.csv --outdir out --option CYP450
```

实测输出（真 M）：

```
[biotransformer] 阳性对照 CYP450: {'acetaminophen': 6, 'phenol': 2}
[biotransformer] [1/1] M ok
[bt] 0 个代谢产物（注意：0 ≠ 无代谢）
```

长表里两行都是 `domain_flag=out_of_domain`、`value` 留空、
note 写明"规则引擎活着但本分子 0 产物 → 判为规则未覆盖"。
**这条是本类化学的硬结论**：该源对肉桂酰糖苷没有规则覆盖，
对香豆酸甚至会产出"生成咖啡酸"这种化学上荒谬的结果。

### 4) ChEMBL：适用域 + 真值参照

```bash
$PY -m adt.cli chembl --in out/compounds.csv --outdir out --threshold 40
```

实测（真 M）：

```
chembl_neighbors_t40      537   邻居总数 537；仅取前 40 个做活性统计
chembl_max_tanimoto     0.676   最近邻 CHEMBL479699（PUBESCENOSIDE A），本地 Morgan r2
chembl_neighbors_t70        0   Tanimoto>=70 的邻居数
```

三个必须知道的接口事实：
- **阈值只接受 40–100**，传 30 直接 400；
- 老的 `molecule.json?...similarity=` 写法会 500，**正确端点是 `/similarity/{smiles}/{t}.json`**；
- 返回里**没有 Tanimoto 分数**，最大相似度要本地用指纹算。

这条给的是两类信息：① **适用域**（邻居多不多、最近邻像不像）；
② **真值分位**（邻居的实测 logD/溶解度/CLint/hERG 分布 p10/p50/p90）。
用 70% 档判断会误判成"完全无参考"——真 M 在 70% 是 0，但 40% 有 537 个同类糖苷。

### 5) 多源裁决（s5）

```bash
$PY examples/build_demo_long.py     # 用项目里 4 个源的真实结果拼长表（154 行）
$PY -m adt.cli reliab --in out/measurements_demo.csv --outdir out \
    --rules references/03_endpoint_rules.yaml \
    --saturation out/admetlab_results_saturation.csv
```

实测输出 **42 个 分子×端点 全部 UNDETERMINED**——这不是 bug：

```
A  Ames   源间分歧过大（极差=0.830）
A  DILI   源间分歧过大（极差=0.746）
A  hERG   源间分歧过大（极差=0.369）   ← 0.014 / 0.409 / 0，30 倍差异不能算一致
```

每个 UNDETERMINED 都带 `action`（补哪个源或哪个实验）。这正是本项目"没有哪个源最准"
的结论被写成了机制，而不是一句心得。

逻辑分支用 `tests/test_reliability.py` 验证（25 个断言，**数据是合成的**，只测分支）：

```bash
$PY tests/test_reliability.py      # 25 passed
```

### 6) desirability + Pareto（s6）

```bash
$PY -m adt.cli desire --in out/reliability.csv --outdir out \
    --rules references/03_endpoint_rules.yaml
```

单端点 desirability（0–1，按 shape 定义）→ 同轴内**几何平均** → Pareto 前沿。
三条铁律都来自本项目教训：

1. **UNDETERMINED 既不当 1 也不当 0**——不进几何平均，但占分母；
   轴覆盖率 < 0.5 时该轴标 `insufficient_coverage`，不参与 Pareto。
2. **FAIL = 0**，会真实拉低几何平均（阈值判定比连续打分更硬）。
3. **默认不输出排名**，只输出 Pareto 前沿；要排名必须 `--enforce-rank-guard`
   且过四条件（候选≥30 / 最大簇<30% / 跨源分歧<阈值 / 可判端点≥3）。

真实数据实测（14 分子 × 6 端点 = 84 行 → reliab → desire）：

```
Pareto 前沿: ['H', 'I', 'J', 'K', 'L']        ← 三个 NR/SR 端点全部 PASS 的分子
A   safety  geo=0.0   (SR-ARE 0.901 > 0.7 FAIL)
H   safety  geo=1.0   (0.354/0.231/0.475 全 PASS)
M   safety  geo=0.0   (NR-AR-LBD 0.724 > 0.7 FAIL)
```

注意 DILI/Ames/hERG 在这个化学类上 42/42 UNDETERMINED（四源分歧），
所以 safety 轴只有 3/6 端点可判（cov=0.50）——这正是"UNDETERMINED 占分母"设计的意义：
分数没有假装那些端点不存在。

### 7) 反应性（XenoSite，人工通道）

```bash
$PY -m adt.cli xeno-prep --in out/compounds.csv --outdir out --models quinone reactivity
# 在网页上跑完、把数值按 examples/xenosite_readback_template.csv 的列填好
$PY -m adt.cli xeno-ingest --file readback.csv --outdir out
```

原因：XenoSite 站点 Terms 明确写 "access to the programatic API" 是**许可项**，
免费只到网页界面。所以这里**不模拟网页提交**（那等于绕过许可），只做
任务单生成 + 回填解析。`value` 留空的行会自动记为 `out_of_domain`。

## 目录

```
SKILL.md                  给 agent 看的主文档（何时用、流程、判据速查、契约）
references/
  00_scope.md             9 层框架 + 明确不做的边界
  01_structure_and_state.md  InChIKey 三级判定、糖苷四查、3D 手性、状态标准化
  02_source_registry.yaml **源清单**：URL / 实测状态 / 接口坑 / 限流 / 化学类白名单
  03_endpoint_rules.yaml   端点阈值 + desirability 形状（阈值目前是文献来源，待实测重标）
  04_decision_funnel.md    门控、何时才允许排名、UNDETERMINED→实验映射
  05_qa_gates.md           11 条 QA gate，每条带踩坑出处
adt/                      schema / normalize / saturation / adapters
assets/controls/controls.csv  对照集（6 条，全部实测值）
tests/test_reliability.py s5 的 25 条断言（合成数据，只测逻辑分支）
examples/
  build_demo_long.py      用项目 4 个源的真实结果拼多源长表
  xenosite_readback_template.csv   XenoSite 人工回填契约
out/  out2/               运行产物（可删）
```

## 还没做的（下一步）

| 项 | 说明 |
|---|---|
| ~~ChEMBL 适配器~~ | ✅ 本轮完成（比原计划多做了一件：把它同时当适用域指标） |
| ~~`s5_reliability`~~ | ✅ 本轮完成（含 25 条单元测试） |
| admetSAR3 / Pred-hERG / TOXRIC | ⚠️ 已探明但**不能脚本化**：admetSAR3 需要私有 access_key（不在 POST 响应里）、Pred-hERG 是 Next.js 前端 fetch、TOXRIC 首页只有 740 字节且真实入口未定位。三者已在 registry 里标 `needs_probe` 并写清阻塞点 |
| ~~desirability + Pareto~~ | ✅ 本轮完成（`adt/desirability.py` + 36 条单元测试；规则加了 `axis` 分组） |
| Margin（未结合暴露） | 依赖 fu 与 PBPK，等实测 |
| ADMETlab 适配器 | 现在复用的是项目里 `w1_admetlab_retry.py`，没搬进 skill |

## 这个 skill 现在**确实能派上用场**的一件事（v4.4 补充）

前面几轮的所有数字几乎都在削弱这个框架——诚实是诚实，但不解决问题。**唯一一处"改了行为且数字变好"的地方是 Ames 致突变性**：

| ICH M7(R2) 口径，n=1457 | 只跑统计模型 | 统计模型 + 专家规则层 |
|---|---|---|
| 放行中**真致突变物**个数 | 156 | **40** |
| 放行错误率 | 0.2685 | **0.177** |
| 放行率（代价） | 0.399 | 0.155 |

机制很简单，也正是这个 skill 的命题在**单个端点内部**的缩影：**结构警报不是"又一个特征"，而是有否决权的独立证据体**——
任一层报警即升级，两方法一致才放行。产物 `out_ext/tdc/ames_alerts.json`（2026-11-01）。

> **v4.4 起已接线到生产**：`reliab --enable-alerts`（默认开）+ `--compounds` 会真实调用该
> 专家层做双方法合成，ames 在 `reliability.csv` 中出真实判决；此前它仅存在于基准脚本，
> `reliab` 并不使用（这正是已修正的"文档声称≠行为"脱节）。

> 边界必须同句说清：这个增益**只在 Ames 成立**（因为存在高特异性、高可解释性的警报体系）；
> hERG/DILI/BBB 三端点上同一思路**没有**带来增益（gate AUC 0.580/0.669/0.514 全低于 0.65）。
> 且代价是放行率从 0.399 掉到 0.155（244 个真阴性被误挡）——**报收益不报代价，就是本文档一直在批评的那种选择性呈现**。

## 一个提醒

`references/03_endpoint_rules.yaml` 里的所有 pass/fail 阈值**没有一条来自实测**，
全部是文献惯例。第一批湿实验回来后必须重标，并把 `threshold_source` 从
`literature` 改成 `measured`。否则这个 skill 只是把别人的假设固化下来。

## 2026-10-27 晚：借入外部对接 skill 的九条协议（P0/P1/P2 全部落地）

| 借入项 | 实现位置 | 怎么用 |
|---|---|---|
| B2 价键/奇电子/radical 硬门 | `adt/normalize.hard_gates`（normalize 自动执行） | `hard_gate_problems` 列非空 = 禁止分发；[CH3] 双警报实测拦截 |
| C2 状态敏感性 | `adt/normalize.state_sensitivity` | 醋酸根 dTPSA 2.83/dClogP 1.33 → `state_sensitive` 列非空；阈值 dTPSA>3 或 dClogP>0.2（实测校准） |
| A1 措辞封顶 | `adt/phrasing` + reliab 输出 `allowed_statement` 列 | 每条结论只许模板内表述；禁止 ΔG→Kd、人体剂量、"证明/无毒"（见 05_qa_gates §12） |
| C1 源独立性计票 | registry 每源 `independence_group` + reliability `n_indep_groups` | 同组只记 1 独立票；require_sources=N = N 个独立组；单组一致 → confidence=low |
| A3 预注册 | `adt/manifest.py`（reliab/saturate/desire/chembl/bt 自动调用） | 每次 run 写 `run_manifest.yaml`（判据文件 SHA1）+ 历史链 jsonl |
| A2 证据台账 | `adt ledger` 子命令 | 每条结论反查支撑记录；`unsupported` 必须先修证据或改结论 |
| B1 跨批锚点 | bt 适配器 `control()` 自动比对 controls.csv 区间 | 出界打 `BATCH_DRIFT`；w1/w2/w3 按同协议混入对照 |
| B3 MD 收敛门 | `examples/md_convergence_gate.py` | 接触图 Tanimoto 驻留 + 块平均；<20 帧或不收敛 → 结论封顶"静态敏感性"（Mv2 9 帧实测正确拒绝） |
| D1/D2 元数据 | registry `targets:` 块（8ZVZ=激活态）+ 01 §1.7 分子式核验 | 靶点形态限制写进 usage_limit |

测试：tests/test_gates_protocol.py 新增 19 断言；三套共 **80 断言全过**。

## v2.0.1（2026-10-27 23:50）：全功能实例排查

对 v2.0 全部命令做了真实数据实例排查，**3 个新 bug/欠账当场发现并修复**：

| # | 排查项 | 结果 |
|---|---|---|
| 1 | normalize 全 14 分子 | ✅ 硬门/状态敏感 0 触发（中性糖苷预期），真 M InChIKey 保持 |
| 2 | saturate + manifest | ✅ 历史链 jsonl 落盘 |
| 3 | bt 跨批锚点（真实 API 14 分子，10 min） | ✅ 对照 6/2 在区间内、14/14 out_of_domain 与历史一致 |
| 4 | chembl 全量 14 分子（7 min，42 行） | ✅ **A/B 的 Tanimoto=1.0（ChEMBL 有本体）；J 适用域全班最差，与垫底互证** |
| 5 | xeno-prep | ✅ 14 任务单 |
| 6 | desire --enforce-rank-guard | ✅ + 修复 C39（max_cluster_frac 可配置） |
| 7 | report 措辞层（合成 measured/跨 3 组实例） | ✅ + **修复 C38 跨目录污染** |
| 8 | MD 收敛门 ≥20 帧（旧 M 23 帧） | ✅ **converged**（末四分 0.852/块误差 0.018）+ 修复 C40 |
| 9 | run.py 跨目录 smoke | ✅ 10 命令 |

案例库同步 +4 条（C38–C41）。测试 80 断言全过。

## v3.1.0（2026-10-29）：外部评审驱动的"可检验方法学"升级

一句话：把"证据准入"从工程约束提升为可检验、可比较、可证伪的方法学命题。
新增 7 个模块与 7 个子命令，逐条对应外部评审的工作包 A/C/D/E/H/I/J：

| 命令 | 回答什么问题 | 关键产物 |
|---|---|---|
| `independence` | 同组源真的独立吗？"两票半"的错误率是多少？ | pairs/groups/effective_votes/vote_calibration |
| `certainty` | 这个 UNDETERMINED 是"补源能解决"还是"只能做实验"？ | certainty.csv（5 档） |
| `selective` | 弃权信号可靠吗？结构性弃权 vs 分数型弃权谁退化慢？ | risk_coverage / AURC |
| `failure-modes` | 哪些行是结构性失效（单位异构/域外未接线/版本漂移）？ | failure_modes + precision/recall |
| `perturb` | 结构标准化到底改变了什么？ | 描述符位移 + 位移/分歧比 |
| `decision-value` | 固定预算下，"准入"比"强行投票"划算吗？ | 三策略期望效用 + 决策曲线 |
| `dst` | 为什么不直接用 DST？ | all-in vs 准入 + 过度裁决计数 |

实例分析（14 匿名分子 × 4 源）与 6 个实跑 bug 的修复记录见
`学术升级实例分析_v3.1.0.md`；与 conformal/AD/DST/多数投票的分工表见
`references/09_reliability_landscape.md`。

> 诚实边界：严格口径下本批 84/84 UNDETERMINED；无 truth 时 `selective` 的
> AURC 只作代码自检（n<10 标 insufficient），`decision-value` 只写期望效用，
> 不写"准确率提高"。

## v3.2.0（2026-10-29）：外部公开数据随包分发（工作包 B/G）

不再只给接入协议。`assets/external/` 已随包放两份公开数据：

| 数据 | 许可证 | 规模 | 用途 |
|---|---|---|---|
| OpenADMET-ExpansionRx | **CC-BY-4.0** | train 5,326 / test 2,282 × 9 终点 | 前瞻性 ADMET 基准 |
| NPASS 3.0 curated | 学术免费（cite NAR 2026） | 1,307 rat-LD50 + 76 ADME | 天然产物毒性基准 |

新增两个命令：

```bash
# 外部数据 -> 三张契约表 + rules
$PY -m adt.cli external --dataset openadmet --data-dir assets/external/openadmet \
    --split test --outdir out_ext

# Ridge 基线（RDKit 描述符 / Morgan 指纹）-> test 预测 + 风险分数
$PY -m adt.cli baseline --train-meas out_ext/measurements_train.csv \
    --test-meas out_ext/measurements_test.csv \
    --train-compounds out_ext/compounds_train.csv \
    --test-compounds out_ext/compounds_test.csv \
    --method both --rules out_ext/external_rules.yaml --outdir out_ext

# 真实 AUROC/AUPRC（必须用 *_risk.csv）
$PY -m adt.cli benchmark --predictions out_ext/measurements_baseline_rdkit_risk.csv \
    --truth out_ext/truth_test.csv --rules out_ext/external_rules.yaml --outdir out_ext/bench_rdkit
```

实测：OpenADMET 上 RDKit 基线平均 AUROC **0.656**、Morgan **0.730**；
NPASS LD50 上 RDKit **0.660 [0.595–0.720]**。

> 边界：`baseline_*` 是 Ridge **基线**，不是 ADMET-AI/ADMETlab；PASS/FAIL 阈值
> 是分析选择；"NPASS 三工具 201,905 化合物"基准不在官方下载包，未随包分发。

## 推广策略 5 条（R40 / 评审 §7.2）

> 评审要求：推广不是"发出去等下载"，而是**分层**——不同受众拿到的应该是不同的东西，
> 且推广动作本身要产生可回收的证据。以下 5 条互为前提，缺一条就会出现
> "有人用但没人会正确用"或"有人用但问题不回流"。

**1. 分层推广（同一内核，三种入口）**

| 受众 | 给什么 | 不给什么 | 理由 |
|---|---|---|---|
| 湿实验室/药化 | `normalize → saturate → reliab` 三条命令 + `--profile academic-internal` | 不要求装 RDKit 之外的东西 | 他们要的是"这批分子能不能往下做"，不是方法论 |
| 计算化学/建模 | `references/POSITIONING.md` + 基石实验脚本 + 挑战包 | 不给调好的超参（会诱发过拟合式使用） | 他们要复现与反驳 |
| 方法学审稿人 | 主文材料 + 负面结果表 + `references/STATISTICAL_POLICY.md` | 不给"全面优于 SOTA"的表述 | 他们要失效边界 |

**2. 讲义（一次性讲清"什么时候不该用"）**
- 60 分钟：证据准入的动机（四源四失效实例）→ 三态裁决 → 取舍（弃权有代价）→ 三个必踩坑（小样本/单位/立体）。
- 讲义必须包含**至少两个负面结果**，否则会把框架讲成"万能过滤器"。

**3. 复现入组（把"用"变成"验"）**
- 新人第一件事不是跑自己的分子，而是跑 `replication/` 挑战包并提交 `submission.json`；
- 只有 `counted` 指标全部落容差内、且非 `suspicious_identical`，才允许跑自己的数据；
- 好处：入门门槛变成一个**可自动判分的动作**，而不是"读文档"。

**4. 版本信用（谁的结果可以引）**
- 对外材料必须写明：`version`（含 `-dev`）、`ADT_REPLAY` 状态、`prereg` 锚定状态（`UNANCHORED` 必须写）、快照 id；
- 缺任一项的数字**不得进入论文表**（红线 3 的可执行版本）；
- 同一份数据在不同版本下结论可能不同——这不是不稳定，是**留痕**的意义。

**5. 反馈入 gate 验证集（推广的闭环）**
- 使用者报告的任何"框架判错/误弃权"案例，按 `badcase` 格式入库，
  **优先补进 gate 验证集**（误放率/误杀率的评估集），而不是只改文档；
- 约束：入库必须带原始输入、快照 id、真值来源；无证据的"感觉不准"不入库，
  但会记录为待验证假设（不得据此调参）。
- 当前 gate 审计已给出基线：hERG 上 gate-as-classifier AUC **0.58**、误杀率 **0.826**——
  任何反馈若能把这两个数字推离"无信息"，就是真实贡献。

---

## 仓库结构：框架入口 vs 一次性评测脚本（C8，2026-11-03 评审）

仓库里并存两类可执行物，**职责不同、标准不同**，此前没有任何文档说清这一点，
新用户（研究生）无法判断"该跑 `adt.cli x` 还是 `run_x.py`"。

| 类别 | 位置 | 用途 | 质量标准 |
|---|---|---|---|
| **框架入口** | `python -m adt.cli <subcommand>` | 面向用户的分析流水线；有 schema 校验、红线守卫、措辞封顶 | 红线接线 + 集成测试（`tests/test_redline_wiring.py`） |
| **一次性评测脚本** | 根目录 `run_*.py`（21 个） | 产生材料里的一次性数字；不进用户流水线 | 清单登记 + `--help` 无副作用 + 产物存在 + 数字进 CLAIMS_REGISTRY（`tests/test_experiment_scripts.py`） |

四条纪律：

1. **不要把 `run_*.py` 当 API 用**。它们没有参数校验、没有红线守卫、不做措辞封顶；
   改动它们不会触发 G8，只会触发 `test_experiment_scripts.py`。
2. **任何进入材料/论文的数字，必须来自某个 `run_*.py` 或 `adt.cli` 的落盘产物**，
   并在 `references/CLAIMS_REGISTRY.yaml` 登记（文件 + 字面量）。口头/截图数字无效。
3. **新增 `run_*.py` 必须登记**（`tests/test_experiment_scripts.py::REGISTRY`），
   否则测试红——这是为了不再出现"21 个脚本零测试覆盖"的历史状态。
4. **看到"86 passed"时要知道它是什么**：那是 86 个测试文件各返回 0，不是 86 条断言。
   2026-11-03 实测发现：函数式测试文件（只有 `def test_xxx()`）用
   `python <file>` 跑是**空跑**——rc=0 但一条没执行，却被计入通过。
   现已改为"脚本跑 + pytest 收集跑"双轨（`tests/test_smoke_pytest.py`）。
   **报覆盖度时只能报"真执行到的东西"，不能报绿灯个数。**
5. **2026-11-22 补丁**：`pytest tests` 之前只收集 smoke 一个文件，`SKIP` 里的
   14 个 pytest 原生测试从未默认执行。现 smoke 增加原生文件逐个执行，
   默认 103 例；换机一条命令：`python tools/verify_all.py`（环境 → API 死代码
   → 版本 → smoke → release-check）。
6. **实验层**：`adt/governance_ext/` 是同行评审后的治理扩展（分割敏感性、OOD
   单调性、ZKP/Merkle、联合封印、信任继承、UQ），**不接主 CLI**；先跑
   `pytest tests/test_governance_ext.py`，真实数据标定后再按 SHADOW→ENFORCE 接入。

### 多重比较（写论文前必读）

同一族里测了 m 次，就**不许只报最小的那个 p**。三端点（hERG/DILI/BBB）的
`Fisher p` 属同一族，Holm 校正后：

| 端点 | p | Holm p | 结论 |
|---|---|---|---|
| DILI | 0.0267 | **0.0801** | 单端点口径可写"有据"；跨端点归纳**不成立** |
| BBB | 0.7554 | 1.0000 | 不显著 |
| hERG | 1.0000 | 1.0000 | 不显著 |

复算：`python run_gate_multiplicity.py` → `out_ext/tdc/gate_multiplicity.json`。

### 已知技术债（明示，不隐藏）

`adt/cli.py` 目前 3.1k 行、30+ 子命令集中在单文件；`reliability.py` 与 `endpoints.py`
各有一份端点匹配逻辑（双真源）。这两项属于**结构性重构**，风险高于收益，
安排在 P2 阶段按 `adt/cli_*.py` 五域（normalize / source / adjudicate / evaluate /
governance）拆分，并在拆分前用 `tests/test_help_all.py` + `test_e2e_cli.py` 锁定行为。
在拆分完成前，任何新增子命令**必须**沿用现有注册方式，不得再往单文件里加业务逻辑。

## 使用规范（同行评审 §8，2026-11-22 补全）

### 专业用户（6 条）
1. 先声明 `--profile`；商业项目不得用 academic 默认档。
2. 输入必须 InChIKey 锚定，禁止名称→SMILES 直接进流水线。
3. `T0/UNDETERMINED` 不得进入排序、申报、对外结论。
4. 交付附 `manifest_sha1 + snapshot sha256 + 生效参数哈希`；生效参数哈希在
   `ADT_SHOW_PARAM_HASH=1` 时由 CLI 打印到 stderr（`[effective-params] sha256=`）。
5. 外部源调用前 `compliance.enforce`，商用档位留 `compliance_calls.jsonl`
   （默认 `logs/compliance_calls.jsonl`，可用 `ADT_CALL_LOG` 覆盖）；
   `compliance.aggregate_calls()` 给出按源×档位×许可的聚合审计。
6. 升级依赖前 `release-check` + 黄金快照；禁止为绿灯改断言。

### 研究生（4 条）
1. 先读 `references/ONBOARDING_10MIN.md` + 跑 `python tools/verify_all.py --quick`。
2. 用阿司匹林/地高辛/瑞格列苷 A 三案例观察 PASS/FAIL/UNDETERMINED。
3. 必须能解释"为什么拒答"，不能只截图（`abstain-why` 命令给出归因）。
4. **`adt/governance_ext/` 和 `experimental/` 的输出不得直接写进论文**——
   它们是实验层（SHADOW），未接主 CLI、未经真实数据标定，只能作为方法学探索记录。

### 推广（4 条）
1. 内部 seminar 讲"证据链 > 预测值"，不演示"SOTA 性能"。
2. 复现挑战：5 个分子 + 期望输出，30 分钟复现（`adt/replication.py` 的挑战包）。
3. 版本政策：对外引用 `0.9.x` + manifest；`4.0-dev` 不写成"已认证/已验证"。
4. 贡献门槛：新模块必须带 `contract + evidence_role + tests + 死代码登记`；
   CLI 新命令须在 `adt/command_roles.py` 声明分层角色（`ADT_ENFORCE_ROLES=1` 强校验）。

