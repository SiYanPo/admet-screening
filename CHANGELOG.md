# admet-screening skill 变更日志

## 同行评审补丁（2026-11-22，doc 4.35，不升能力等级）

**触发**：外部同行评审对 94/94/367 断言证据链提出四点质疑（分割乐观偏差、
UQ 覆盖条件性、审计链信任域、算子贫困），并做全仓静态/运行审计。

**已修（全部有回归）**
1. **默认测试假绿（P0）**：`pyproject.toml` 的 `python_files=["test_smoke_pytest.py"]`
   使 14 个 pytest 原生测试（estimand/external_comparison/panel_fixes/real_truth_legs 等）
   从未进入默认批跑。新增 `test_native_pytest_file_passes` 逐文件子进程执行；
   默认 smoke 从 89 → 103 例，且 `no tests ran` 判失败。
2. **trust.physchem_violations 静默放行（P0）**：传 `physchem_limits()` 整包时
   `limits.get("MolWt")` 为空 → 越界永远为 0，`trust_decision` 不会 REFUSED。
   现同时接受整包/内层契约；`tests/test_peer_review_fixes.py` 覆盖长链越界与无效结构。
3. **零引用公共 API 门禁（P1）**：新增 `tools/api_usage_audit.py` +
   `references/API_USAGE_ALLOWLIST.json`；626 个公共定义中 14 个零引用，
   11 个纳入真实调用回归，3 个显式登记（conformal 自校准 demo / mmp 兼容入口 /
   pubchem 交互辅助）。未登记即 CI 失败。
3b. **`test_help_all` 超时（P0 连带）**：旧实现对 104 个命令各起一次
   `python -m adt.cli ... --help`，Windows 上单次导入 rdkit 可达数十秒，
   600s 超时把默认 smoke 拖红（实测 15min 仅跑到第 8 个命令）。改为同进程
   `CLI.main([cmd,"--help"])`，89 个命令 **37.8s** 全过，`ALL OK`。
3c. **原生测试腐烂（P0 连带）**：真正接入后立即抓到两处过期断言：
   `test_contract_write_guard` 仍断言 25 unresolved/0 matched（实际 0/25），
   `test_interference` 写死 CHANGELOG=4.25（实际 4.35）。已按当前真实状态
   修正并保留可证伪性；14 个原生测试最终 14 passed。
4. **治理扩展层移植**：`adt/governance_ext/` 纳入 split_audit、ood_monotonicity、
   zk_audit、regulatory_seal、stratified_monitor、UQ 等 31 个实验模块；
   明确不接主 CLI，需真实数据标定后按 SHADOW→ENFORCE 接入。
5. **一条命令自检**：`tools/verify_all.py`（环境 → API → 版本 → smoke → release-check）。

**未修（架构级，见同行评审报告）**：4,761 行 CLI 拆分、104 命令收敛、
容器 digest（G6 warn）、13 条阈值中 2 条有意不冻结（G12 warn）、
无 git/资产哈希的可复现包（P1）。

---

## v4.35（2026-11-19）未闭合项清零：8 条"只能测试覆盖"的命令接上真实真值

**背景**：v4.34 面板实跑留下 4 类未闭合。核实后发现本机已有三份真数据，覆盖率里
"需要实测真值"的 8 条命令里 7 条其实可以真跑。

**真数据**：OpenADMET-ExpansionRx（train 25 265 / test 10 738 行实测，9 端点，2 282 化合物）
+ 两个真实模型源 + ChEMBL hERG 外部留出（训练 9 443 / 留出 959）。

**真跑结果（`tools/real_truth_legs.py`）**
- `ablate`：无准入 0.772 覆盖 / **0.2733** 裁对；仅单位守卫 0.760 / 0.8868；
  完整准入 0.068 / **0.9462**。**同覆盖 725 决定**下 0.946 vs 0.829 vs 0.258 ——
  增益不是覆盖假象，但确实是拿 11 倍覆盖换来的。
- `prospect`（时序留出，10 738 对）：准入层 0.8793，无准入 0.2733；
  PASS 组实测失败率 45.3% → 8.3%（但仅单位守卫已 7.8%，域外阻断边际贡献≈0）。
- `conformal`（真实 logD）：n_cal=2 270，q=1.0516，±1.052。
- `conformal-class`（真实 hERG 留出，不相交 477/482）：边际 0.913、类0 0.881、
  类1 0.928、MCG 0.019、CII 0.047。
- `cross-class`（面板 vs OpenADMET）：弃权率 0.973 vs 0.276，方向符合预期。
- `decision-value`：admission ≡ vote_all（EU −124）→ **本场景无增量**，如实报。
- `pred-shift`：去立体位移 0.000；互变异构 logP 位移 0.517（源间 0.628，比值 0.83）、
  TPSA 2.696，**3 个分子净电荷结论翻反**。
- `benchmark`（9 端点真实）：修完方向后平均 AUROC **0.730**。

**修复的 3 个新缺陷**
1. **`benchmark` 没有端点方向概念**：9 个端点里 5 个 AUROC 整体翻反
   （mppb 0.082→0.918、ksol 0.177→0.823、mbpb 0.176→0.824、mgmb 0.198→0.802、
   papp 0.356→0.644）。新增 `_risk_score()` 按规则 shape 定向 + `score_orient` 列；
   并记录命名陷阱：`up/down` 指**好坏方向**不是数值方向。
2. **`pred-shift` 把 no-op 变体的 0.000 当结论**：`ac-plan` 早已标 `noop=Y`，
   `pred_displacement` 从不读该列 → 空转变体集被解释成"结构扰动影响小于源间分歧"。
   现按 noop 排除、单列 `n_noop`/`noop_all`，全为 no-op 时 `verdict()` 拒绝下结论。
3. **`tautomer` 变体本身空转**（根因）：`Canonicalize()` 返回规范互变体，已是规范态时
   原样返回 → 变体与母体相同。改为从 `Enumerate()` 取第一个真正不同的互变体。

**未闭合项处理**
- **BioTransformer 不可达 → 本地 SyGMa 引擎**（Ridder & Wagener 2008, J Cheminform 1:3）：
  新增 `adt/adapters/sygma_local.py` + `bt --engine {auto,biotransformer,sygma}`。
  面板 30/30 分子、**330 个代谢产物**（伊马替尼给出 N-去甲基哌嗪，华法林 6-/7-羟基化）。
  装法两个坑已写进 docstring：`--no-build-isolation`（构建隔离无 rdkit）、`setuptools<81`
  （sygma 1.1.0 仍 import pkg_resources）。**不等于 BioTransformer**，`source` 明确区分。
- **立体盲区证书**（`tools/stereo_ceiling.py`）：机械识别未指定手性中心 → 4/4 分子
  （华法林/普萘洛尔/特非那定/酮康唑）枚举全部 2–4 个立体异构体，10 个描述符
  （含 logD@7.4）**max|Δ| = 0** → 结构性失明，数值只能读作外消旋上限。
- **XenoSite**：复核为**许可边界**（程序化访问需商业许可；前端已 WASM 化，无 REST），
  覆盖率表里从"8 条只能测试覆盖"收敛为**仅 1 条许可边界**。
- **ChEMBL**：重新抓取（当日限流已过；端侧间歇 500，按设计降级为参照分位并保留适用域）。

**产出**：`real_legs/REAL_TRUTH_LEGS_REPORT.md`、`combined_run_report.json`、
`coverage/coverage.md`（COVERED 83 / TEST_ONLY 1 / UNCOVERED 0，待重算确认）；
回归 `tests/test_real_truth_legs.py`（8 例）。


## v4.34（2026-11-19）30 化合物覆盖式面板全流程实跑，修 9 类"只有跑真分子才暴露"的缺陷

**做法**：30 个化合物 / 9 个化学类，结构全部由 ChEMBL InChIKey 锚定；三腿 83 步跑批
（化学腿 A / 统计腿 B / 治理腿 C），命令级覆盖率核算；跑完按真实报错逐条修。

**修复**
1. 输入闸门承诺了"声明消旋体"的门却不存在 → 四态 `defined/racemic_declared/not_applicable/undefined`；
   `report --publish` 结论段首屏打印立体上限（实测 4/30）。
2. `bt` 无可达性预检（源不通时每分子 90s×2 重试 + 31s 限流）→ `preflight()` 8s 短超时，19s 内 rc=3。
3. `glycoside-hyd` 把非糖苷酯（阿司匹林）套进糖苷轴 → 新增 `axis_applicable` 列 + 仅酯键分支（并落盘）。
4. `cardiac` 静默丢弃 `domain_flag=manual` 回填（与自己打印的指引冲突）→ 纳入并提示条数。
5. `schema.advisory_warnings` 漏 `manual`（人工读数无区间可免检）→ 纳入红线 6 提示。
6. `chembl` 无 `--max-neighbors`（30 分子默认 40 邻居 >20 min）→ 新增参数 + 成本说明。
7. `pbpk-qualify` 缺文件裸 traceback、拒绝码 2 与 argparse 撞车 → 缺文件 rc=3、拒绝 rc=4、干净报错。
8. `conformal` 收到宽表直接 KeyError → 入口长表列校验（rc=2 + 期望列说明）。
9. `acyl_glucuronide` 文案残留"失眠适应症"（跨项目串味）→ 改通用表述；登记已知反例
   （双氯芬酸 medium vs 阿托伐他汀 high 与临床排序相反 → 禁止跨分子排序）。

**新增工具**：`tools/panel_fetch.py`、`tools/panel_run.py`、`tools/panel_coverage.py`、
`tools/panel_legb_split.py`；回归 `tests/test_panel_fixes.py`（10 例）。

**边界**：conformal/benchmark 用合成配对（truth 真、pred ±8%），只验接线；
BioTransformer 在本网络不可达，记为 REFUSED，不写成"0 代谢产物"。


## v4.33（2026-11-19）G14 外部对照台账门：把"自验会共享盲点"变成可检的账

**动机**：连续三轮出现"selftest 全绿但实现是错的"（t 分布 df 用 n；Holm 回填错位导致
结论颠倒；OOT 基线含待检尾部导致 SD 膨胀 30× 的系统性漏报）。三次同一结构：自测与实现
同源，模型错则两边一起错。唯一能打破闭环的是"另一个来源的实现"。

**新增**
- `adt/external_comparison.py`：同一统计量算两遍——`ours` 为真正被调用的函数，
  `ref` 为本文件另行写出的参考实现（scipy 1.18.1 / 教科书闭式 / 独立复算）。
  6 模块 28 对照点：Clopper-Pearson、Wilson、Newcombe、Holm（`stats_ci` 与
  `paired_stats` 两处实现同时比对）、相关系数双尾 p（df=n−2 哨兵）、OOT 基线
  （前缀哨兵）。实测最大偏差 5.2e-15。
- `references/EXTERNAL_COMPARISON_LEDGER.yaml`：`required_modules` 为棘轮（新增统计
  模块必须先进台账）；每条挂对照脚本 / 独立审查报告 / 回归测试节点 / 声明容差。
- `release_gate._check_external_comparison` → **G14_external_comparison（blocker）**
  接入 `release-check`：不只查台账格式，而是实跑对照，实测偏差超声明容差即拦——
  避免"台账写 0、代码已漂移"。
- CLI `external-compare --selftest`；回归测试 `tests/test_external_comparison.py` 9 例，
  含 4 条对抗探针（参考实现偏移 50% / 容差写死 1e-18 / 棘轮漏登 / 审查报告缺失）
  必须转红，以及"OOT 对照组必须同时出现 OOT 与 IN_CONTROL"的漏报型防线。

**同期修复（文档承诺 ≠ 代码行为）**：复现挑战包 README 要求"交实现 + 环境指纹"，
但 `replication.score()` 只比对数字，纯数字提交仍 `verdict=pass`。现两处评分器
（`adt/replication.score` 与包内生成的 `score.py`）一致要求 `implementation`
（code/repo/files）+ `environment`（python/rdkit/numpy），缺则 `verdict=numbers_only`、
退出码 2；`SUBMISSION_TEMPLATE.json` 与包内 README 同步更新；回归测试 +1 例
（`test_numbers_only_submission_is_not_replication`，含三档退出码断言）。

**边界**：G14 只声称"实现与参考实现逐点一致"，不声称统计假设成立或结论正确。


> **2026-11-11 增量（刻意不升版本号）**：新增离线结构干扰红旗层
> `adt/interference.py`、源健康探针 `adt/source_health.py`、`adt.cli interference /
> source-health` 两个子命令、`03_endpoint_rules.yaml` 的 `f_oral` 三分口径与
> `not_covered_endpoints` 显式缺口登记、`claims_audit` 干扰措辞断言、回归测试
> `tests/test_interference.py`，并补登记 VERSION_POLICY 台账（4.22→4.25，修复
> `test_version_divergences_all_declared` 真实失败）。
> 不新增 `## v4.xx` 标题，是为了**不制造第五轨版本分歧**：`adt.version` 的四轨
> 观测值保持不变，`python -m adt.version --strict` 仍 rc=0。全部为本地离线能力，
> 不依赖 SciMiner/API/积分/联网预测。详见 SKILL.md 对应章节。
>
> **2026-11-11 第二轮增量（同样不升版本号）**：系统盘点 85 个模块 / 70 个命令 /
> 测试引用矩阵后，补齐 4 类可静态举证的缺口 ——
> ① `adt/coverage_gate.py` 把 `not_covered_endpoints` 接进生产链路（`report`
> 无条件并入声明、失败即 exit 4；`claims_audit --coverage-declaration` 校验），
> 修复 `07_case_lessons.md` C82「登记不接线」的复发；
> ② `adt/interference.py::physical_interference()` 补胶体聚集 / 自荧光 / 成醌
> 三类离线结构预警（严格 SMARTS，C87 愈创木基回归），端点表 3 项由
> `not_covered` 升 `partially_covered`（仅结构预警，实验判据仍缺）；
> ③ `adt.cli local-tools` 把 6 个离线工具接入主 CLI（显式重建 argv，
> 实测 `REMAINDER` 会把 `--` 参数交给主解析器）；
> ④ 补 9 个无文档命令索引 + 3 个零引用模块回归测试。
> `adt.cli` 命令数 70 → 72。新增 `tests/test_coverage_gate.py`、
> `tests/test_module_wiring.py`，扩展 `tests/test_interference.py`，并同步登记
> `test_smoke_pytest.py::SKIP`。端到端实跑见项目侧《补齐后实际运行分析.md》：
> 6 工具 12 次 0 失败、真实分子物理三层全 none、产物 sha256 两次一致、
> `report` rc=0 且 5/5 声明标记、全量声明审计 0 违规；旧 `conclusions.md`
> 被审计判违规后重跑更新（备份留痕，不追溯改写）。

## v4.25（2026-11-06）——S1a：撤回标记贯通 + n_eff 口径对齐 + 切分类型登记

一句话：**按评审交付物 `05_FinalActionCard.md` 执行「不依赖外部真值」的 S1a 工程项；
不改任何生产裁决逻辑，两条 `reliab` 基线数字逐位不变。本轮不产生新科学证据，不做 S0/S1b。**

### 一、撤回标记贯通（F1，04 之后新发现的真实缺口）

- **复用**既有 `status: superseded` 机制（`references/CLAIMS_REGISTRY.yaml:175`），
  **未新建第二套撤回清单**（外部评审 V1）。`indifference_curve` 补 `status: superseded`、
  `admissible_for_external_use: false`、`retracted_at`、`retraction_ref: R4`。
  `verify_registry_fields()` 计数由 `retracted=1 / unresolved=26` 变为
  `retracted=2 / unresolved=25` —— 已撤回主张从「未绑定字段」移出证据聚合，
  是**更严格**的分类；`tests/test_contract_write_guard.py` 两条断言如实同步，不是为全绿放宽。
- 全库扫描发现 F1 范围大于 05 所记：除 c\* 族外还含 R1/R2。已改
  `SKILL.md:112`（脚本清单把 c\* 当结论）、`SKILL.md:211-212`（条件性优势）、
  `references/NEGATIVE_RESULT_DEFAULTS.yaml` 的 R4 两处与 R1/R2 两处、
  `adt/defaults.py:44` 死常量注释。`default` 值、条目数、`expect` token **全部未动**
  ⇒ `defaults.assert_consistent()` 仍 `ok=True / 8 条 / 证据 8 条`。
- `adt/claims_audit.py` 新增 `verify_no_retracted_claims()` + CLI `--retractions`：
  扫活跃对外文本，命中 R1/R2/R4 禁用表述且无撤回标记即违规；历史评审档案
  audit_only，**不追溯改写**。正反双向实测：正常 0 违规（rc=0）／故意注入一条
  未标记旧句 1 违规（rc=1）／还原 0 违规（rc=0）。**未接入 G1–G12**
  （避免改变现有门禁行为），由 S1b 的 G13 挂接。

### 二、口径对齐（04 §4.1 P0 / V1）

- 新增 `tools/reconcile_existing_impl.py`：只从 `adt.independence` 导入既有函数，
  并排输出 `n_eff_from_corr_matrix` / `n_eff_equicorrelated` / `n_eff_kish_eigen` /
  GLS 对照列 / `Var(μ̂)`，6 条断言全过（rc=0，JSON 可复现）。**未另起实现**。
- 第一手发现：等相关矩阵下 GLS 式与 Kish 口径数值一致（一般 Σ 才分叉，故采用 GLS
  必须显式声明 `aggregation_operator`）；ρ<0 时 `n_eff_equicorrelated` 内部
  `max(rho,0)` 把负相关截断为 0 给出 `n_eff=k`，而矩阵口径给出 `n_eff>k`
  （k=2, ρ=−0.5：4.0 vs 2.0）⇒ 生产路径须触发 `SOURCE_POLARITY_CHECK`（J1），已立为断言 A6。
- 生产路径取证：`independence.py:300` 用等相关标准形；`adt/cli.py` 中
  `n_eff_kish_eigen` 零命中 ⇒ 不存在第二套计票实现。

### 三、切分类型登记（F2 / Q3·D3 定案）

- 新增 `references/SPLIT_TYPE_REGISTRY.yaml`：pytdc 1.1.15 源码实读，
  benchmark_group 的 `split_method` 枚举 = `{random, scaffold, combination, group}`；
  `create_fold_time(df, frac, date_column)`（`utils/split.py:296`）是独立函数，
  **不在枚举内**且需 `date_column` ⇒ 三条曲线里的 temporal 不得声称是 TDC 官方切分，
  且在日期列登记前不得报告 temporal 曲线。仍待核实：本项目 ADMET 端点数据
  是否有可用 `date_column` 及其语义（实验日期／文献年份／入库时间）。

### 四、回归与回滚

- 本轮全部改动均为「文本标记 / 诊断脚本 / 登记表」，**不触碰 `reliability.py` 判定、
  阈值、`default` 值**；两条 `reliab` 基线须逐位复现 05 §1 的数字。
- 回滚：6 个被改文件的改动前字节 + SHA256 清单保存在评审工作区
  `s1a_baseline/`（`SHA256_BEFORE.txt` + `files/`）。skill 目录**非 git 仓库**且体积
  1.3 GB，故未按 02 PRE 的 `git init -A` 建基线，改用文件级快照。
- **未做**（S0/S1b，硬阻塞于 B3 与口径定稿，不得冒充已完成）：estimand cards、
  实测代价矩阵、`SAP_FROZEN.yaml`、正式第三方时间戳锚、`decision.py` /
  `reference_impl.py` 两套实现、G13、B3 全批次外部真值。

---

## v4.24（2026-11-05）——OneADMET SI / ORCA 全盘定位入包 + 模块 L 逐位复现

一句话：**用户指出两项"需人工下载/注册"其实早已完成；本机全盘定位后把它们从
"外部阻塞"变成随包资产 + 机器可判的自检项，并用随包脚本把 v3.6.1 的 L 项结论
逐字节复现了一遍，不再依赖旧机器上的一次性脚本与硬编码路径。**

### 一、定位（第一手证据）

- `~/Downloads/jm6c00049_si_002.zip`（35,054,958 B，
  SHA256 `09d8eb35f541253c61f1ced6acd383f260a624986c924ef967382953c535f60e`）
  内含单个 `oneADMET.csv`：1,197,248,494 B、SHA256
  `c0860bf9c47806d9867f95b84bdfda8a62c189f891e1d951765fdd283d51034c`、
  ZIP CRC `149a7f43`、738,162 行（SMILES + 44 端点）。
- `D:/WorkBuddy/pharma-tools/ORCA611/`（36 GB / 293 个 exe）：ORCA 6.1.1 已装。
  `orca.exe --version` banner 有 `Program Version 6.1.1  -  RELEASE  -` 但固定 **rc=2**
  （与 PK-Sim 的 rc=1 同类陷阱）；HF/def2-SVP H2O 单点 rc=0、
  `ORCA TERMINATED NORMALLY`、E = −75.960838753103 Eh、10.7 s，这才算可用证据。
- 旧工作区留有 2026-10-30 的 `instances/v350/` 产物与一次性转换脚本，但脚本硬编码
  `D:/WorkBuddy/本地文件/2026-10-27-...`，当前 skill 内既无数据也无脚本 ——
  即"文档宣称 L 已闭环、换机却无法复现"的真实缺口。

### 二、修复（全部零硬编码本机绝对路径）

- 新增 `tools/` 三个可移植脚本：`build_oneadmet_longtables.py`（默认校验 SI SHA256，
  口径不符直接拒绝；`retrieved_at` 固定为取数时刻以保证逐位可比对）、
  `probe_oneadmet_dimensions.py`（量纲探针）、`tdc_export.py`（联网重取 TDC，
  离线用随包快照）。
- SI + TDC 快照 + 重建后的两组长表随包落到 `assets/external/oneadmet/` 与
  `instances/v350/`；新增 `assets/external/oneadmet/PROVENANCE.json`（哈希、口径、许可）。
- `adt/env_audit.py` 新增 `data.oneadmet`（required）、`ext.orca`（external）、
  `--deep`（ORCA H2O 单点 + 1.2 GB SHA256/行数）；新增 `discover_orca()` 有限广度
  自动发现（≤3 层 / ≤2500 目录 / 只认目录里真有 `orca.exe`，命中耗时 0.15 s）。
- `bootstrap.py` 路径映射新增 `orca_dir` / `oneadmet_csv` 两键并转发 `--deep`；
  重入检查对这两键验证产物可用，不验证路径字符串。CLI 新增 `env-audit --deep`。
- 文档同步：`SETUP_REPRODUCE.md` §0/§1/§4.1/§5.1/§6/§7/§8、
  `references/02_source_registry.yaml` 的 `orca` 事实字段、`assets/external/README.md`、
  `SKILL.md`（doc_revision 4.24 + 文件清单）、`L项四方案实测裁决与闭环结果.md` 第八节。
  registry 的 `status: needs_probe` **刻意不改**：那是计票/准入层的保守标记，
  本机装了 ORCA ≠ 该源可作为预测证据，改状态会改变上游行为。

### 三、本轮实测验收

| 检查 | 结果 |
|---|---|
| `python tools/probe_oneadmet_dimensions.py` | exit 0；MLM CLint max 10,354.8 等数值与 C90 记录一致 |
| `python tools/build_oneadmet_longtables.py` | exit 0；11,944 / 29,258 行；`cmp` 与 2026-10-30 产物**逐字节一致**（2,313,273 B / 5,470,516 B） |
| `python -m adt transfer`（三数据集） | exit 0；`transfer_profiles.csv` 与旧产物**逐位一致**：11,944/0.1488/值级 0 拒绝、22,656/0.134/29,258 值 38 拒绝（0.1299%）、17,248/1.000 |
| `python -m adt env-audit --deep --quiet` | exit 0，**45 项全绿**（原 41 + 4）；ORCA E=−75.960838753103 Eh、SI SHA256 与 738,162 行 |
| `python -m adt env-audit --network --deep` | exit 0，**56 项**；仅 SwissADME 403 / PyPI 429 两条时点告警 |
| `python bootstrap.py`（全链路含 pytest） | **exit 0**（4m38s）；pytest **89/89** |
| `python -m adt release-check` | **PASS**；G1/G4/G8 全绿，4 条既有 WARN 与 v4.23 相同 |
| `python -m adt.redlines` | 9/9 已接线 |
| 模拟换机（删 `.env_audit_paths.json` 后重跑 bootstrap --skip-tests） | exit 0；自动发现 R 环境、**ORCA 6.1.1**、**OneADMET SI**；env-audit 返回 2 仅因 `ADT_PYSCF_ENV` / `ADT_OPENMM_ENV` 未显式配置（设计预期，不把别的项目环境当本 skill 依赖） |
| `bash -n bootstrap.sh` / `.bat` 静态校验 | 通过；`.bat` 844 B / CRLF 21 / 裸 LF 0 / 非 ASCII 0 |
| 新代码/注册表静态校验 | 4 份 YAML + PROVENANCE.json 可解析；`tools/`、`adt/env_audit.py`、`adt/cli.py`、`bootstrap.*` 排除 URL 后**零硬编码本机绝对路径** |

**未验证（如实）**：`bootstrap.bat` 双击执行 —— `cmd.exe` 在 Bash 与 PowerShell
工具中均被安全策略明确禁止（本轮从 PowerShell 调用同样返回 `Command blocked for
security`），只能做静态校验；同一 `python bootstrap.py %*` 逻辑已实跑。
PK-Sim 仿真层往返、三个商业平台、Linux/macOS 重建 R 环境耗时仍未闭环。

---

## v4.23（2026-11-05）——全面环境排查 + 换机可复现层（bootstrap / env-audit）

一句话：**把"换一台电脑还能不能完整跑起来"从事后补救变成可机器判的门禁。
排查发现 3 类真实缺陷（锁文件漂移、可选软件缺失、文档/注册表 stale），全部修复并实跑验收。**

### 排查发现（均为第一手证据，非推断）
1. **`requirements.lock` 停在旧栈**：rdkit 2026.3.6 / pandas 2.3.3，而 2026-11-03 环境漂移后
   实测是 2026.9.1 / 3.1.0。按旧 lock 装会复现出不同数字。已按实测回填。
2. **架构声明可用、主环境实际缺失**：`Pharmpy 2.3.0`、`pytdc 1.1.15`（MODULE_MAP §4.1 与
   SETUP_REPRODUCE §4.2 都写了实测结论，但主 Python 里 import 不到）。
   另缺 `tqdm / fuzzywuzzy / openpyxl / setuptools(pkg_resources) / huggingface_hub`。
3. **文档互相矛盾**：pip 镜像在 requirements.txt（华为云）与 SETUP_REPRODUCE（阿里云）不一致；
   测试数写了 75/75 与 86/86，实测收集 **89**；`pharmpy` 包名写错（正确是 `pharmpy-core`，
   PyPI 上 `pharmpy` 只有 0.0.1/0.0.2 占位版）；registry 的 `pk_sim_mobi`、
   `nlmixr2`、`pharmpy` 三条仍写"本机未安装/未验证"。

### 从官方来源补装并实跑验证
`pharmpy-core==2.3.0`、`pytdc==1.1.15 --no-deps`、`tqdm==4.70.1`、
`fuzzywuzzy==0.18.0`、`openpyxl==3.1.5`、`setuptools==80.9.0`、
`huggingface_hub==2.4.0`（PyPI 官方包经华为云官方镜像下载：
实测 pypi.org 索引 200 但 wheel 下载 3 分钟零输出）。
验证：`from tdc import BenchmarkGroup` OK、`pharmpy.modeling.create_datainfo` OK、
`PKSim.CLI` 版本串 OK、`micromamba run ... Rscript` 报出 R 4.5.3 / nlmixr2 5.0.0 /
rxode2 5.0.2 / qs2 0.3.1 全部 OK。

### 新增（可移植层）
- `bootstrap.py`：纯标准库、幂等、多镜像 fallback（429 自动换源）、日志落盘
  `logs/bootstrap_<ts>.log`、失败即停并打印返回码；重入检查验证**产物可用**而非目录存在。
- `adt/env_audit.py` + CLI `env-audit`：分 required/optional/external/network 四层，
  退出码 0/1/2 机器可判；外部工具全部走 `ADT_*` 环境变量或 `.env_audit_paths.json`
  （bootstrap 每次重生成），代码内零硬编码本机绝对路径。
- `bootstrap.bat`（CRLF + 纯 ASCII）/ `bootstrap.sh`（LF，`bash -n` 通过）。
- `requirements-optional.txt`：可选层精确钉版，与核心 lock **强制分开**
  （pytdc 元数据会强拆 numpy/pandas/rdkit，实测 dry-run 直接崩在源码编译 numpy）。
- `SETUP_REPRODUCE.md` 重写：官方下载网址、需注册/授权项当场给链接、
  18 条环境坑、四层复现验证、已验证/未验证清单。
- `README_CN.md` / `SKILL.md` 的硬编码解释器路径改为 `${PYTHON:-python}` 与环境变量。
- registry 三条 stale 条目按实测复核修正。

### 全链路验收（2026-11-05 实跑）
| 命令 | 结果 |
|---|---|
| `python bootstrap.py` | exit 0（89/89 pytest、env-audit exit 0） |
| `python -m adt env-audit --quiet` | exit 0，必需/可选/外部层均无缺失 |
| `python -m adt.redlines` | 9/9 已接线（7 hard / 1 soft / 1 conditional） |
| `python -m pytest -q` | 89/89 通过（含新命令 `env-audit --help` 的自动发现测试） |
| `python -m adt release-check` | PASS（G1 全量精确钉版 / G4 指纹一致 / G8 红线 9/9） |
| 模拟换机（删掉 `.env_audit_paths.json` 后重跑 bootstrap） | exit 0；核心 10/10 判"已可用无需安装"，经 `micromamba env list --json` 自动发现 R 环境，外部层 0 问题 |
| `bash -n bootstrap.sh` | 通过；`.bat` CRLF/纯 ASCII 静态校验通过 |

### 未验证（如实列出，不假装闭环）
- `bootstrap.bat` 的**双击执行**无法在本沙箱实测（安全策略禁止从 Bash 调用 `cmd.exe`，
  PowerShell 隐式调 cmd 会挂起）；已做 CRLF/编码静态校验，主入口 `python bootstrap.py`
  与 `bootstrap.sh` 均已实跑通过。换机在 Windows 上双击前，可先用
  `python bootstrap.py --verify-only` 验证同一逻辑。
- PK-Sim **仿真层**往返仍未闭环（化合物层 32/32 已验）；
- OneADMET SI 1.2 GB 需人工过 Cloudflare（网址见 SETUP_REPRODUCE §4.1）；
- 换机到 Linux/macOS 重建 conda-forge R 环境的耗时未知（repodata 约 294 MB）。

## v4.22（2026-11-04）——run7 全流程实测（9 化合物 × 67 子命令全覆盖）+ 五处真修复

一句话：**用 9 个不同类别化合物（TCM 单体 + 西药阳性对照）把全部 67 个 CLI 子命令真跑了一遍，
四条生产者-消费者断链被全流程逼出并修复；cardiac 首次获得真实 ChEMBL 通道 IC50 输入；
xenosite 手动回填通道闭环；driver 全 7 阶段 60 步 0 FAIL。**

### run7 化合物集（类别互异，覆盖各失效分支）
黄苓苷（糖苷/多酚，酸性）、葛根素（异黄酮糖苷）、大黄酸（蒽醌酸）、小檗碱（季铵碱）、
地高辛（强心苷）、胺碘酮（多碘阳离子西药）、双氯芬酸（NSAID 酸）、二甲双胍（双胍，
触发 tautomer 分支）、槲皮素（多酚邻苯二酚，触发成醌通道）。

### 修复（本轮全流程逼出，全部有复现证据）
1. **pbpk `cmax_uM` 算而不落盘** → cardiac `--exposure` 永远缺文件（第 1 条断链）。
   新增 `pbpk --dump-cmax`，落 `pbpk/cmax_uM.csv`（6 分子）。
2. **糖环判定过松**（任意含氧 5/6 元环即判糖）→ 修为真糖环模式匹配；
   修复前 Baicalin/Puerarin/Digoxin 三个真糖苷不触发糖苷水解轴。
3. **gut-micro 单分子网络失败整批炸** → 单分子失败隔离（计入 out_of_domain，
   其余分子继续）+ `--poll-timeout` 可调（默认 300s）+ 阳性对照 FAIL 改为
   降级警示（结果只能作背景，不再 SystemExit(3) 整批作废）。
4. **xenosite prepare 只出任务清单不出回填模板** → ingest 永远缺输入（第 2 条断链）。
   prepare 现在同时生成 `xenosite_readback_template.csv`（预填 compound_id/model/endpoint，
   人工只填 value；空 value 并表为 out_of_domain，诚实不过票）。
   run7 实测 54 行按 out_of_domain 并入 merge（303→357 行），reliability 判定不变
   （PASS 2 / FAIL 4 / UNDETERMINED 156 / PASSTHRU 132）——域外行正确不进计票。
5. **ChEMBL `molecule?inchikey=` 端点在本环境行为异常**（查任何 key 都返回同一氯代吡唑）。
   cardiac 的真实通道 IC50 改走**相似度搜索路径**（复用 chembl adapter 已验证的
   Tanimoto 邻居→活性查询链）：Berberine hERG=66 µM、Amiodarone hERG=10 µM +
   Nav1.5=0.041 µM、Diclofenac hERG=30 µM、Quercetin hERG=30 µM（全部带 provenance）。
   cardiac 首次跑出有意义的结论（Amiodarone 因 pbpk CLint/fu 越界跳过 →
   心脏安全裕度 not_estimated，如实暴露"模型跳过 = 裕度算不出"的真实张力）。
6. **季铵被误判为中性**（run7 逼出，影响 BBB/膜渗透方向判断）：Berberine 芳环
   `[n+]` formal charge=+1，却因"无可电离 pKa 基团"被判 `neutral_no_group`/
   net_charge=0。新增 `permanently_charged` 类别：分子总 formal charge≠0 时
   直接按永久荷电处理（net_charge=formal、f_neutral=0），与 pH 无关。
   回归测试 `test_quaternary_ammonium_is_permanently_charged` +
   `test_truly_neutral_no_formal_charge_stays_neutral`（萘守卫）。

### 其他
- run7 driver（`run7_driver.py`）merge 步骤逗号拼接传参 bug（argparse 收成单一路径），
  改为逐参数传递；baseline 改用 OpenADMET 外部 split（9 分子批不足 min_train=20，
  这是对该命令既定用法的一次澄清而非缺陷）。
- 门禁：`pytest tests/` **89 passed**（smoke 汇编器口径；其中 test_extension_v414.py
  44→**46** 例，本轮新增 2 条季铵回归）；driver 全 7 阶段（base/ext/new/analysis/gov/pk/extra）
  **60 步 0 FAIL 0 SKIP**；external OpenADMET（train 5326/25265 实测）+ NPASS
  （train 916/test 391/76 条 ADME）真跑。

## v4.21（2026-11-04）——外部工具真装真跑 + 七模块实例分析 + 模块全景成文

一句话：**上一轮写的是"函数就绪"，这一轮把七个新模块用 32 个真实分子端到端跑了一遍，
装上四款外部工具，抓出七个真 bug（其中一个是"收敛但错误"的假成功），并把"模块之间怎么互相印证"第一次写成矩阵。**

### 新增
- `references/MODULE_MAP_v4.21.md`：**模块全景 / 运营流程 / 交叉印证矩阵**（本版最大交付物）
  - §0 四层定位：L0 结构与状态（normalize / structure alerts / pKa）→ L1 证据采集
    （外部源 + 回填）→ L2 裁决（reliability / 域判别 / 决策漏斗）→ L3 交付（措辞 / 报告）。
    **层间单向依赖**：下层不许回头改上层结论，只有 L2 能改 `domain_flag`。
  - §1 四张模块清单表，每行写"它回答什么问题 + **不做会怎样**"（不是功能罗列）
  - §2 运营流程：10 步主链 + **三分支**（无实测 / 源分歧 / 交外部工具），每步给判停条件
  - §3 **五组交叉印证矩阵**（结构→一切、理化↔暴露↔通道、代谢↔代谢、模型↔模型、结论↔产物），
    每行都写"两者对不上时优先信谁、怎么记录"
  - §4 本轮四条硬结论；§5 三个常见误读
- `adt/interop.py`：**OSP 快照导出** `pk_sim_snapshot()` / `write_pk_sim_snapshot()`，
  `PK_SIM_SNAPSHOT_VERSION = 80`（版本号取自官方 Midazolam-Model v2.0 快照，不是猜的）。
  CLI 加 `--snapshot`，产出 `pk_sim_snapshot.json`（32 KB，PK-Sim `snap -p` 直接可吃）
  - 缺 logP → **不写** `Lipophilicity`（PK-Sim 会用默认值）并记 `problems`
  - 缺 fu → 记"PPK 结论作废"
  - Caco-2 Papp → **故意留空**并进 `omitted`：换算系数不是常数，硬填等于编造
  - pKa 只给数值时按电离类别猜 `PkaTypes` 并**在 meta 里记一笔**
- `adt/interop.py`：`nonmem_id_map()` / `nonmem_dataset(id_map=...)` —— NONMEM 侧整数 ID 契约
- `out_case/`：本轮实例分析全部产物（pka / pbpk / pd / interop / qualify / cardiac / gut /
  readback / pksim_in|out），可直接复跑比对

### 安装（全部官方来源，全部实测可运行）
| 工具 | 来源 | 闭环程度 |
|---|---|---|
| PK-Sim 12.3.173 | OSP 官方 GitHub Releases，portable ZIP（经 ghproxy） | `pk_sim_cli_snap_passed`（化合物层） |
| MoBi 12.3.136 | 同上 | GUI，无 CLI；随包带 Diclofenac 示例 |
| Pharmpy 2.3.0 | 官方 PyPI | `pharmpy_dataset_ok` |
| R 4.5.3 + nlmixr2 5.0.0 + rxode2 5.0.2 | conda-forge（micromamba 用户态） | `nlmixr2_fit_passed`（COMPILE_OK + FOCEI 收敛） |

`validated_against_tool` 因此**从布尔值改为三级**——这是本轮对"诚实标注"的实质修正：
一个 `False` 掩盖了"PK-Sim 化合物层已经往返一致"和"nlmixr2 连编译都没过"的巨大差别。

### 修复（三个真 bug，全部由实例分析逼出）
1. **`cardiac_panel` 把"有数据缺暴露"报成"无通道数据"**（事实错误 + 方向错误）：
   只有 IC50 没有 Cmax,u 时旧逻辑给 `undetermined_no_channel_data`，
   会把读者引去"再测一遍通道"，而真正缺的是**暴露**。
   → 拆 `has_data` / `tiered` 两态，新增 `undetermined_missing_exposure`
   （附"已测 k/3 通道"）。实测复验：无 Cmax → `undetermined_missing_exposure 已测 1/3`；
   加假设 Cmax 0.1 µM → caffeic_acid `herg_only_intermediate`（margin 25.1）、
   CAPE 106 / taxifolin 96 / curcumin 55.5 均 `herg_only_low`。
2. **NONMEM / Pharmpy 要求 ID 是整数**：`ID=A-1` 触发
   `ValueError: invalid literal for int()`。这是**契约缺陷不是环境问题**——
   任何人拿 `compound_id` 直接当 ID 都会踩。→ `nonmem_id_map()` + `validate_nonmem`
   硬校验 + 落 `nonmem_id_map.csv`。重跑后 Pharmpy 真读通过：11228 行 / 12 列 /
   28 受试者 / 28 次给药。
3. **`pbpk-qualify` 配对只有 n=10（应为 40）**：A-1 的曲线在 12–168 h 衰减到 0/负 0，
   被 `C>0` 过滤掉却没报出 → 只用早期时点重做，得 n=40 / AFE 0.99 / AAFE 1.14 /
   2 倍内 100% / rmse 0.06。**静默丢时点=静默缩小样本**，与"静默丢仿真"同类。

4. **conda-forge 的 `r-qs2 0.2.1` 与 RcppParallel 自带 `tbb.dll` 死锁**（这是"nlmixr2 跑不起来"的真因，
   与编译器无关）。现象：`library(rxode2)` 挂 4 分钟以上；`Rprof` 采样 2986/3283 落在
   `inDL ← dyn.load ← library.dynam ← namespaceImportFrom`（R 层无代码在跑）；
   `dyn.load(qs2.dll)` 在 tbb 可见时挂死、不可见时秒错——**两种失败形态完全不同**。
   → 用**官方 CRAN 的 Windows 二进制** `qs2_0.3.1.zip` 替换（conda 删目录 + 解包，先备份
   `qs2.bak-0.2.1`），此后 `rxode2` 4 秒加载、`rxSolve` 一次编译通过（cmax 1.391 @ 4 h）。
   **教训：卡在"加载"而不是"编译"时，别去装 Rtools。**
5. **给药与观测同 `CMT`，NONMEM 会把血浆浓度当胃肠道浓度**（见 MODULE_MAP §4.4）：
   原 `nonmem_dataset` 只用一个 `default_cmt` → 给药与观测都是 1。nlmixr2 单端点模型
   不按 CMT 匹配输出，所以"看起来能跑"；NONMEM `ADVAN2` 里 CMT=1 是胃肠道，吸收相直接消失。
   → 拆 `obs_cmt`（口服默认给药 1 / 观测 2）+ `cmt_layout()` / `cmt_split_ok()` +
   `validate_nonmem(expect_cmt_split=True)`，CLI 加 `--dose-cmt` / `--obs-cmt`。
6. **把"数值零"当观测，会得到收敛但错误的拟合**（本轮最重要）：
   pbpk 曲线 12–30 h 已衰减到 0，之后约 370/400 个时点 DV 是 ODE 数值零。
   喂进去后目标函数被零主导，实测 **bobyqa 正常退出、tcl 停在初值 6.0 不动、
   tv 估成 2978 L（t½=344 h，而曲线实际 t½≈1.6 h）**。
   → `mask_nonpositive_obs()` 置 `MDV=1` 并报条数（本例 8037 条），validator 增对应检查。
7. **骨架的默认初值差两个数量级**：原写死 CL 5 L/h / V 50 L，本批数据 V≈1400 L，
   直接跑会卡在初值附近。→ 新增 `pk_initials()` 从 C(t) 推初值
   （V0=AMT/Cmax、ka0=1/Tmax、CL0=λz·V0、addSd=0.05·Cmax），
   并修掉两个自己踩的坑：末端斜率取在衰减到 0 的尾巴上会得 λz≈0（CL 估成 0.001 L/h）、
   残差地板按全样本中位数会给 2e-06（"噪声为零"的假初值）。
   顺带把骨架的数据路径改成**绝对路径**（原来用相对路径，换个 cwd 就跑不了——实测报
   `cannot open file 'out_case/...'`）。

### 实测（32 个真实分子 + 4 个文献分子，每个模块都有产物）
- `pka`：32 分子，3 个显著电离（BH5/BH46 脂肪胺 +0.99）
- `pbpk --dump-curves`：11201 行 C(t)，28 分子（4 个因 CLint/fu 越界**被跳过并报出**）
- `pd --ec50 0.5 --hill-n 1.2 --dosing-interval 12`：28 分子，1/28 达 ≥50% 覆盖
- `interop --what all --snapshot`：`pk_sim_compounds.csv` + `pk_sim_snapshot.json` +
  `nonmem_dataset.csv`（11228 行）+ `nonmem_id_map.csv`（28 条）+ `nlmixr2_skeleton.R`
- **PK-Sim 真机往返**：`snap -p` → `pk_sim_snapshot.pksim5`（540 KB）→ 再导快照，
  **compounds = 32，数值逐位一致**（A-1: logP −4.05 / pKa Acid 10.0 / MW 562.52）；
  缺失的 fu/Solubility 被 PK-Sim 补成默认对象（所以"能读"≠"参数全"）
- `gut-micro --option HGUT --dump-raw`：阳性对照 **PASS（APAP→3）**；
  quercetin=7 / APAP=3 / caffeic_acid=10；17 条菌群产物中
  **9 条 reaction_type 与质量差矛盾、7 条一致、1 条待定**
- **nlmixr2 真跑**（直接执行生成的 `nlmixr2_skeleton.R`，不是另写脚本）：
  `COMPILE_OK`；FOCEI 收敛（"Normal exit from bobyqa"）；OBJF −29612.53；
  V=1433 L / RSE 3.8%，CL/ka/F 不可辨识。完整输出存 `out_case/interop/nlmixr2_fit.txt`
- **Pharmpy 复读**（换新数据集后）：11228 行 / 28 ID / EVID{0:11200,1:28} /
  CMT{给药:[1], 观测:[2]} / 有效观测 3163 条 → `out_case/pharmpy_check.txt`
- `cardiac` 两情形（见上）；`pbpk-qualify` 两路径（见上）；
  `readback`（自定义 `literature_2026_herg`）：5 行 → 4 长表行，quercetin 结构不符进 `unmatched`

### 门禁终态
- `pytest tests/` **89 passed**（rc=0，8m08s）；`tests/test_extension_v414.py` **44 passed**
- `release-check` **PASS**（G1–G12；G10 27/27；G8 9/9；仅 G4 env_fingerprint 与
  G12 `ad_anchor:not_frozen` 两项既有告警）
- `out_case/interop/nlmixr2_fit.txt`（骨架直跑输出）与 `out_case/pharmpy_check.txt`（Pharmpy 复读）已落盘

### 文档
- `SKILL.md`：`doc_revision` → 4.21；两处文件清单加 MODULE_MAP 引用；
  **已知限制从"八条"改写为"十一条"，并把过时表述逐个更正**
  （原文"PK-Sim/nlmixr2/Pharmpy 全部未安装"已不成立；菌群 "7/7 矛盾" → 实测 9/17）
- `references/EXTENSION_ANALYSIS_v4.14.md` §7 第 1 条同步改写为三级分级说明

### 仍开放（写清而不是含糊过去）
- ~~rxode2 模型编译~~ **已闭环**：真因是 conda `r-qs2 0.2.1` 与 `tbb.dll` 死锁，
  换官方 CRAN 二进制后一次编译通过，**不需要 Rtools**。
- **nlmixr2 只估得出 V**：屏蔽数值零后 3163 条有效观测，V=1433 L（RSE 3.8%）可估；
  CL/ka/F 的 95%CI 跨四个数量级（flip-flop + F 与 V 混淆）→ 不可辨识，不得当估计结果写。
- **数据集 ID = 化合物**，eta 是化合物间变异不是 IIV（实测 eta_cl 收缩 −427%）。
- **PK-Sim 仿真层往返**：`snap -p` 退出码 0 + 日志 "Project saved" 但 `Simulations` 恒 0
  （官方 Midazolam 快照 37 条裁到 1 条仍丢；已排除 `ParameterIdentifications` 空引用与
  `ObservedData`）。**结论：PK-Sim 会静默丢内容，验收必须看产物计数**。
  - **2026-11-18 勘误（第一手复测，见 logs/peer_review_20261117/pkpd_diagnosis.md）**：
    上条归因有误。① 本 skill 快照 `Simulations` 恒空是因为 `pk_sim_snapshot()` 从未构造它，
    非 CLI 丢弃；    ② CLI **支持**仿真往返——官方快照完整往返后 `.pksim5` 的 `SIMULATIONS` 表实测=37
    （ObservedData=115/Protocols=33 全保留），裁成 1 条且保留引用 ObservedData 时=1；
    ③ 清空引用 ObservedData 则报 `Cannot load Simulation`
    但退出码仍 0。"已排除 ObservedData"不成立。验收看产物计数的结论保留。
- **MoBi 无 CLI**：只能打开 `4-Hydroxy-Diclofenac.pkml` 人工确认。

## v4.20（2026-11-04）——无 API 工具的通用回填通道

一句话：**截图里一半工具没有可编程接口，写爬虫既不合法也不稳；把"人工跑 → 回填"从一次性脚本升级成契约。**

### 新增
- `adt/readback.py` + `references/readback_schemas.yaml`：`adt.cli readback`
  - 结构对齐：用 SMILES（RDKit 规范化）或 InChIKey 与 `compounds.csv` 匹配，**不符进 `unmatched` 报表**
    （不按名字硬配，不用相似度猜——铁律 1）
  - 未映射列**逐列报出**（不静默丢：少一半端点必须有人知道）
  - 类标映射（Yes/No/High/Low → 1/0）走 schema 的 `class_tokens`
  - `measured` **必须**带显式 `--provenance-url`（工具主页不算引文；否则自动降级 `manual` 并留 note）
  - `--map "源列名=端点id:单位"` 是唯一允许的临时映射方式（**不做列名模糊匹配**）
- 已登记回填源：`swissadme`（完整映射）、`aoamp` / `graphpka` / `cardiosafe` / `cardiosim_tox` /
  `herbtoxnet` / `kan_prospect`（`endpoints: {}`，列名未实测，必须 `--map`）、
  `microbetcm` / `gutbugdb` / `masi`（数据库注解，`domain_flag=manual`）

### 实测
- SwissADME：`GET /` 200（42909 B）；`GET /index.php` **403**（bot 防护）→ 自动化不可行，只能回填
- 用假导出表跑通：3 行 → 12 长表行 / 2 分子；1 行结构不符被丢弃并报出；1 个未映射列被报出；
  Terfenadine `Pgp substrate=Yes`（与已知药理一致，作 sanity check）

### 修复（全量批跑现场抓出，**本模块自己开了一个信任根漏洞**）
- **`readback` 曾可写任意 `domain_flag`**：C2 白名单审计报出两处未登记写入点
  （`readback.py:ingest`、`cli.py:cmd_readback`）。这不只是"忘了登记"——
  `out_of_domain` / `saturated` / `error` 三个取值改变的是**可判性**与**是否入票**，
  若允许回填表或 schema 自行声明，**任何人只要在 CSV 里写一列就能把分子踢出裁决**。
  → 新增 `readback.BACKFILL_FLAGS = (predicted, measured, manual)` 并做硬校验；
  两处写入点按"逐点理由"登记进 `flag_audit.WHITELIST`；补 4 例成对断言
  （3 个禁用取值各抛一次 + 白名单恰好三项）。
- **`tests/test_smoke_pytest.py` 元测试第二次抓漏**：`test_efflux_heuristic.py` /
  `test_uptake_heuristic.py` 自 v4.12 起就有测试文件但**从未登记**，
  `pytest tests/` 一直没执行过它们 → 一并登记（连同本轮 `test_extension_v414.py`）。
- 顺带纠正一个**误判**：上一轮把"全量 `pytest tests/` 迟迟不返回"当成"既有 TDC 网络测试挂起"。
  实测全量批跑**能跑完，耗时约 10 分钟**（smoke 元测试对每个脚本既要 `python <script>` 跑一遍、
  又要 `pytest` 收集跑一遍，索引 60+ 文件）。**"慢"被误读成"挂"** —— 这正是不该用间接信号下结论的例子。
  终态：`pytest tests/` **89 passed / 8m23s**（rc=0），`release-check` **PASS**。

---

## v4.19（2026-11-04）——肠道菌群代谢子模块：biosystem 过滤 + 反应标注一致性 QC

一句话：**"菌群代谢"这一块以前只有 `bt --option`；实测发现两个必须硬拦的坑——`reaction_type` 是规则名会串底物类，且同一次 HGUT 查询会混入 `biosystem=Human`。**

### 新增
- `adt/gut_microbiome.py`：`adt.cli gut-micro`
  - `HGUT`（Human Gut Microbial）选项；option 枚举从站点 `<option value>` 实取（12 个，见 `VALID_OPTIONS`）
  - **biosystem 过滤**（`filter_biosystem`）：只保留 gut 来源转化
  - **反应标注一致性 QC**（`reaction_label_check`）：8 类常见转化的质量差规则
    （脱羧必须 −44、羟化必须 +16、葡糖醛酸化必须 +176 …）；不符标 `label_inconsistent`
  - **阳性对照闸门**：APAP → 期望 3 个唯一代谢物（`POSITIVE_CONTROL`，2026-11-04 实测）；
    对照不达期望则整批只作背景，不得跨批比较
  - **0 产物 → `out_of_domain`**（沿用 registry 硬规则，不是"无代谢"）
  - `--dump-raw` 落原始 JSON（`bt_raw_<cid>.json`）：标注一致性结论必须可回看

### 实测（这是本轮最重要的一条负面发现）
- APAP + HGUT → **3** 个唯一代谢物（对照 PASS）；quercetin + HGUT → **7** 个
- **7/7 条 `reaction_type` 与质量差矛盾**：
  - 4 个葡糖醛酸苷（Δm=+176.03）被标 `Decarboxylation of aromatic L-amino acid`
  - 2 条被标 `2-Hydroxylation of 1,4-disubstituted benzene` 而产物**少一个 O**（Δm=−15.99，方向相反）
  - 另 1 条标 `2-Acetyl hydrolysis of ...glycerol-3-phosphocholine`（底物是槲皮素，与该规则无关）
- 同一次 HGUT 查询里出现一条 `biosystem="Human"`（儿茶酚 O-甲基化）→ **不过滤就会把人体代谢算成菌群代谢**
- 结论写进 SKILL 判据表：**只可引用 `metabolite_smiles/inchikey`，`reaction_type/enzymes` 不得引用**

---

## v4.18（2026-11-04）——外部 PK/PD 工具互操作桥（PK-Sim / NONMEM / nlmixr2）

一句话：**PK-Sim 是 .NET 桌面、nlmixr2 是 R 包——本 skill 不该重写它们；缺的是参数与数据能无损进出。**

### 新增
- `adt/interop.py`：`adt.cli interop --what pk-sim|nonmem|all`
  - `pk_sim_compounds()`：MW / logP / 化合物类型（neutral/acid/base/ampholyte/zwitterion）/ pKa 列表 /
    fu / 溶解度 / Caco-2 / fu_mic / CLint / CLr → PK-Sim 化合物参数表；
    **未映射的参数显式列出**（`PKSIM_FIELDS` 里没有本 skill 来源的项），**不静默丢**
  - `nonmem_dataset()` + `validate_nonmem()`：ID/TIME/AMT/EVID/CMT/DV/MDV/RATE/II/ADDL/SS/DVID，
    校验 5 类会让 NONMEM 静默算错的约定（EVID=1 但 AMT=0、观测行 MDV=0、观测行带 AMT、
    给 II 却 ADDL=0、键重复、TIME 未排序、无给药记录）
  - `nlmixr2_skeleton()`：1 房口服 + 加性误差的 R 脚本，标 `template_only`

### 实测
- 6 个化合物参数表：Diclofenac 正确判 `ampholyte`（有 COOH + 芳香胺），Digoxin `neutral`，
  Quercetin pKa 去重为单个 10.0（5 个酚羟基在类别模型下同值，**去重避免 PK-Sim 重复计电离**）
- 2005 行数据集契约校验通过；nlmixr2 骨架生成成功
- ⚠ **三款工具本机均未安装**，全部产物标 `validated_against_tool=False`

---

## v4.17（2026-11-04）——PBPK 资格认定：把"会算"升级为"能用"

一句话：**没有资格认定，PBPK 只是会算数的模型；此前只有三项自校验（质量守恒/稳健性/MC 收敛），那保证"算得对"、不保证"算得准"。**

### 新增
- `adt/pbpk_qualify.py`：`adt.cli pbpk-qualify`
  - 指标：fold error、AFE（方向性）、AAFE（无方向）、%2fold、%3fold、rmse(log10)
  - 三条**拒绝**条件：配对数 <5；**每化合物时点数 <2**（只对 Cmax 的比对不构成资格认定）；
    观测与预测单位不一致（直接抛错，不出数）
  - 判定：`qualified_conventional` / `not_qualified` / `insufficient_n` / `insufficient_timepoints`
  - 阈值**明标 `convention`**：EMA 2018 要求报 fold error 但**未规定通过线**；2 倍/80% 是工业界工作点

### 实测（两条路径都跑到）
- 5 化合物 × 1 时点 → `insufficient_timepoints`（拦住"只比 Cmax"的常见误用）
- 5 化合物 × 8 时点 = 40 配对 → `qualified_conventional`（AFE 0.99、AAFE 1.20、2 倍内 98%）

---

## v4.16（2026-11-04）——PK/PD 连接层：从"峰值"到"时间"

一句话：**此前的暴露侧只有 `Margin = IC50/Cmax`，三个结构性缺陷：只用峰值、没有时间维度、没有效应室滞后。**

### 新增
- `adt/pd_link.py`：`adt.cli pd`
  - Hill/Emax 直接效应；效应室 `dCe/dt = ke0(C−Ce)`（梯形离散）
  - `time_above()`：阈值穿越时刻**线性插值**（不在采样点上截断），给绝对时长 + 占时间跨度比例
  - `pd_metrics()`：`fT>EC50`、`fT>EC90`、效应 AUC、峰效应、达峰时间、平台判定
  - `tmdd_minimal()`：R0/kon/koff/kint/kdeg **缺一即抛 `PDParameterError`**，不许默认值凑
  - `c_mg_per_L_to_uM()`：**量纲不一致直接抛错**（C71 教训：log 值与线性阈值混用会恒判 FAIL）
- `adt/cli.py pbpk --dump-curves`：落 `pbpk_curves.csv`（compound_id, t_h, c_mg_per_L），供 `pd` 消费

### 实测
- `pbpk --dump-curves` → 2001 行 C(t)（5 个分子，240 h 视野）
- `pd --ec50 0.5 --hill-n 1.2 --dosing-interval 12`：fT>EC50 0–105 h；2/5 个分子在 12 h 间隔内
  ≥50% 时间高于 EC50；峰效应 17–69% Emax
- 输出的 `qualification_statement` 明确写"不是疗效/毒性预测；`fT>EC90` 是反算值不是独立信息"

---

## v4.15（2026-11-04）——心脏离子通道三联：hERG 单通道不能下结论

一句话：**缺口不是"不够准"而是"方向都可能反"**——Cav1.2 阻断会抵消 hERG 的 APD 延长，Nav1.5 晚电流是另一条通路；而三个计算源**一个都不给** Cav1.2/Nav1.5。

### 新增
- `adt/cardiac_panel.py`：`adt.cli cardiac`
  - 三通道（hERG / Cav1.2 / Nav1.5）× 两种证据形式（IC50 → 裕度；%抑制@Cmax）
  - 裕度分档 <10 HIGH / 10–30 INTERMEDIATE / ≥30 LOW（Redfern 2003 惯例，**非法规线**）
  - **覆盖率闸门**：无数据 → `undetermined_no_channel_data`；缺 hERG → `undetermined_missing_herg`；
    只有 hERG → `herg_only_<tier>` 且 `allowed_statement` 硬写"**不能**据此排除多通道风险"
  - 三通道齐备也只给"通道级最高风险 + 缺口 + 下一步实验"，`net_effect=not_estimated`
  - **不输出概率**（无 ORd 即无净效应，概率化会掩盖这一点）
- 新增 6 个端点（`cardiac_herg_ic50` / `cardiac_cav12_ic50` / `cardiac_nav15_ic50` /
  `cardiac_herg_inh_pct` / `cardiac_cav12_inh_pct` / `cardiac_nav15_inh_pct`），全部 `role: reference`

### 实测
- Terfenadine（hERG IC50 0.06 µM，Cmax,u 0.097 µM）→ margin 0.62 → `panel_high`
- Quercetin / Digoxin（只有 hERG）→ `herg_only_low`，且措辞禁止"已排除"
- Diclofenac（只有 %抑制 45）→ `herg_only_intermediate`，margin 留空（不伪造 IC50）

---

## v4.14（2026-11-04）——pKa / 电离状态层：把"本机没有可靠 pKa 源"补成带区间的估计

一句话：**Gate 0.5 一直按 SMARTS 猜电荷、不看 pH；而 pH 7.4 带不带电决定渗透、转运体底物类型与 logD 与 logP 的差。**

### 新增
- `adt/ionization.py`：`adt.cli pka`
  - 11 类可电离基团（羧酸/磷酸/磺酰胺/四唑/酚/胍/脒/苯胺/吡啶/咪唑/脂肪胺）SMARTS + **类别级文献 pKa 区间**
  - 同一原子只归属一个基团（按 priority，避免酚羟基重复计入）
  - Henderson–Hasselbalch → 电离分数**区间**、净电荷**区间**、`charge_class`、`zwitterion`
  - logD 位移：`logD = logP − Σ log10(1+10^δ)`（扩展 HH），同样给区间
  - `bracket_straddles_ph`：某基团区间两端跨过"电离与否"分界时提示需实测
  - `pka_grade = "literature_category_range"` 随值输出；`limits_statement()` 写死禁用方式

### 实测（14 个真实分子 + 8 个探针）
- 正确：阿司匹林/咖啡酸 → `ionized_dominant` 净电荷 −1；苄胺 → +1；甘氨酸/阿莫西林 → **两性离子**；
  葡萄糖/咖啡因 → 中性（咖啡因嘌呤环 N 高估碱性约 5 log，但结论仍为中性，已写进 limits）
- 修 bug：初版吡啶 SMARTS 写成 5 元环（`[c,n]×4`），导致吡啶命中不了、咪唑反被判成吡啶 →
  分开为 6 元环（5 个 `[c,n]`）与 5 元环（4 个 `[c,n]`）两条模式

---

## v4.13（2026-11-04）——全量可达性审计：把「写了但没人调」的东西接上线

一句话：**用户要求"新增模块全部实跑一遍 + 排查一次也没被调用过的功能"。审计结论是：模块级 0 孤儿，但函数级抓到 2 个真死代码（1 个接线、1 个删除），另有 1 个 CLI 入口缺失让文档承诺成了空话。**

### 审计方法（可复现）
1. **模块级引用图**：对 `adt/*.py` 逐个检查「绝对导入 `adt.X`」「`from adt.X import`」「`from .X import`」
   「`from . import X`」四种形式。前三轮扫描分别漏了后两种，导致 `defaults`/`threshold_audit`/`conformal_scale`
   **被误判为孤儿**——它们是在函数体内 `from . import X as Y` 引入的。
   **结论：正则审计会误报，AST 才是准绳。**
2. **函数级**：用 `vulture`（AST）复核，60% 置信度报 37 个函数 + 4 个"未使用变量"。
   逐个回查全仓库引用后：**绝大多数其实活着**（测试直接调用、内部调用、注册表/配置字符串引用）；
   4 个"未使用变量"实为**未使用函数参数**（无害，其一带 `deprecated` 注释）。
3. **真死代码**（全仓库除定义处零引用）：
   - `adt/transfer.py:decided_accuracy` —— 模块 docstring 写着"可选：有实测真值时算"，
     但 `transfer` 子命令**从未暴露 `--truth`**，函数不可达 → **接线**（见下）。
   - `adt/adapters/biotransformer.py:BioTransformerAdapter.batch_drift` —— 与
     `adapters/base.py:91` 的 `meta["batch_drift"]` 机制重复，从未被调用 → **删除**。
4. **CLI 覆盖漏洞**：`tests/test_help_all.py` 的 `CMDS` 是手写清单，实际只覆盖 **41/60** 个子命令，
   24 个从未做过 `--help` 冒烟（而该文件开头的 argparse `%` 崩溃缺陷恰好只在 `--help` 暴露）→ **改为自动发现**。

### 改动
- **新增 `adt/cli.py source-admit`（别名 `sadmit`）**：F1 源注册门（CI 化）的**真实执行入口**。
  `adt.stats_ci.registration_gate` 与 `gate_pass_probability` 此前已实现且有单测，但**没有任何管线步骤调用**
  （SKILL.md 判据表 §F1 的措辞是"应做"规范而非"已执行"）——典型文档-代码漂移。
  - 输入：`--results CSV`（必需列 `source,n,observed_failures`），`--tol`（默认 0.05）、`--alpha`（默认 0.05）
  - 输出：`source_admission.json`，每源携带 `n / observed_rate / ci_lower / ci_upper / passes / decision / disclosure_required`
  - **语义守则**：判据是 **CP95 CI 上界 ≤ tol**，不是点估计。不通过 ≠ 源不可用——小源 CI 宽，
    标 `decision="admit_with_ci_flag"` + `disclosure_required=true`（带 CI 标注进入并声明构成偏差），
    不做二值拒绝。`--design-p` 额外输出各 n 下的通过概率曲线。
  - 实测（真失败率 3% 的设计曲线）：n=100 → 0.0476、n=200 → 0.1472、n=1000 → 0.8838，
    与 `STATISTICAL_POLICY.md §1.1` 的"n≳60 才勉强、n=500 才 56.8%"一致。
- **`transfer` 新增 `--truth`**：给了才计算 `decided_accuracy`，不给则显式输出
  `decided_acc=not_evaluated(未给 --truth)`（**不许把"没测"伪装成"测了"**）。
  `--truth` 里没有任何 PASS/FAIL 真值类时 fail-fast，不静默返回 None。
  真实数据实跑（`run6/merged/measurements_merged.csv` 四源 vs `run6/admetlab3`，真值 `run6/truth.csv`）：
  `four_source pairs=156 弃权率=0.378 域外触发率=0.583 decided_acc=1.0 (n_decided=4)`；
  `al3_only` 因 `require_sources=2` 全部弃权 → `decided_acc=None (n_decided=0)`（正确：无可判即不可评）。
- **删除 `biotransformer.batch_drift()`**（死代码，机制由 `pre_batch` + `adapters/base.py` 承担；
  `tests/test_batch_anchor.py` 只断言 `meta["batch_drift"]` 键，不受影响）。
- **`adt/stats_ci.py:gate_pass_probability`** 返回值 `float()` 化（此前 `prob` 累加 scipy 的
  `np.float64`，`round()` 不会降级，导致打印出 `np.float64(0.0476)`）。
- **`tests/test_help_all.py`**：`CMDS` 改为「静态清单 ∪ 从 `adt/cli.py` 源码抓取 `add_parser("x")`」，
  覆盖 41/60 → **60/60**（实测 65 个入口含别名全部 PASS）。
- **`tests/test_transfer.py`** 新增 3 例：`decided_accuracy` 语义（无可判必须 None，不得伪装 0.0/1.0）、
  CLI 必须暴露 `--truth`、`source-admit` 端到端（`n=100,obs=1` 判 `passes=False` 且
  `decision="admit_with_ci_flag"`；`n=1000,obs=10` 判 `passes=True`）。
- **文档错误引用修正**：`REFERENCES/COMMUNITY_BENCHMARK_ROADMAP.md` 写的是
  `SOURCE_REGISTRATION_POLICY.yaml`，实际文件是 `.md`——已改正并补上执行入口命令。
- **`run_b2_coverage.py` 补 argparse + 可核对 JSON 产物**：该脚本此前**只打印、不落盘**，
  因此`tests/test_experiment_scripts.py` 的 L1「`run_*.py` 必须登记」一直红着
  （`run_b2_coverage.py 未登记`）——**它从 2026-11-03 被写出来起就从未入网**。
  现加 `--test-csv/--priors/--out`，默认产 `out_ext/tdc/b2_coverage.json`
  （含 chemotype 命中数、分子级/转运体级覆盖度、caveat），并：
  - 登记进 `tests/test_experiment_scripts.py` REGISTRY（`core=True`，L2 `--help` 无副作用 + L3 产物存在）；
  - 登记进 `CLAIMS_REGISTRY.yaml` 的 `b2_transporter_coverage` 条（expect 逐字核对 `0.0714/0.0197/OATP2B1/n_implemented`）→ **G10 26/26 → 27/27**。
  - 顺带改正 `B2_transporter_coverage.md` 里写错的列名（文档写 `Drug(SMILES)`，实为 `Drug`）。

### 实跑清单（全部真实执行，非 pytest 代劳）
| 对象 | 命令 | 结果 |
|---|---|---|
| `run_gate_audit.py` ×3 端点 | `--endpoint hERG/DILI/BBB_Martins --dump-scores` | 三端点全部跑通，四态 verdict 正确（hERG `uninformative_unconfirmed`，CI [0.456,0.701]） |
| `run_gate_multiplicity.py` | 直接运行 | Holm 校正后 m=3 无一项显著（DILI 0.0801） |
| `run_gate_metrics.py` | 直接运行 | 校准/Brier/MCC/DCA/EF 全部出数；DILI EF 全钉在上限 1.92（再证饱和不可解读） |
| `run_b2_coverage.py` | 直接运行 | 转运体级 1/18、分子级 ≤7.1% |
| `efflux_heuristic` / `uptake_heuristic` | 逐分子探针（verapamil / glucose / L-DOPA / estrone-3-sulfate / raffinose / 非法 SMILES） | 分档符合文献预期，非法 SMILES 优雅失败 |
| `stats_ci.holm` | 三端点 p 值 | `_z(0.05/3)=2.394`（确认伪校正已修） |
| `bbb.apply_dual_layer` | 带 SMILES 的 rec | 外排+摄取启发式写入，verdict 不被改写 |
| `cli transfer --truth` | 真实 OpenADMET/run6 数据 | `decided_acc=1.0 (n_decided=4)` |
| `cli source-admit` | 4 源模拟验证结果 | CI 判定 + 设计曲线正确 |

### 未做（如实登记）
- `gate_pass_probability` 的 n_grid 未含 500，故 `STATISTICAL_POLICY.md` 里"n=500 → 56.8%"这个数
  目前只能由函数外推得证，未在默认格里直接可见（数据一致，非矛盾）。
- 全量 `pytest tests/` 仍有**既有**网络下载类测试挂起（TDC），与本次改动无关；本次用相关子集 + 逐项实跑替代。

## v4.12（2026-11-03）——B2 续·再：补上 OATP1A2 / LAT1 / GLUT1 摄取通道启发式 moiety 骨架

一句话：**按用户授权，把"摄取通道"也从纯叙事升级为"有结构依据的待验证假设"——OATP1A2 大体积有机阴离子 / LAT1 大中性 L-氨基酸 / GLUT1 仅游离单糖 的共识药效团启发式，强制绑定过表达细胞摄取 ± 竞争抑制剂验证。**

### 改动
- 新增 `adt/uptake_heuristic.py`：`oatp1a2_lat1_glut1_uptake_heuristic(smiles)` 用共识药效团近似评估
  OATP1A2（大体积有机阴离子，Hagenbuch 2004 / König 综述，estrone-3-sulfate 探针）、
  LAT1（大中性 L-氨基酸，Kanai 1998；α-氨基 + α-羧基 + 大疏水侧链，碳数≥6 或芳香侧链，甘/丙氨酸强制降级）、
  GLUT1（仅游离单糖，Mueckler 1994；完整糖苷经分子量阈值判为 excluded）底物 plausibility。
- `adt/bbb.py`：`apply_dual_layer` 在提供 `smiles` 时**同时**运行外排与摄取启发式，分别写入
  `rec["efflux_heuristic"]` 与 `rec["uptake_heuristic"]` 及 action 的"外排/摄取启发式命中"段；
  `postprocess` 自动从 `rec.get("smiles")` 透传（向后兼容：无 smiles 仍纯叙事，不变量不变）。
- `transporter_priors.yaml` 新增 `uptake_heuristics` 块（人类可读副本，明确标注启发式/非实测/强制验证/不得计票；
  SGLT1 因 BBB 内皮无功能性表达、属肠侧 Fa 通道，**不含结构规则**）。
- 同步更新 docstring 机制落点说明、`B2_transporter_coverage.md` §6/§7、红黑榜 B2 段。

### 严格纪律（防过度声称）
- 摄取启发式与外排启发式同纪：均**不得**进 reliab 计票、**不得**改 verdict/confidence；
  所有命中必须经 MDCK/HEK-OATP1A2 / HEK-LAT1 / 原代 BBB 内皮（GLUT1）± 竞争抑制剂验证后方可下结论。
- 这是"框架级→待验证假设"的升级，**不是**量化级；仍不得给人"摄取通道已被本 skill 量化"的印象。
- 量化级需对 P-gp/BCRP/OATP1A2/LAT1 做实验回填端点（role=reference）。

### 验证
- 新增 `tests/test_uptake_heuristic.py`（13 例）：游离葡萄糖→GLUT1 medium、L-DOPA→LAT1 medium + OATP low_to_medium、
  estrone-3-sulfate→OATP1A2 medium、完整糖苷→GLUT1 excluded、甘氨酸→LAT1 降级、非法 SMILES 优雅失败、bbb 集成（带/不带 smiles、postprocess 透传）。
- 相关子集（`test_uptake_heuristic` + `test_efflux_heuristic` + `test_bbb_dual_layer` + `test_bbb_three_channel` 等 11 文件）= **41/41 全绿**。

## v4.11（2026-11-03）——B2 续：补上 P-gp / BCRP 外排通道启发式 moiety 骨架

一句话：**按用户授权，把"外排通道"从纯叙事升级为"有结构依据的待验证假设"——P-gp 共识药效团启发式，强制绑定 Caco-2 ± verapamil/elacridar 验证。**

### 改动
- 新增 `adt/efflux_heuristic.py`：`pgp_bcrp_efflux_heuristic(smiles)` 用 P-gp 共识药效团
  （Seelig 1998 HBA 距离模型 + Penzotti/Crivori 2002/2006 ADMET Predictor 药效团）近似评估
  P-gp / BCRP 底物 plausibility（low / low_to_medium / medium）。
- `adt/bbb.py`：`apply_dual_layer(rec, smiles=None)` 新增可选 `smiles`；提供时运行启发式并把结果
  写入 `rec["efflux_heuristic"]` 与 action 的"外排启发式命中"段；`postprocess` 自动从 `rec.get("smiles")`
  透传（向后兼容：无 smiles 仍纯叙事）。
- `transporter_priors.yaml` 新增 `efflux_heuristics` 块（人类可读副本，明确标注启发式/非实测/强制验证/不得计票）。

### 严格纪律（防过度声称）
- 启发式**不得**进 reliab 计票、**不得**改 verdict/confidence；所有命中必须经
  Caco-2 双向 ± verapamil 100 µM（P-gp）/ ± elacridar 2 µM（BCRP）验证后方可下结论。
- 这是"框架级→待验证假设"的升级，**不是**量化级；仍不得给人"P-gp/BCRP 已被本 skill 量化"的印象。
- 摄取通道（GLUT1/SGLT1/OATP1A2/LAT1）仍仅叙事、无 moiety 规则——这是剩余真缺口。

### 验证
- 新增 `tests/test_efflux_heuristic.py`（7 例）：verapamil→medium、raffinose→low_to_medium、
  pentane→low/uncertain、非法 SMILES 优雅失败、bbb 集成（带/不带 smiles、postprocess 透传）。
- 与既有 `test_bbb_dual_layer.py` / `test_bbb_three_channel.py` 同跑全绿（18/18）。

## v4.10（2026-11-03）——B2 闭环：BBB 转运体先验覆盖度量化（黑榜 B2 / O5-D2）

一句话：**用 `run_b2_coverage.py` 对 406 个 BBB_Martins SMILES 实跑，把"覆盖度"从疑点变成数字。**

### 量化结果
- 转运体级覆盖率 **1/18**：canonical 人类 BBB 转运体集合（KEGG BRITE 02000 + UniProt 锚定：ABCB1/ABCG2/SLCO1A2/SLC2A1/SLC7A5/SLC29A1 等均核实为真实条目）；本 skill 仅 OATP2B1 有 moiety 规则，且为黄酮类专属骨架。
- 分子级覆盖率 **≤7.1%**（保守上限：分母取 TPSA>140 的 28/406 转运体主导分子，OATP2B1 代理仅 2 例含糖；按机制相关集 ~全 406 计趋近 0）。
- 405/406 的 CNS 分子不命中任何黄酮 chemotype → 现有先验对这套数据**化学性失明**。

### 结论与动作
- `adt/bbb.py` 的"被动 × 外排(P-gp/BCRP) × 摄取(GLUT1/SGLT1/OATP2B1)"三通道决议：**仅被动层 + 一层近乎休眠的 OATP2B1(黄酮) 层真正可执行**；P-gp/BCRP/GLUT1/SGLT1/OATP1A2/LAT1 仅叙事、无 moiety 规则。
- "BBB 双层机制"表述应降级为"仅覆盖 OATP2B1 分支（黄酮专属，对 CNS 集几乎不触发）"，待补 P-gp/BCRP/OATP1A2/LAT1/GLUT1 的 moiety 规则或实验回填。
- 数据来源 `out_ext/tdc_cache/admet_group/bbb_martins/test.csv` 本机已缓存，无需外网（原以为要 fetch，省了）；分母权威源 KEGG BRITE / UniProt 实测可达。
- 产物：`references/B2_transporter_coverage.md`、`run_b2_coverage.py`；红黑榜 B2 / 台账 O5-D2 状态更新为已量化。

## v4.9（2026-11-03）——B3 闭环：Clark 2014 原文核对，修正"过度更正"的归属

一句话：**查了原文，发现上一轮把 Clark 2014 判成"纯 laundering / 仅启发来源"是过度更正。**

### 核实结果（Clark RD et al., J Cheminform 2014;6:34, doi:10.1186/1758-2946-6-34，Open Access）
- 协议第 7 步原文：*"add 1 to each prediction tally and adding 0.5 to each error count"*
  = 本包的 `(err+0.5)/(n+1)`。Clark 2014 确实在 ADMET/QSAR 投票不确定性语境下用了这个修正。
- 但其 headline 方法是 beta-binomial 拟合 `u(k)=ER·f(k)/g(k)`，本包**未实现**。

### 修正后的精确归属
- 公式**起源**：Jeffreys（1946）/ Agresti & Coull（1998）伪计数平滑（Laplace 连续性修正先例）。
- **Clark 2014 = 合法次级引用**（已查原文 PDF 核实），不再是"仅启发来源 / laundering"。
- 但**不得声称"实现了 Clark 2014 方法"**——那才是真正的引用 laundering。
- 受影响文件：`adt/independence.py`（docstring + 两处注释）、`08_literature_map.md`、`09_reliability_landscape.md`、`REVIEW_2026-11-03_RED_BLACK.md`(B3)、`REVIEW_2026-11-03_LEDGER.md`(O5/D1)。
- 红黑榜"黑榜仍需外部输入"三项（B1/B2/B3）中，B3  hereby 关闭；剩余 B1（外部效度）、B2（转运体先验覆盖度）。

## v4.8（2026-11-03）——两件比补字段更要紧的事：多重比较，和"一直亮着但没通电"的测试绿灯

一句话：**这一版没有新功能，只有两处"我们一直在说的东西其实不成立"。**

### 一、多重比较（`adt/stats_ci.holm` + `run_gate_multiplicity.py`）

材料里有一句话："门在某些端点上有效。"一旦用了"**某些**"，检验就不再是单次检验，
而是"3 次里挑最好的一次报出来"。此前材料只报 DILI 的 Fisher p=0.0267，从未提过
另外两次也测了。

新增 `stats_ci.holm(pvals, alpha)`（Holm–Bonferroni 逐步法），并新增
`run_gate_multiplicity.py` 产出 `out_ext/tdc/gate_multiplicity.json`：

| 端点 | n | gate AUC [95%CI] | Fisher p | **Holm p** | 差值 95%CI | 族内 98.3%CI |
|---|---|---|---|---|---|---|
| hERG | 132 | 0.580 [0.456, 0.701] | 1.0000 | 1.0000 | +0.001 [−0.148, +0.126] | 跨 0 |
| DILI | 96 | 0.669 [0.543, 0.793] | 0.0267 | **0.0801** | −0.193 [−0.321, −0.030] | **[−0.349, +0.014] 跨 0** |
| BBB_Martins | 406 | 0.514 [0.440, 0.595] | 0.7554 | 1.0000 | +0.011 [−0.054, +0.072] | 跨 0 |

**结论**：m=3、familywise alpha=0.0167 之后，**没有任何一项达到显著**。
DILI 的 0.0267 → 0.0801，族内 98.3%CI 也从"不含 0"变成"含 0"。

因此"PASSTHRU 在 DILI 上有据"这句话**只允许在单端点口径下写**，并且必须
在同一段里声明：跨端点归纳时该结论不成立。已在 `GATE_AND_P8_MMP_v4.2.md` 同步。

顺带修掉 `stats_ci._z` 的一个静默 bug：原来是 4 值查表 + `table.get(..., 1.96)` 兜底，
于是 alpha=0.05/3 **静默退回 1.96**，算出与 95% 一模一样的"校正后区间"——
一个本该更宽的区间只是看起来没变，等于在校正声明上撒谎。改为标准库正态分位数。

### 二、测试绿灯"一直亮着但没通电"（`tests/test_smoke_pytest.py`）

`test_smoke_pytest.py` 用 `python <script>` 逐个跑测试文件。对**函数式**文件
（只有 `def test_xxx()`、没有模块级断言）来说这是**空跑**：进程 rc=0，
**一条测试都没执行**，而汇总里算它"通过"。

实测证据：`tests/test_experiment_scripts.py` 自称 44 例，在本版之前
**一例都没跑过**。它一被真跑，立刻抓出 3 个失败：

1. `run_gate_multiplicity.py` 未登记（元测试本身生效）；
2. `run_gate_audit.py --dump-scores` 的 `help` 里写了 `95% CI`，argparse 格式化时
   抛 `ValueError: unsupported format character 'C'` → **`--help` 直接崩**；
3. `test_every_script_has_help_guard_or_argparse` 把 `any(a in ("-h","--help"))`
   误判成"无守卫"（静态记号只认变量名 `_a`）——检查太字面，自己是假阳性来源。

修法：`test_script_passes` 在 `python <script>` 之后再跑一遍
`pytest <script>`（文件含 `def test_` 时），并断言不许出现 `no tests ran`；
自身排除避免递归；对偶发的 rdkit access violation（0xC0000005，解释器退出阶段）
允许重试一次，重试仍失败判负。

**规模对比（这才是真实覆盖度）**：

| 指标 | 本版之前 | 本版之后 |
|---|---|---|
| 实际执行的测试文件 | 48（脚本式） | **86（全部）** |
| 函数式测试文件是否真跑 | ❌ 空跑 | ✅ |
| `def test_` 函数实际执行数 | 0 | **253** |
| `assert` 语句（静态计数） | — | 721 |

**"86 passed" 这个数字本版之前含义是"86 个文件各返回 0"，现在是"86 个文件
真的跑了里面的东西"。** 这正是本轮评审开头批评的"声明式 vs 执行式"在测试层的重演。

### 三、门禁

- `release-check` PASS（G1–G12，G10 **23/23**）。
- `pytest tests/` 全绿（在**新判据**下，即函数式文件真的执行）。

---

## v4.7（2026-11-03）——P2.4-b：gate 判别力的 95% CI，以及由此暴露的一处反向过度声称

一句话：**补齐区间之后，材料里一句"已证明门没用"必须撤回，改成"未证明门有用"。**

### 一、新增能力

- `run_gate_audit.py --dump-scores <csv>`：落盘逐分子
  `(idx, y_true, model_prob, model_pred, model_correct, sim, gate_passed)`。
  没有这一列就没法做 bootstrap——这是"红线 7 要求 CI"能否落地的前提。
- 三个 AUC 口径**分开命名**并各带 95% CI（percentile bootstrap，2000 次，固定种子）：

  | 口径 | label | 分数 | hERG 实测 |
  |---|---|---|---|
  | `gate_as_predictability` | 模型这条是否预测正确 | `sim` | **0.5800 [0.4561, 0.7008]** |
  | `sim_as_label_baseline` | 真值 | `sim` | 0.6857 [0.5854, 0.7784] |
  | `model_auc` | 真值 | `model_prob` | 0.7916 [0.6893, 0.8836] |

- 估计量**双实现**交叉核对：`roc_pr` 梯形积分 0.580 vs Mann-Whitney 秩和 0.5800
  → 差 2×10⁻⁵，证明 0.580 不是 ROC 离散化/平局处理的伪影。核对结果写进产物
  `auc_ci.estimator_check`。
- `forced_prediction_test` 补差值区间（Newcombe）。hERG：差值 0.0005，
  95%CI **[−0.1482, 0.1257]**，跨 0 且宽 → 该比较**功效不足**。

### 二、判定逻辑升级（`adt/gate_audit.py`）

- `discriminative_power(..., auc_ci=)` 新增四态 `verdict_ci`：
  `informative_supported / informative_unconfirmed / uninformative_supported /
  uninformative_unconfirmed / no_ci`。`verdict` 保留点估计口径以兼容旧调用方，
  **冲突时以 `verdict_ci` 为准**。
- 无 CI 时不再输出"与随机丢弃不可区分"，只输出"未提供 95% CI，不得下结论"。

### 三、必须撤回的一句话（本版最重要）

旧材料："hERG gate AUC 0.580 < 0.65 → 与随机丢弃**在统计上不可区分**"。

补 CI 后：**[0.456, 0.701] 的上界越过 0.65**。这句话方向反了——
既没证明"有判别力"，也没证明"没有"，n=132（正确 109 / 错误 23）只够说"未证明有"。
已在 `GATE_AND_P8_MMP_v4.2.md`、`POSITIONING.md`、`gate_audit.py` 三处改口，
并把"禁止写什么"写进 `CLAIMS_REGISTRY.yaml`。

### 四、三端点结论结构变细了（不是变好看了）

| 端点 | n | gate AUC [95%CI] | AUC 判定 | 准确率差 [95%CI] |
|---|---|---|---|---|
| hERG | 132 | 0.580 [0.456, 0.701] | `uninformative_unconfirmed` | +0.001 [−0.148, 0.126] |
| DILI | 96 | 0.668 [0.543, 0.793] | `informative_unconfirmed` | **−0.193 [−0.321, −0.030]** |
| BBB_Martins | 406 | 0.514 [0.440, 0.595] | **`uninformative_supported`** | +0.011 [−0.054, 0.072] |

只有 BBB（n=406，样本最足）达成"已证明无判别力"；DILI 的"域外更差"有区间支持
但"门能排序"没被证实——**两条判据分开写，一条成立不等于另一条成立**。

### 五、顺带抓出并锁死的三处"工具自己造谣"

1. `--dump-scores` 列名 `gate_passed` 写的其实是模型预测 → 分列为 `model_pred` / `gate_passed`；
2. 第一版把 `model_auc`(0.792) 的 CI 记在 gate 名下（张冠李戴）→ 三口径分离命名；
3. `sentence_zh` 把结论写死成 hERG 叙事，导致 DILI（0.668>0.65）被生成成
   "点估计低于工作点" → 改由 `verdict_ci` 驱动 + 回归测试。

### 六、环境与门禁

- 宿主升级替换了自带 Python 的 site-packages（rdkit 2026.03.6→2026.09.1，
  pandas 2.3.3→3.1.0）。**按新栈重跑全量测试 + gate 审计**：86/86 通过，
  hERG AUC 复现 0.580、域内外准确率 0.826 与旧栈**逐位一致** → 该漂移无数值影响
  （这条比对本身即一次免费复现性验证）。`env_fingerprint.json` 已重生成，G4 由 WARN 转 OK。
- 清华 TUNA 镜像对此解释器返回 `from versions: none`、官方 PyPI 索引 7 分钟无响应；
  **华为云镜像 8.5MB/s 可用**，已写入 `requirements.txt` 注释，省掉下一个人再猜一遍。
- `release-check` PASS（G1–G12，G10 **23/23** 条主张）。

### 七、仍未解决

- P2.4-c：CI 只覆盖**评测集抽样**，不含模型训练随机性（需 nested/repeated-CV 重抽）。
- 前瞻盲测（条件②）、外部第二实现者（条件③）仍需外部资源。

---

## v4.6（2026-11-03）——外部同行评审整改（doc_revision 4.6，version 仍为 4.0-dev）

一句话：**这一版没有新增功能，全部是"把已经声称的东西变成真的"。**
起因是外部同行评审打出的七寸——红线层是**声明式**而非执行式，与本文档自己
"能不能用一条命令绕过"的判据直接矛盾。完整台账见
`references/REVIEW_2026-11-03_LEDGER.md`。

### 一、治理层（最重）

- **C1 红线接线**：新增 `adt/redlines.py`（AST 探测生产调用点 + `REDLINE-<id>` 集成测试）。
  `red_lines_status()` 从**硬编码 `ok=True`** 改为真探测；G8 改读它。
  `adt.cli report` 落盘前统一跑红线 6/7/8/9，命中即**不写 `conclusions.md`**、`exit 4`。
  `report --publish` 触发红线 3（快照重放）与红线 1（结构准入）。
  **硬度普查**：7 hard / 1 soft（R1）/ 1 conditional（R3）——禁止再写"九条全部阻断"。
- **P1.7 `domain_flag` 白名单**：`adt/flag_audit.py` 扫出 11 处写入点，逐点登记取值与理由；
  未登记写入点即测试红（外部评审 R-D 要求）。
- **C2**：`bbb.postprocess` 的裸 `except: pass` 改为留痕 + 置信度降级。

### 二、统计层

- **C3**：红线 7 判据从"点估计 vs 0.65"改为"**必须给 95% CI，且 CI 上界越过工作点**"；
  `GATE_AUC_MIN` 降级为 `GATE_AUC_WORKPOINT`（约定工作点，非判据）。
- **C4**：`u(k)=(err+0.5)/(n+1)` 的出处从"Clark 2014"更正为 **Jeffreys/Laplace 伪计数平滑**
  （Jeffreys 1946；Agresti & Coull 1998），Clark 2014 降为启发来源（8 处同步）。
- **P2.4**：新增 `stats_ci.auc_bootstrap_ci / wilson_ci / newcombe_diff_ci /
  paired_bootstrap_diff_ci`；**实算 Ames 双方法层差值 0.0915，95%CI [0.0479, 0.1345]**
  （产物 `out_ext/tdc/ames_release_ci.json`，G10 已核）。gate AUC 的 CI **仍缺**
  （无 per-sample 分数，登记为 P2.4-b）。

### 三、可复现性与测试

- **C5**：21 个 `run_*.py` 入网（`tests/test_experiment_scripts.py`，40 例）；
  5 个无 argparse 的脚本加 `--help` 早退（此前 `run_replication_pack.py --help`
  会**写出挑战包**）。
- **元测试补漏**：`SCRIPTS` 硬编码导致 **5 个测试文件从未被默认批跑**
  （含红线 7/8/9 的单元测试）。已全部登记，并加
  `test_every_test_file_is_registered` 防复发。

### 四、语义一致性

- **C7**：归因分类唯一真源 `abstain_attrib.TAXONOMY`（弃权 8 + 源可靠性 1 = 九类）。
- **C9**：单位异构投射路径新增 `projection_used` 与 `phrasing` 独立档 `projected`
  （禁止写成"中位 X"）。
- **C10**：版本三轨制（能力等级 / 材料修订 / 产物身份）。
- **C6**：U9 阈值普查新增「§B 代码常量普查」13 项 + 双向一致性测试。

### 五、对外表述（重要）

- SKILL.md 条件④ 从"可断言"改为"**在生产路径上接线**"，并写明 2026-11-03 之前该条件**不成立**。
- SKILL.md 条件② 增"排除清单"：随机切分 / 数据集固定时序切分 / post-cutoff 重组
  **均不满足②**；当前状态由"②未开始"改为"**②未满足**"。
- 新增 `references/TEMPORAL_HOLDOUT_DISCIPLINE.md`、`PREREG_ANCHORING_CHECKLIST.md`、
  `SECOND_EXTERNAL_SOURCE_SPEC.md`、`COMMUNITY_BENCHMARK_ROADMAP.md`、`ONBOARDING_10MIN.md`。

### 六、门禁与测试实测

```
pytest tests/                   → 86 passed（86 个测试文件，300+ 用例）
python -m adt.redlines          → PASS 9/9（7 hard / 1 soft / 1 conditional）
python -m adt.flag_audit        → PASS 11 处写入点
python -m adt.cli release-check → PASS G1–G12（G10 20 条主张）
python -m adt.cli prereg-status → 新增命令（exit 3 = 未锚定）
```


## v4.5（2026-11-02）——华山参 59 成分实跑暴露的 3 个数据/规则缺陷（文档留痕，不改判定语义）

一句话：**用 v4.4 管线跑完华山参 59 个真实成分后，发现 3 处"模型输出越界被当成有效值"
与"规则过判"的问题。本版把它们的量级、成因与处置口径写进文档，保证外部评审看到的
结果解读与管线实际行为一致。判定逻辑本身未改动（改动会破坏已发布的复现性），
因此这些属于"已知限制 + 显式处置"，而不是静默修数。**

### 一、ADMET-AI 的 CLint 出现负值（59 成分中 9 例，15.5%）

- 现象：`clint_microsome` 出现 −0.86 至 −85.45 µL/min/mg。微粒体清除率为负在物理上不可能。
- 成因：`measurements` 里的 CLint 来自回归端点，模型对训练域外分子可输出负值，
  **适配器未做物理边界截断**（`adt/adapters/admet_ai.py` 只对 PPBR 做了方向换算，
  未对 Clearance 做 >0 校验）。
- 后果：`adt.cli pbpk` 的 `in_phys_range_ok()` 会拒绝这类分子（华山参 13 个被跳过），
  该成分的 t½ / F / CLh 全部缺失。若下游脚本不校验，会把负值当成"极低清除=代谢稳定"，
  得到完全相反的结论。
- 处置（已实施于分析层，未改适配器）：凡是 ≤0 的 CLint 一律按缺失处理，代谢维度按
  `None` 计分。**下游任何使用 clint_microsome 的脚本都必须先做 >0 过滤。**
- 待办：适配器应在写入前加 `value <= 0 → 丢弃并写 note`，并让 source_version 记录丢弃数。

### 二、PPBR 换算后 fu% 出现负值（59 成分中 3 例）

- 现象：`ppb_fu` 出现 −14.8 / −13.7 / −10.8。
- 成因：`ppb_fu = 100 − PPBR_AZ`，当模型给出 PPBR > 100% 时 fu 转负。
- 处置：同样按缺失处理；报告与打分均不得把负 fu 当作"极高游离"。

### 三、`michael_acceptor` 规则对 α,β-不饱和**羧酸**过判

- 规则：`[CX3]=[CX3][CX3]=O`（`adt/alerts.py`），本意捕获 Michael 受体。
- 问题：该 SMARTS 同时命中肉桂酸、对香豆酸、咖啡酰奎宁酸等**羧酸**。羧酸根是弱
  Michael 受体，这类物质多为食品级 GRAS、文献 Ames 阴性。华山参数据集 16 个命中者中
  有 4 个属于此列（A-37、Hs-16、Hs-17、A-38），直接导致 Ames 判 FAIL 偏多。
- 量化影响：剔除这 4 个酸类后，Ames FAIL 由 15 降至 11。
- 处置：**不改规则**（ICH M7 下"命中即升级"是保守侧，改动需重新标定 TDC 基准）。
  在报告与文档中显式标注该过判类别，并把酸类单列为"需实验确认"而非"确认阳性"。
- 待办（v4.6 候选）：把羧酸/羧酸根从 Michael 受体规则中拆出，单独成
  `alpha_beta_unsaturated_acid`（弱规则，仅提示不判 FAIL），并以 TDC AMES 重新标定
  放行错误率，确认不劣于 0.177 后再切换。

### 四、语义澄清：vNN `MRTD` 不是"平均驻留时间"

- `MRTD` = Maximum Recommended Therapeutic Dose（最大推荐治疗剂量，mg/day），
  属剂量参照端点（`role=reference`，不参与裁决）。
- 华山参首轮汇总中曾把它当作排泄/驻留指标解读，本版明确纠正：**E（排泄）维度
  在本框架内没有实测支撑**，只能用 `clint_microsome` + `ppb_fu` 经 PBPK 推算
  t½ / CLh / F，且 fu_mic 默认 1.0（未实测）。任何报告不得把 MRTD 写成 t½ 或 MRT。

### 五、验证

- 华山参 59 成分全流程复跑：安全性裁定 236 条（通过 54 / 失败 22 / 未定 160），
  Ames 9 通过 / 15 失败 / 35 未定，与独立 `ames_ichm7` 计算 100% 一致。
- `pytest tests/` 全绿（含 v4.4 新增的 `test_ames_alerts_wired.py`）。

## v4.4（2026-11-02）——补上 Ames 专家规则层的**生产接线**（修复"文档声称≠实际行为"脱节）

一句话：**v4.3 把"补 adt/alerts.py 专家规则层、ames 升为 qualitative_only、放行错误率
0.269→0.177"写进 CHANGELOG 与 ENDPOINT_TIER_EVIDENCE，但 `reliab` 命令从未调用
alerts.py、`expert_rule_layer` 在生产流中永不被设置——ames 在真实 reliability.csv 里
仍全 UNDETERMINED。本版把这条**真实接上**，并有回归测试锁住。**

### 一、问题（外部评审反复抓到的同一类脱节）

- `run_ames_alerts.py`（TDC 基准）证明双方法有效，`adt/alerts.py` + `two_method_verdict()`
  也在；但它们是**库/基准**，不是生产管线的一部分。
- `apply_tier_policy()` 里"ames 必须启用专家规则层，否则降 UNDETERMINED"这条约束，
  在 `reliab` 里**永远命中拒绝分支**（没有代码去置 `expert_rule_layer=True`）——
  这等于给 ames 上了一把**没有钥匙的锁**。
- 结果：文档说"已升档、已补专家层"，实际跑 `reliab` 得到 0 PASS / 0 FAIL。
  这就是评审说的"已做内容与 skill 记录不一致"。

### 二、修复（真正接线，不是改措辞）

- `reliab` 新增 `--enable-alerts`（**默认开**）与 `--compounds`（指向含 `calc_smiles`
  的 compounds.csv；默认在输入同目录/cwd 自动找 `compounds.csv`）。
- 启用时：对每个 `QUALITATIVE_NEEDS_EXPERT`（当前 `ames`）端点，用化合物 SMILES 跑
  `adt/alerts.py` 结构警示扫描 → 置 `expert_rule_layer=True`、构建 `alert_cache`。
- `apply_tier_policy(recs, ..., alert_cache=...)`：当专家层满足时调用
  `two_method_verdict(统计结论, 结构警示命中, in_domain)` 做 ICH M7 双方法合成，
  并把结果写回 `verdict`，新增 `alert_hit` 列。
- `reliability.csv` 输出新增 `expert_rule_layer`、`alert_hit` 两列（审计留痕）。
- 找不到 compounds.csv 或显式 `--no-alerts` 时：打印说明，ames 等**维持 UNDETERMINED**
  （ICH M7：两法缺一不判），行为与旧版一致，不静默放行。

### 三、验证（真实跑批，非玩具数据）

- 华山参 85 成分（59 有结构）×5 源合并 2499 行跑 `reliab --enable-alerts`：
  - 全库 PASS **54** / FAIL **22** / UNDETERMINED 566（此前 45/7）；
  - **ames 由 59 全 UNDETERMINED → 9 PASS / 15 FAIL / 35 UNDETERMINED**；
  - 与独立双方法计算（`ames_ichm7_v2.csv`）**100% 一致，0 错配**。
- 新增 `tests/test_ames_alerts_wired.py`（5 条），锁住"stat PASS+警示命中→FAIL、
  stat PASS+无警示→PASS、stat FAIL→FAIL、无专家层→UND、无 cache 向后兼容"。
- **顺带修复两处既有测试漂移**（同样属"记录≠实现"，非本次功能引入）：
  1. `tests/test_red_lines_v41.py` 断言红线 `len(st)==6`，但 `guards.all_enforced()`
     自 v4.4 起返回 **9** 条（+gate_eval_distribution / external_not_preregistered /
     endpoint_plurality）→ 改为 `==9`；
  2. `tests/test_snapshot.py` 的"完整夹具"停留在 G1–G9 时代，缺 G10/G12 要求的
     `references/CLAIMS_REGISTRY.yaml`、`THRESHOLD_REGISTRY.yaml` → 新门禁把缺失当
     blocker，导致 `test_release_gate_pass_and_block` 误报 → 夹具改为复制真实登记表
     （产物路径按 skill 包根解析，无需复制产物）。
- **全量 `pytest tests/` 100% 通过**（含上述 5 条新测 + 2 处漂移修复）。

### 四、文档同步（消除声称≠行为）

- `adt/endpoints.py`：ames 档位注释改为"`reliab --enable-alerts` 默认开、真实接线；
  未启用/无 SMILES 时维持 UNDETERMINED"，并记录 v4.3→v4.4 的脱节教训。
- `references/ENDPOINT_TIER_EVIDENCE.md` §5：把"真实升档"改为"升档 + v4.4 补生产接线"，
  明确"补了库+拒绝约束 ≠ 已接线"。
- `SKILL.md`：reliab 用法补 `--compounds` / `--enable-alerts` / `--no-alerts`。

> 版本仍 `4.0-dev`（前瞻预注册 R11 与第三方独立复现两项未关闭，标签授予条件不变）。

## v4.3（2026-11-01）——"仍未解决项"收口：7 项关闭/降级，其中 3 条结论对框架不利

一句话：**把 v4.2 红黑榜黑榜里"仍未解决"的项，全部换成一次实测或一个可辩护的替代设计；
最重要的新结果是"hERG 模型在 post-cutoff 全新骨架上 AUC 只有 0.581，比 always-positive 还差"。**

### 一、新增实测（每项都有产物路径 + 数字）

| 实测 | 产物 | 关键数字 |
|---|---|---|
| **post-cutoff 外源时间留出** | `out_ext/external/herg_holdout.json` | n=**9443**（ChEMBL_37，文献年份≥2023，剔除删失 5087/无效 304/重复 122/近重复 63）；到 TDC 中位最大 Tanimoto **0.241**；**AUC 0.581 [0.569, 0.593]** vs TDC 内部 **0.792**；阈值 0.5 下 specificity **0.051**，accuracy 0.674 **低于 always-positive 0.679**；换先验匹配阈值 0.661 后 accuracy 反降至 **0.603** |
| **S5 未校准基线** | `out_keystone_v43/results.json` | S4−S5 = hERG **−0.133**、DILI **−0.115**、BBB **−0.219**，全部 SIG 更差 → "基线过强"解释**被否证** |
| **回归端点 MMP（3 端点 × 4 模型）** | `out_ext/tdc/p8_mmp_reg_*.json` | Caco2 220 对 R 0.170–0.417（sign 0.53–0.58）→ `insensitive`；脂溶性 4636 对 R 0.32–0.41 但 sign **0.67–0.73** → **`compressed`**；溶解度 5684 对 2 个 `equivalent`、2 个 `inconclusive` |
| **多判据 AD（4 判据 × 3 端点 × 5 种子）** | `out_ext/tdc/ad_multicriteria.json` | **全部 AUC < 0.65**（最高 DILI kNN 0.648，最差种子 0.542）；conformal p 与 kNN AUC 差 ≤0.003 = 同一度量的单调变换 |
| **近邻泄漏归因** | `out_ext/tdc/leakage_attribution.json` | hERG Δ(r_error)=**+0.002**、BBB **−0.212** → 共享误差**不随**近邻泄漏上升；DILI 不可算 |
| **Ames 双方法（ICH M7(R2) §6）** | `out_ext/tdc/ames_alerts.json` | 补 `adt/alerts.py` 专家规则层后放行错误率 **0.269 → 0.177** |

### 二、判定修正（由实测逼出来，不是拍脑袋）

1. **回归端点新增 `compressed` 方向**：R<1 对"回归到均值"的模型是数学必然。
   新增符号一致率与二项符号检验（`sign_z ≥ 3.0`，**约定值**），R 判迟钝但方向显著一致时改判
   `compressed`（幅度保守、方向可靠），并**禁止**写"对结构变化不敏感"。
   不加这条，脂溶性（R=0.32、方向 73% 对）会被误报成迟钝——
   与 P8 旧版把迟钝误报成稳定是同一类错误的镜像。
2. **Ames 档位 `not_recommended` → `qualitative_only`**，但带可执行约束：
   ≥2 源 + 必须启用专家规则层，否则降 `UNDETERMINED`（`apply_tier_policy`）。
   `tests/test_input_compliance_v41.py` 同步改钉这三条约束（原断言已过期）。

### 三、基础设施

- **新增 `adt/tdc_local.py`**：TDC 切分读取器，优先官方 `tdc` 包、未装则读缓存 CSV。
  原因：`run_p8_mmp_regression.py` / `run_external_holdout.py` 三端点全部
  `ModuleNotFoundError: No module named 'tdc'`，而数据早已在 `out_ext/tdc_cache/` 里。
  7 个 `run_*.py` 全部改走该入口；本地读取规模与文档记载逐一吻合（hERG 523/132、DILI 379/96、
  BBB 1624/406、Caco2 728/182、脂溶性 3360/840、溶解度 7985/1997、Ames 5821/1457）。
- `run_external_holdout.py`：改用活性记录自带的 `canonical_smiles`（原 `molecule_chembl_id__in`
  批量查询实测返回 0 条）；剔除删失值 / ChEMBL 无效记录；新增 AUC bootstrap CI 与
  **先验漂移分解**（0.5 阈值 vs 先验匹配阈值）。

### 四、文档

- 新增 `references/UNRESOLVED_CLOSEOUT_v4.3.md`（SKILL.md 早已引用但文件不存在）：逐项写明
  关闭/降级/仍开，并给 Sheridan 2013、TRIPOD+AI 2024、PROBAST 2019、Silberzahn 2018、
  Steegen 2016 等依据 + 允许/禁止措辞。
- `references/GATE_AND_P8_MMP_v4.2.md` §4：6 条"仍未解决"逐条标注去向，新增 §4.7–4.9。
- `references/REVIEW_v4.1_LEDGER.md`：R11 ⛔ → 🟡（降级未关闭）；v4.3 表补全。

### 五、验证

- 全量 `pytest tests/` **exit 0**（含新增/改写的回归支与端点档位测试）；
- `release-check` **9/9 PASS**；
- 版本仍 `4.0-dev`：**前瞻预注册（R11）与第三方独立复现两项仍未关闭**，标签授予条件不变。

## v4.2（2026-11-01）——空心闭环清查：三项"代码已写、从未执行"补跑

一句话：**42 项台账里查出 3 项空心 ✅（`out_gate/`、`out_p8/` 目录根本不存在），
补跑后 2 项结果推翻原有说法、1 项承认测不了。**

### 一、查出的问题
- R14（P8→MMP 检验）、R19（gate 误放/误杀）、R20（gate ROC/PR）三项此前标 ✅，
  实际只有模块与 `run_*.py`，**从未产出任何结果文件**。台账已改登记规则：
  标 ✅ 必须附产物路径 + 至少一个数字。

### 二、三端点真实结果（`references/GATE_AND_P8_MMP_v4.2.md`）
- **gate 判别力是端点依赖的**：DILI AUC **0.669**（域外准确率 0.746 vs 域内 0.939，Fisher p=0.027）
  → PASSTHRU **有据**；hERG **0.580**、BBB **0.514**，域内外准确率无差异（p=1.000 / 0.755）
  → PASSTHRU **无据**。**任何"本框架域外弃权是诚实的"全局表述都被这两个端点否定。**
- **P8 旧结论方向相反**：hERG 127 对（标签翻转 13.4% vs 模型 0.0%）、BBB 479 对
  （16.3% vs 4.8%），TOST 均不等效 → 模型对活性悬崖**迟钝**。
  旧版"位移小 = 稳定"把缺陷当优点表彰（评审 F4 预判命中）。
- **DILI MMP 检验功效不足**：31 对 < 所需 61 对，连完美模型（oracle-like）都判不出等效
  → 标 `insufficient_power`，**不判迟钝**。

### 三、代码
- `adt/gate_audit.py`：新增 `discriminative_power()`、`forced_prediction_test()`（Fisher 精确检验）、
  `GATE_AUC_FLOOR=0.65`；`actionability_summary(rows, thr, power=None)` 在未测判别力时
  强制 `gate_verdict="not_measured"` 并写明"不得称域外诚实"。
- `adt/mmp.py`：`_overall_status` / `_overall_interpretation` 方向化（insensitive / oversensitive /
  insufficient_power）；新增 `min_pairs_for_power()` 与 `power` 块；迟钝状态下的解释文本内嵌"禁止"。
- `adt/mmp.py` **新增召回拆分**：`overall.cliff_recall` / `flat_specificity` / `flat_false_alarm_rate`
  —— 单一翻转率读不出召回（模型不动时 0 真阳与全部真阴混在一个率里）。
  实测 hERG 召回 **0.000**（17 正例命中 0）、BBB **0.115**（78 命中 9）、特异度 1.000 / 0.965。
- `adt/mmp.py` **新增回归支**：`analyze_regression()`（位移幅度比 R 的 TOST，判据 R∈[0.5,1.5] 为等效）
  + `analyze()` **非二值守卫**（连续标签直接 `ValueError`，此前会把每对都判成"翻转"）。
  ⚠️ 回归支尚无真实端点运行，仅接口可用。
- `run_gate_audit.py` / `run_p8_mmp.py` 参数化 `--endpoint`，输出按端点分文件。
- 新增 `run_p6_seed_ci.py`：Caco2 泄漏增益的 20 种子配对裁决。

### 四、附带：Caco2 泄漏结论**顶住了**质疑
- 配对 Δ 中位 **−0.0228**，95%CI **[−0.0274, −0.0206]** 完全 <0 → 不是种子噪声，原结论成立。
- 但 seed0 绝对 MAE（0.4128/0.3883）比 20 种子中位（0.3964/0.3730）高约 0.016：
  **差值可用，绝对水平必须报 median[IQR]**。

### 五、验证
- `tests/test_gate_mmp_v42.py` 新增 7 条（钉判定语义，不钉小数）；
- 全量 pytest exit 0；`release-check` 9/9 PASS；版本仍 `4.0-dev`（R11 外源盲测仍 ⛔）。

## v4.1（2026-10-31）——黑榜收口第二轮：干净机复现 + 端点文献补齐

一句话：**黑榜 7 项从「4 项闭环」推进到「5 项闭环 / 2 项待外部输入」**，
过程中抓出 1 个真缺陷（依赖清单漏 `lxml`）并修掉 4 处自我不一致。
**其中 4 项闭环的结论对框架不利**（S4 从未显著优于纯置信度弃权、收缩权重方向不一致、
nr_ar_lbd 档位偏保守、干净机漏依赖），故仅记为 v4.1 材料轮次，**安装版仍为 `4.0-dev`**（G9 拦截）。

### 一、真实缺陷（干净机复现抓出，非代码风格问题）
- `adt/adapters/vnn.py`：新增 `_make_soup()`，`lxml → html.parser` 依次尝试，
  两者皆失败才 `RuntimeError`（原为硬编码 `BeautifulSoup(html, "lxml")`）。
  根因：`requirements` 从未声明 `lxml`，主环境靠**别的包的传递依赖**侥幸可用；
  按 lock 装机的环境 `test_vnn_parser.py` 必崩（`FeatureNotFound`）。
- `requirements.txt` / `requirements.lock`：补 `lxml`（`>=5.0` / `==6.1.3`，实测版本）。
- `.github/workflows/ci.yml`：安装改为 `pip install -r requirements.txt`
  （原仅装 rdkit/pyyaml/requests/numpy/pytest，缺 bs4/scipy/sklearn/pandas/lxml → CI 真跑必假失败）。
- `tests/test_vnn_parser.py`：新增 §5（3 条断言，21→24），钉住"降级后解析结果与 lxml 逐字段一致"+"两解析器都失败显式报错"。

### 二、端点分级文献补齐（黑 6）
- `references/ENDPOINT_TIER_EVIDENCE.md`：新增 §3.1 致癌性（Gottmann 2001, PMID 11401763，
  CPDB **121 组重复一致率 57%**）、§3.2 nr_ar_lbd（Huang 2011 / Klimenko 2020 支持"单测定脆"，
  但 Kleinstreuer 2018 的 11 测定通路模型 **PPV 100%** 反向削弱该结论）；§4.3/§5/§6 同步更新。
- `adt/endpoints.py`：`ames` / `carcinogenicity` / `nr_ar_lbd` 的档位理由字符串改为**直引证据**，
  并显式标注后两者"档位偏保守"。**档位本身未改**（改档需重跑判定链，留待下版）。

### 三、文档一致性
- `references/BLACKLIST_CLOSEOUT.md` §6/§7/§8、`references/TASK_SCORECARD_v4.1.md`、
  `references/REPRODUCIBILITY.md`、`references/TDC_ALIGNMENT.md`、`SETUP_REPRODUCE.md`：
  测试计数统一为 **75/75**；黑榜状态更新为 5 ✅ / 2 🟡；新增干净机复现三层证据表。
- `SETUP_REPRODUCE.md`：新增环境坑 §5.6（`lxml` 必须显式装）；环境要求表改为
  "依赖以纯 Python 为主，唯一 C 扩展是 lxml（可降级）"。
- 新增 `外部评审材料_v4.1.md`（按 8 字段模板重写送审材料）；`外部评审材料_v4.0-dev.md` 顶部加"已被取代"指针。

### 四、验证（全部实测）
- 主环境 `pytest`：**75/75，EXIT=0**；`release-check`：**9/9 PASS**。
- 干净目录（排除 `out*`）：release-check 9/9 + 75/75。
- 干净 venv（py3.13.14，按 lock 装）：75/75；**卸载 lxml 后**再跑：仍 75/75。

## v4.0-dev（2026-10-31）——评审 v4.0 拔高落地（Major Revision 应对）

一句话：**按同行评审报告 v4.0 的 35 项执行清单（P1–P13 / L1–L3 / C-U-D）逐条拔高**；
代码层（P1 双通道、P2 CI 注册门、P4 配对 McNemar、P5 略优审计）已落地并 66/66 pytest 全绿，
文档/方法学层覆盖全部 35 项；**需真实数据/算力的阻断项（P3 risk–coverage、P6 去污染、P11 mppb 留痕等）
已写入方法学+脚本骨架，待实验室数据跑通后闭环，故版本标 `4.0-dev` 而非 `4.0`**。

### 一、代码层（已测，66/66 全绿）
- `adt/independence.py`：新增 `rho_contraction_weight`（P1 双通道：n_eff=1/(1+max(ρ,0)) 截断 +
  ρ<0 触发 `source_conflict` 冲突分流；ρ 须经 Fisher z 95%CI 下界>0 才收缩）——修 C1/C10 致命。
- `adt/reliability.py`：注册第七类归因常量 `SOURCE_CONFLICT_REASON`。
- `adt/stats_ci.py`（新）：Clopper-Pearson 95% CI 注册门 `registration_gate` + 设计端通过概率
  `gate_pass_probability`（真实计算：真失败率 3% 时 n=100 通过概率仅 4.8%）——修 C5。
- `adt/prospective.py`：新增 `paired_mcnemar` 精确二项配对检验（P4，修 C7）。
- `adt/phrasing.py`：新增 `flag_unqualified_superiority` "略优"审计护栏（P5，修 C2）。
- 新增测试：`test_rho_contraction.py`(7) / `test_stats_ci.py`(5) / `test_p4_p5.py`(4)，登记入 `test_smoke_pytest.py`。

### 二、文档/守护层（SKILL.md + references/）
- 守护项固化：科学自我意识、证据准入流水线、铁律3 条件化（D2）、G5 充分性边界、复现四元组。
- 核心贡献声明精确化（P9，删"共同跳过"）。
- 新增参考文档（10 份）：`V4_ELEVATION_PLAN`(中央台账) / `INDEPENDENCE_DECISIONS` / `STATISTICAL_POLICY` /
  `RISK_COVERAGE_PROTOCOL` / `DECONTAMINATION_PROTOCOL` / `SOURCE_REGISTRATION_POLICY` /
  `ADAPTER_COMPLIANCE` / `BAYESIAN_DECISION` / `EXCHANGEABILITY_PROTOCOL` / `TDC_ALIGNMENT` /
  `SAP_PROTOCOL` / `REPRODUCIBILITY`。
- §8 SOP（版本钉死/三态不改判/每端点归因/排序默认关/ρ 数据集条件量/负结果入库/PASS门禁非排序）+ 反模式 + 引用格式。
- 文献锚点核查（U1/U4/C8）：U1 不在分发版故无残留；U4 外部 DOI 待用户核验后钉入（不编造）。

### 三、诚实边界（务必保留）
🟡 项（P3/P6/P8/P11/P13/L1-1/L2-1/L2-2/L3-1~4 等）为**文档+方法学已写、数值待真实数据闭环**，
不得伪造；其数值栏在拿到数据前以"待跑"占位。详见 `references/V4_ELEVATION_PLAN.md` 红黑榜。

## v3.6.2（2026-10-30）——三份外审报告全量对账 + 两项欠账补跑

一句话：**把四次外审（审 v3.2.1/v3.3.0/v3.5.0）的全部要求逐条对账**，30 项已闭环、
5 项部分、2 项未执行、2 项不可执行；本轮把其中两件能跑的补掉了（方向4 三空间真实对比、
模块O 的 OneADMET 检测），并修一个提示语缺陷。

### 一、方向4 跨类一致性：真实三空间（此前只有玩具数据）
- 数据：14 苷（84 对，真实 web 源）/ OpenADMET（20,538 对，双基线）/ NPASS（391 对，双基线）。
- 结果：弃权率 **glycosides 0.500 > openadmet 0.276 > npass 0.192**，定向检验**符合预期**
  （差 0.308）——弃权率随可裁决性单调变化，与准入逻辑预测一致。
- 口径限制（必须声明）：三空间面板构造与端点不同，属"行为模式对比"而非同端点准确率对比。

### 二、模块 O：失效检测器在 OneADMET curated 数据上 0 命中
- `fail-layers` 三层（契约/裁决/架构）在 11,944 行上全部 0 命中，与 OpenADMET（10,738 行）一致。
- 特异性（FPR）仍不可估，诚实声明不伪造。

### 三、修复
- `crossclass.compare_spaces`：只声明单侧预期时误报"未声明预期方向" → 现明确提示缺哪一侧。

### 四、台账
- `评审要求落实台账_v3.6.2.md`：逐条对账 + 7 项待裁决（D1–D7）+ 3 项可立即执行（W1–W3）。

## v3.6.1（2026-10-30）——L 彻底闭环：OneADMET 到手 + 方向性检验成立 + 修 phys_range 实测路径漏洞

一句话：**L 从"部分闭环"变为"彻底闭环"**——用户手动过 Cloudflare 下载 OneADMET SI
（35 MB ZIP → 1.2 GB `oneADMET.csv`，738,161 化合物/44 ADMET 端点），与 OpenADMET raw
构成同端点、双独立 curation 的方向性检验；实测确认专家预测方向**在值级成立**。
期间发现并修复 `reliability.py` 一个真实漏洞。

### 一、phys_range 实测路径漏洞（新模块实例分析暴露，已修 + 回归测试）
- **漏洞**：`reliability.evaluate` 的 phys_range 只过滤 `in_dom`，`measured` 在过滤**之前**
  构建 → **实测路径绕过物理边界守卫**。真实后果：OpenADMET raw 的 MLM CLint
  10,354 µL/min/mg（phys 上限 5000）被直接判 FAIL 而非按无效值弃权——违反 C80
  "物理不可能值一律无效"的本意。
- **修复**：`measured ⊆ phys 过滤后的 in_dom`；某 (cid,ep) 全部值越界 → 走
  "全部越物理边界"域外分支（n_in_domain=0，可被 transfer 检验）。
- **回归测试**：`tests/test_phys_range.py` 新增第 6 节 3 条（实测越界弃权 / 混合越界用合法值 /
  值级域外触发），21/21 通过；全量 63 套 pytest 全绿。

### 二、L 方向性检验（`transfer` + 值级统计增强）
- **数据**：OneADMET SI `PUBLIC___LogPapp_Caco`（log10 cm/s）、`PPB_Human`（%bound→fu%）、
  `LogER_Caco2`（10^x→ER）、`LogD74`；OpenADMET raw 对应 5 组端点。量纲**逐一实测核实**
  （OneADMET 列名 `pX` = −log10(X) 约定已确认；Clearance-Microsomal 为 per-kg 体内
  清除率，与 clint µL/min/mg 语义不同 → **不映射**，遵守 C52/C70）。
- **结果**（修复后引擎）：

  | 数据集 | 值级 | 准入拒绝 | 值级拒绝率 | 对数 | 弃权率 |
  |---|---|---|---|---|---|
  | OneADMET_meas（严格 curation） | 11,944 | 0 | **0.000%** | 11,944 | 0.149 |
  | OpenADMET_raw（原始未清洗） | 29,258 | 38 | **0.130%** | 22,656 | 0.134 |
  | TDC_ADME | 17,528 | 0 | 0.000% | 17,248 | 1.000（无规则） |

- **方向性检验结论（论文口径，两句一起说）**：
  ① **对级**（domain_block_rate）：0.000 vs 0.000，未观察到位移——统计粒度太粗
  （越界值与合法值同组共存时对级恒为 0），如实报；
  ② **值级**（准入拒绝率）：0.000% < 0.130%，**方向符合专家预测**——curation 更好的
  OneADMET 被准入层拒绝的值更少，准入行为随数据质量按预期方向移动。
- **transfer 模块增强**：`profile()` 新增 `n_values`/`n_values_rejected`；
  `compare()` 方向性检验在预期顺序下**同时输出值级方向结论**；
  `write()` 的 profiles CSV 增列。

### 三、新产物
- `assets/external/oneadmet/`（jm6c00049_si_002.zip + extracted/oneADMET.csv，1.2 GB）
- `instances/v350/oneadmet/oneadmet_measurements.csv`（11,944 行）、
  `openadmet_raw_measurements.csv`（29,258 行）、`transfer/`（profiles + note）
- `L项四方案实测裁决与闭环结果.md`（四方案裁决 + L 闭环全记录，全中文）

### 四、运行环境全面排查（换机可复现，2026-10-30 晚）
- **依赖清单补全**：全量扫描 `adt/` + `adt/adapters/` + `tests/` import →
  requirements.txt 原缺 scipy / scikit-learn / pandas / beautifulsoup4，已补齐并
  逐项标注实测版本（numpy 2.5.4 / rdkit 2026.09.1 下 63/63 全绿）。
- **硬编码路径**：全仓扫描仅 1 处（truth_contract.md 文档示例），已改为可移植写法；
  代码层仅 `vnn.py` 用 `expanduser("~")`（可移植、缺失凭据优雅降级）。
- **新增 `adt/__main__.py`**：`python -m adt ...` 与 `python -m adt.cli ...` 双入口等价。
- **新增 `SETUP_REPRODUCE.md`**：新机从零复现指南（依赖安装、随包/需重下载的外部数据
  含 OneADMET SI 直链、5 条已知环境坑、三层验证流程）。
- **装机副本独立验证**：在 `~/.workbuddy/skills/admet-screening` 独立跑全量测试 63/63
  全绿（不依赖开发路径，是"另一台电脑"的最接近本机代理）。

## v3.6.0（2026-10-30）——未闭环 4 项处理：G 真前瞻 + A 真实源 ρ 闭环，C 脚本就绪，L 外部阻塞

一句话：**A / C / G 三项从"协议已给"升级为"真实数字"**——
G 用 ExpansionRx 官方时序 split（train 1321–20100 / test 20101–27239，实测零重叠）；
A 用工作区已有的 14 分子双真实源预测（14/14 SMILES 重合）；
C 由 skill 自己驱动 ADMETlab3 批量提交 45 个 SMILES（45/45 成功）实测得到。
只剩 L（OneADMET）因 ACS Cloudflare 与 PyTDC 版本不兼容而阻塞，已记录，不伪称闭环。

### 一、G 真前瞻裁决（新模块 `adt/prospective.py` + CLI `prospect`）
- 查证并**实测**：OpenADMET-ExpansionRx 的 train/test 就是官方**时序切分**
  （官方文档："IDs in the Molecule name column reflect measurement order"、"time (chronological) split"）；
  本机核对 train ID 1321–20100（5,326 分子）、test 20101–27239（2,282 分子），**重叠 0、test 全大于 train**。
- 结果（10,738 个真值对）：

  | 策略 | coverage | decided_acc | PASS 组失败率 | FAIL 组虚警率 |
  |---|---|---|---|---|
  | 完整准入层 | 0.7746 | 0.8793 | **8.28%** | 22.67% |
  | 仅单位守卫 | 0.760 | 0.8868 | 7.83% | 21.60% |
  | 无准入多数投票 | 0.772 | 0.2733 | 45.27% | 73.35% |

- **如实报负结果**：在真时序外推的自然 coverage 下，完整准入层**没有**击败"仅单位守卫"
  （0.8793 vs 0.8868；8.28% vs 7.83%）。与方向 A 消融"同 coverage 下 (c) 明显更优"不矛盾——
  前者问"置信排序谁更好"，后者问"实际部署谁更准"。论文两口径都要给。

### 二、A 真实源间相关性（新模块 `adt/source_rho.py` + CLI `source-rho`）
- 发现工作区已有同一批 14 分子的双真实源预测：`admetlab14_v5/admetlab3_raw.csv` 与
  `admetai14_v23/admet_ai_raw.csv`，**14/14 SMILES 重合**，15 个可比端点。
- **中位 Spearman ρ = 0.2264**（n=14/端点，bootstrap 1000 次 95% CI）。
  三个发现：① 两源在本类内**不冗余** → 支持保留 2 个独立方法组（C77）；
  ② **hERG ρ=−0.5736，CI [−0.893, −0.045] 不含 0** —— 两源对 hERG 排序**方向相反**，
  是 sign_conflict 规则的首个统计显著实例；③ **DILI 与 NR-ER 类别一致率 = 0.000**
  —— 定量解释了工作包 E 的"admetlab3 DILI 全阳"，两源在该端点不可比。
- 诚实边界：n=14、13/15 端点 CI 跨 0，只能说明"本类内未观察到高度一致"，不外推全局。

### 三、C 预测值位移（新模块 `adt/ac_plan.py` + `adt/pred_displacement.py`）—— **已闭环**
- `ac-plan` 生成提交清单：14 分子 × {original, stereo_removed, tautomer} + 4 控制分子
  → 45 个唯一 SMILES。
- **实跑 ADMETlab3**（`/server/screening` 支持批量粘贴、免登录、上限 1000）：45/45 成功、0 无效；
  取其 `download/csv` 的 122 列全端点，保留与 A 可比的 15 端点 → 675 行长表。
- **结果**：中位 `结构位移/源间位移` = **0.57**；但 **PASS/FAIL 阈值翻转 63 例**
  （去立体 48 + 互变体 15）。
  - **DILI 去立体：14/14 全部翻转**（A 0.683→0.144、B 0.876→0.326、D 0.841→0.224）；
  - NR-ER 10 例、NR-AR-LBD 9 例、NR-ER-LBD 4 例、SR-p53 4 例；
  - **hERG：位移仅 0.032、0 翻转**，但源间位移 0.383 最大（ρ=−0.574）。
- **判读（两结论必须同时报）**：平均幅度上结构扰动 < 源间分歧（0.57）；
  但决策层面结构标准化是决定性的（63 翻转）。DILI 与 hERG 的失效来源**恰好相反**，
  是"结构标准化 vs 源资格不可互替"最硬的证据。
- 新增 `threshold_flips()`：单独统计 PASS/FAIL 被推到阈值另一侧的情况
  （评审原话："clogp 位移可能让 hERG 阈值翻转，而你没有测这一点"），
  并对连续量纲端点（logP/logS/logD）自动跳过以免假翻转。
- **修的 bug**：初版把 `original` 也标 no-op 而跳过 → 拿回"有变体没基线"，位移无法计算。
  现 `original` 永远提交；另修复同一 SMILES 对应多个 (cid,variant) 时被字典去重吞掉的问题
  （J 的 original 与 tautomer 同 SMILES）。

### 四、L OneADMET（外部阻塞，未闭环，不伪称）
- ACS 论文页/SI 直连 **403**（Cloudflare）；WebFetch 返回 "Just a moment…"；
  无头 Chrome 也停在"正在进行安全验证"。
- PyTDC（TDC benchmark group）**装得上但不可用**：`pytdc 1.1.15`（最新）硬性要求
  **numpy<2.0.0、rdkit<2024.3.1**，本环境是 numpy 2.5.4 / rdkit 2026.09.1；
  为它降级会废掉整个 skill 的 RDKit 2026 栈 → **已卸载 PyTDC，保持环境干净**。
- 给出三条可行路径（独立 venv 跑 TDC / 手动下 OneADMET SI / 换可得数据集）。

### 五、工程修复
- **meta-runner 临时目录累积**：63 个子进程 pytest 会话各建一个临时根，累积过阈值后
  pytest 的垃圾清理触发环境"批量删除确认"，导致 8 个测试**误报失败**。
  修复：`test_smoke_pytest.py` 固定 `PYTEST_DEBUG_TEMPROOT=<repo>/.pytest_tmp` 并预先 makedirs。
- 两个测试遗留 `tempfile.mkdtemp()`（不清理）→ 改用 `tmp_path` fixture。
- 注意：`.pytest_tmp` 不要同步到装机副本。

### 六、新增
- 新模块 4：`prospective`、`source_rho`、`ac_plan`、`pred_displacement`
- 新 CLI 4：`prospect`、`source-rho`、`ac-plan`、`pred-shift`（各 1 别名）
- 新测试 3：`test_prospective`、`test_source_rho`、`test_ac_plan`
- 材料：`未闭环4项_处理结果_v3.6.md`

## v3.5.0（2026-10-30）——第三次外审响应：准入层消融 + Regaloside A/B case study + GRADE 决策触发 + 模块 L/M/N/O

一句话：**按 DeepSeek 第三次核对（deepseek_report4_raw.txt，审 v3.4.0）逐条响应：把 v4 里"协议已给、
未闭环"的项用真实数据跑出数字（方向A 消融、方向B case study）；把确定性分级升级为与决策阈值挂钩的
映射（方向C）；落成评审点名的四个拔高模块 L/M/N/O；并对全部新模块做实例分析，修 8 个真实 bug。**

### 一、方向A：准入层消融（填工作包 D 与 H 的缺口）
- 新增 `adt/ablation.py` + CLI `ablate`：同面板同真值下四条件对比
  (a) 全源多数（忽略单位）/ (b) 仅单位守卫 / (c) 完整准入 / (d) 准入+类条件保形；
  额外给**同 coverage** 比较（回答"87.9% 是孤立数字还是胜出"）。
- **真实运行**（OpenADMET test 2,282 分子 × 9 端点 = 10,738 真值对，两个 Ridge 基线）：
  coverage 0.772→0.760→0.0675；decided_acc **0.2733 → 0.8868 → 0.9462**；
  同 coverage(725) 下 **0.2579 → 0.8290 → 0.9462**；`--corrupt domain` 后 (c) 0.9512 vs (b) 0.8564。
- 纪律：`--corrupt` 产物标 `panel=controlled_corruption`；(a) 明确标为"故意朴素"基线，不得读成"多源投票无效"。

### 二、方向B：Regaloside A vs B case study
- 新增 `adt/case_regaloside.py` + CLI `regaloside-ab`：真实结构（CAS 114420-66-5 / -67-6，
  C18H24O10 / C20H26O11）跑糖苷轴 + 被动轴。
- 结论：框架**不能**在被动层区分 A/B（都 unlikely），但把差异**定位**到糖苷键位阻
  （A primary / B secondary）+ 乙酰化（False/True）+ 酯键数（1/2）+ XlogP（−1.87/−1.30）。
- 诚实限制：水解**分级**对 A/B 相同（都 high，因都有酯键）——规则编码"责任存在"而非"速率"；
  另给 4 条可检验假设 H1–H4（含 H1 的反向可能）。

### 三、方向C：确定性分级 → 决策触发映射
- `adt/certainty.py` 新增 `DECISION_TRIGGER` / `DECISION_NEXT_STEP`，`annotate()` 写入
  `decision_trigger` / `decision_next_step`；`mapping_table()` 同步带出。
  `low_unresolvable` → "不得基于计算推进"；`moderate` → "可筛选但不得排序"。

### 四、模块 L/M/N/O
- **M** `adt/abstention_compare.py` + `abstain-cmp`：逐端点 AURC + 跨端点 sd/IQR/CV。
  **实测给负结果**：sd(structural)=0.1353 ≥ sd(spread)=0.1257 → **不支持**"结构性弃权更一致"，
  并如实转述为"支持两轴不互替（structural AURC 0.1871 差于 spread 0.1404）"。
- **N** `adt/abstain_attrib.py` + `abstain-why`：UNDETERMINED 归因 9 类 + 可多重 + 修复建议。
  实测 5,673 条弃权：`phys_range_violation` 88.4% / `domain_block` 9.5% / `spread_exceeded` 2.1%
  → 主导失效是"模型输出越物理边界"，不是"源不够多"。
- **O** `adt/failure_layers.py` + `fail-layers`：7 类失效按契约级/裁决级/架构级三层组织；
  显式输出**特异性未被挑战**的告警（0 触发 ≠ 0 误报）。
- **L** `adt/transfer.py` + `transfer`：多数据集弃权行为画像 + 方向性检验。
  代理运行：two_sources 域外触发 0.026 < one_source 0.102（**符合预期**），标 `proxy=true`。
  同时如实记录"raw vs test split 无位移"的失败尝试（OpenADMET 值为 measured，准入无仲裁对象）。

### 五、实例分析修复的 8 个真实 bug
1. `cmd_regaloside_ab` 格式串 `A(0.52%)` 未转义 → `ValueError`
2. `abstention_compare` 端点<2 时 `_sd` 返 None 仍做除法 → `TypeError`
3. `external.write_baseline` 的 `*_risk.csv` 语义坑：value 是**方向对齐后的原始量纲**（shape=up 时为 −v，
   实测 −54.9），`unit="risk_score"` 容易被误当 0–1 分数 → 0.5 阈值与 `phys_range` 双误判；
   已在 `ablation.py` 头写死警告并改走 `--rules`
4. `ablation.policy_unit_guard` 过滤后又用 `naive=True` 重投影 → (b)≡(a)
5. `ablation.policy_admission_plus_conformal` 的 `**kw` 未透传 `rules` → (d) coverage=0
6. `ablation._class_of` 不认真实量纲 → 新增"给 rules 就走端点阈值"分支
7. `transfer.write` 手写 profile 缺字段 → `KeyError`；改 `.get()`
8. **`certainty.grade_dimensions` O(n²) 性能雷**（v3.1.0 遗留）：每条 rec 全表扫 measurements；
   20k×41k 真实面板上 `certainty` 命令 >300 s 超时 → 预建版本索引，**3.9 s** 完成

### 六、其他
- `adt/glycoside_hydrolysis.py` 新增 `bond_position`（primary/secondary/tertiary）、
  `n_ester_bonds`、`acetylated`（不改变 high/medium/low 分级，只加细粒度描述符）。
- 新增测试 6 个文件（ablation / case_regaloside / abstain_attrib / abstention_compare /
  failure_layers / transfer），扩展 glycoside_hydrolysis 与 certainty 测试；全量 **60/60** 脚本通过。
- 新 CLI 6 个：`ablate`、`regaloside-ab`、`abstain-cmp`、`abstain-why`、`fail-layers`、`transfer`。
- 材料：`外部评审材料包_v5.md`（v4 保留为历史）。

## v3.4.0（2026-10-30）——评审二次核对响应 + 深水区补全 + 四条增量方向落地

一句话：**按 DeepSeek 外审（deepseek_report3_raw.txt，审 v3.3.0）逐条响应：深水区 2.1/2.2/2.3 全部落成代码，方向1（类条件 conformal）与方向4（跨化学类一致性）落成代码与 CLI，方向2/3 落成论文级材料；A/C/G 给可执行协议 + 诚实局限（不伪称闭环）。**
- **2.1 SAR 预筛补"下一句"**（`adt/sar.py`）：`diagnose()` 新增 `bbb_determinant_layer` 字段——
  被动窗失败 → `passive_closed → transporter_resolution_required`，结论从"被动渗透受限"改写为
  "被动层已关闭、决议权交转运体层"。
- **2.2 BBB 三通道决议**（`adt/bbb.py` 重写 `apply_dual_layer`）：从"双层（被动×外排）"升级为
  "三通道（被动×外排×摄取）"，输出 `bbb_mechanism=three_channel_resolution` +
  `bbb_channels=passive(closed_by_SAR) × efflux(P-gp/BCRP) × uptake(GLUT1/SGLT1/OATP2B1)`。
  `references/transporter_priors.yaml` 做**生物学保真修正**（v3.4.0 诚信点）：SGLT1 在 BBB 内皮
  **无功能性表达**（Yu et al. 实证），GLUT1 **只转运单糖、不转运完整糖苷**——不夸大完整糖苷的
  脑侧摄取正项，把杠杆定位在肠侧 SGLT1/OATP2B1 吸收与苷元水解转运。
- **2.3 糖苷水解-苷元暴露轴**（`adt/glycoside_hydrolysis.py` 新模块 + `glycoside-hyd` 命令）：
  区分 O-糖苷键稳定性等级（acyl / phenolic / alkyl），输出 `intestinal_hydrolysis_risk` +
  `aglycone_first_pass_risk`；把"14/14 low 酰基葡糖苷酸"升级为"糖苷稳定性-苷元暴露轴"
  （酰基葡糖苷酸豁免正确，但糖苷水解 + 苷元首过才是本类真实暴露决定因素，标为需实验）。
- **方向1 类条件 conformal**（与 2026 少数类失效文献正面对话）：`adt/conformal.py` 新增
  `_cc_score` / `class_conditional_coverage` / `evaluate_disjoint`（正确校准-测试不相交 CP）/
  `build_class_conditional_endpoint`；文献锚点 arXiv:2607.06605v1（2026，边际保形 BBBP 少数类
  64.8%→Mondrian 90.3%）。`conformal-class` 命令 + `--endpoint` 输出边际 vs 类条件覆盖与 MCG/CII。
- **方向4 跨化学类裁决行为一致性**（替代原"分子对接层"，评审已确认口误）：`adt/crossclass.py`
  新模块 + `cross-class` 命令（含 `--expected-high/--expected-low`），在统一行为指标下对比多化学空间
  并检验"弃权率随可裁决性单调变化"的可检验预测；反向则报结构性缺口。
- **方向2/3 论文级材料**：MARS（Comput Biol Chem 124:109213, 2026）与 ADMET-XSpec
  （Chem Res Toxicol 2025, 39(8):1518–1531）近邻引用 + 分工表（扩 `09_reliability_landscape.md`）；
  14 分子"不可裁决"重框定为"与 Regaloside 实测 PK 一致"。
- **A/C/G 协议**：维持 v3.3.0 的 Ridge 基线 ρ 为"方法组内对照"并明确标注；新增真实外部源 ρ /
  预测值位移 / 前瞻裁决的**可执行协议 + 命令骨架**，诚实标注"数据可得性未闭环"。
- **测试**：新增 `test_glycoside_hydrolysis.py` / `test_bbb_three_channel.py` /
  `test_conformal_class.py` / `test_crossclass.py`；更新 `test_bbb_dual_layer.py`（重框定断言）。
  **维修**：补全 `adt/cli.py` 缺失的 `def main(argv=None):`（v3.3.0 收尾残留致全部 CLI `NameError`）。
  全绿：54/54 测试脚本通过。
- 配套材料 `外部评审材料包_v4.md`：A–J/2.1–2.3 审计总表 + 四条方向全方位解读 + SCI 落地的
  Discussion 段落 / 图例 / 审稿防御清单 + A/C/G 协议。

## v3.3.0（2026-10-30）——深水区拔高（外部评审二次核对 2.1/2.2/2.3 落地）

一句话：**把评审报告"深水区拔高"里三条明确建议从文档主张变成可跑、可测、可审计的代码。**
- **2.1 SAR 预筛轴**（`adt/sar.py` + `sar` 命令）：对每个分子算 TPSA/MW/HBD/HBA/XlogP，
  与内置 BBB+ / BBB− 参照集（来自 BBB-Nuke 2026 与 CNS MPO 阈值）比较，输出
  "结构-通透性瓶颈"诊断：被动渗透筛选（TPSA/MW/HBD 三道闸）、最近邻参照、瓶颈因子列表。
  报告已给出两个真实锚点：GCG（MW 462.4 / TPSA 183.2，BBB−）与
  10-O-trans-p-methoxycinnamoylcatalpol（MW 522.5 / TPSA 177.0 / XlogP −0.60，BBB−）。
- **2.2 BBB 双层机制**（`adt/bbb.py`，接入 `reliab`）：当 BBB 端点（vnn_bbb 等）裁决为
  UNDETERMINED / PASSTHRU 时，**强制改写 action 为"P-gp 底物概率评估（双层机制）"**，
  不再泛泛"补实验"；同时激活 `references/transporter_priors.yaml` 的 P-gp 先验与 assay 处方。
  输出带 `bbb_mechanism=dual_layer_activated` 列，可审计。
- **2.3 acyl glucuronidation 结构警示**（`adt/acyl_glucuronide.py` + `acyl-glucuronide` 命令 +
  `03_endpoint_rules.yaml` 新增 `acyl_glucuronide_risk` 端点）：输入为羧酸/酰基存在（SMARTS）、
  α-碳取代模式、共轭程度 —— 这是**结构警示 + 风险分级**（high/medium/low），不是外部预测端点。
  本批 14 个糖苷为酯键、无自由羧酸 → 全部判 low；咖啡酸/阿魏酸等自由羧酸苷元 → high。
- 新增测试 `tests/test_sar.py` / `tests/test_acyl_glucuronide.py` / `tests/test_bbb_dual_layer.py`
  （共 18 断言），已注册进 `test_smoke_pytest.py` 的 SCRIPTS，`--help` 覆盖扩到 45 个调用名
  （38 主命令 + 7 别名）。
- 配套解读文档 `references/10_deep_water.md`：SAR 瓶颈的化学意义、BBB 被动×P-gp 双层的
  动力学理由、酰基葡糖苷酸生物活化（Grillo 2021）与本项目糖苷为何豁免。

### 纪律细节
- BBB 双层只改写 BBB 端点且只在"证据不足"时触发；PASS/FAIL/其他端点一律原样，不污染正常裁决。
- acyl_glucuronide_risk 属于"结构警示"类端点（`admission_only: true`）：它只给风险分级与
  警示文案，不参与多数投票计票 —— 符合"证据准入先于证据组合"的总纲。
- SAR 轴是**诊断**不是**裁决**：它告诉用户"为什么被动渗透会是瓶颈"，但不替 BBB 端点下 PASS/FAIL。

## v3.2.1（2026-10-29）——工作包 F/K 落地（conformal 验证弃权 + 可靠性分工表）

一句话：**F 和 K 之前只停在"协议/文档层面"，现在真正接成可跑的命令并实跑验证。**
- **F（conformal 区间宽度验证弃权）**：新增 `conformal-scale`（描述符空间 k-NN 难度尺度
  sigma）、`conformal --mode normalized`（变宽区间）、`conformal-check`（UNDETERMINED vs
  PASS/FAIL 宽度分布 + AUC）。关键修正：旧 `conformal` 是绝对残差 split-conformal，**所有
  化合物同宽**，根本无法检验"UNDETERMINED 是否更宽"——必须上 normalized 才让宽度随化合物变化。
- **K（可靠性生态位分工表）**：新增 `landscape`（把 `references/reliability_landscape.yaml`
  渲染成 CSV/Markdown），论文 Discussion 的分工表与 skill 立场保持机器一致，防手改漂移。
- 新增测试 `tests/test_conformal_check.py`（11 断言）、`tests/test_landscape.py`（12 断言）；
  `--help` 覆盖扩到 41 命令。

### F 实跑结论（OpenADMET test，2,282 分子 × 9 端点；两基线当两源 → reliab 混合裁决 → normalized 区间）
- UNDETERMINED 中位宽度 48.6，是 PASS（16.1）的 **2.2 倍**、但**窄于** FAIL（128.6），AUC=0.635。
- 结论档位触发"**证据弱：区间宽度不能替代弃权逻辑**"——conformal 宽度只是弱互证，
  不是独立证明。这正是"不把 F 当新伪精度"的纪律体现（诚实边界已写进 SKILL.md 与输出 note）。

### 纪律细节
- `conformal-check` 自动跳过 `self_calibrated`/`insufficient`/空 width 记录——否则"自我校准的
  窄区间"会把结论拉向反面（校准集分子自身的区间偏窄，不可用于覆盖率/宽度比较统计）。
- 校准集必须是**实测真值**；经验覆盖率是构造保证不是验证；区间只保证边际覆盖、不保证逐分子覆盖。

## v3.2.0（2026-10-29）——工作包 B/G：外部公开数据随包分发 + 真实基准

一句话：**不再只给接入协议**。两个公开数据集已随包分发，skill 可离线跑真实
AUROC/AUPRC 基准；同时修掉一个会让"越高越好"端点 AUROC 系统性 <0.5 的方向 bug。

### 随包数据（`assets/external/`）
- `openadmet/` **OpenADMET-ExpansionRx FULL**（**CC-BY-4.0**，DOI 10.5281/zenodo.21504733）：
  train 5,326 / test 2,282 分子 × 9 个 ADMET 终点；含 `expansion_data_raw.csv`（保留
  `<`/`>` 删失标记与 RLM 额外终点）。约 1.4 MB。
- `npass/` **NPASS 3.0 curated**（学术免费，cite Lin et al. NAR 2026;54:D1519）：
  1,307 个大鼠 LD50 化合物（全部有结构）+ 76 条单位明确的 ADME（PPB/LogD/Clearance）
  + 1,338 个结构；约 240 KB。抽取脚本 `examples/extract_npass.py` 可复现。
- `assets/external/README.md`：许可证、来源、刷新命令、边界。

### 新增模块/命令
- `adt/external.py`：
  - `external --dataset openadmet|npass`：把外部数据转成 compounds/measurements/truth
    + rules + meta；OpenADMET 支持 train/test/raw，NPASS 用 md5 确定性 70/30 切分。
  - `baseline --method rdkit|morgan|both`：train split 训练 Ridge（RDKit 描述符或
    Morgan 指纹），predict test split；产物 `source=baseline_rdkit/baseline_morgan`，
    **是基线不是外部工具**。
  - `oriented_score()`：按端点 shape（up/down/window）把原始预测转成风险分数，
    另存 `*_risk.csv` 供 `benchmark`/`selective` 使用。
- `examples/extract_npass.py`：从官方 105 MB activities / 3.3 MB toxicity / 65 MB
  structures 抽取 curated 子集，只保留单位明确的记录。

### 实例结果（真实实测真值，非 demo）
- **OpenADMET test（2,282 分子 / 10,738 对，9 终点）**：
  - RDKit 基线平均 **AUROC 0.656**；Morgan 基线 **0.730**。
  - 端点级：Morgan 在 MPPB 0.918、KSOL 0.823、MBPB 0.824、MGMB 0.802；
    MLM CLint 0.516 接近随机（与"清除率难预测"的已知结论一致）。
- **NPASS rat-LD50（1,307 化合物；916 train / 391 test）**：
  - RDKit 基线 **AUROC 0.660 [0.595–0.720]**；Morgan 0.562 [0.481–0.643]。
  - 标签：LD50 < 300 mg/kg = FAIL（高毒），阈值为**分析选择**。

### 实跑中发现并修复的 bug（3 个）
1. **方向错位（最严重）**：benchmark 以 FAIL=正类计分，而 KSOL/Caco-2 Papp/% unbound
   是"越高越好"；直接拿原始预测跑，AUROC 系统性 <0.5（Caco-2 Papp 0.272、MGMB 0.196）。
   修复：`oriented_score()` + `*_risk.csv`；修复后同一基线 AUROC 回到 0.66–0.73。
2. **manifest 对目录做 SHA1**：`external` 把 data_dir 传给 `write_manifest` →
   `PermissionError`。修复：只把产物入 manifest。
3. **基线重复解析 SMILES 超时**：每个端点都重算 5k 分子的描述符/指纹。
   修复：每 split 矩阵只算一次，再按端点切片（21.8s / 25.2s）。

### 测试
- 新增 `tests/test_external.py`（25 断言：censor 解析、规则、方向翻转、契约表、
  NPASS 切分、基线形状）；smoke 脚本 44 → **45 个**；help 覆盖 34 → **36 个命令**。

### 诚实边界
- `baseline_*` 是 Ridge 基线，**不是** ADMET-AI/ADMETlab/admetSAR；不能拿它声称
  "本 skill 的预测性能"。
- 评审提到的"NPASS 3.0 三工具基准（201,905 化合物 + 142 Caco-2）"不在官方 NPASS
  下载包中，**未随包分发**；本 skill 分发官方实测 ADME/Tox curated 子集，三工具预测
  可用 `web` 适配器重建。
- NPASS 学术免费；商业使用请自行核对 NPASS 条款。OpenADMET 为 CC-BY-4.0，需署名。

---

## v3.1.0（2026-10-29）——外部评审驱动的"可检验方法学"升级（工作包 A–K）

一句话：**把"证据准入"从工程约束提升为可检验、可比较、可证伪的方法学命题**，
并为每条命题提供可执行的统计入口（独立性、校准计票、弃权、决策价值、DST 对照、
失效频率、结构扰动）。评审意见原文见 `admet-skill/外部评审材料包_v1.md` 的外部回复。

### 新增模块（7 个）
- `adt/independence.py`（A）——同组源对的 Spearman ρ / Fleiss κ；组权重
  （正相关 ρ≥0.90 降半票、0.70–0.90 线性降权；**负相关标 sign_conflict，不当作冗余**）；
  `effective_votes` 暴露"整数两票、有效不足一票半"的伪共识；
  `vote_calibration` 用 Clark 2014 经验版 `u(k)=(err_k+0.5)/(n_k+1)` 估计裁决错误率。
- `adt/certainty.py`（I）——GRADE 式确定性修饰符：`high / moderate /
  low_resolvable / low_unresolvable / medium_needs_experiment`，映射到
  indirectness / inconsistency / imprecision / risk_of_bias 四维；只标注、不改 verdict。
- `adt/selective.py`（H）——risk–coverage 曲线 + 阶梯积分 AURC；结构性弃权 vs
  spread / vote_confidence / **conformal_width（`--conformal`，1/(1+width)）** 三条分数型基线；
  新增**留一源 holdout**（非循环，避免 majority proxy 的循环验证）；n<10 标 insufficient。
- `adt/failure_modes.py`（J）——7 类可自动检测的不变量：unit_isomerism /
  domain_block_unwired / version_drift / phys_range_violation / pseudo_consensus /
  single_group_verdict / silent_empty_source；有标签时输出 precision/recall。
- `adt/perturbation.py`（C）——去盐/中和/互变异构/立体翻转/去立体五种变体；
  默认从 **input_smiles（原始输入）** 出发（用 calc_smiles 会大量 no-op，实验失去意义）；
  描述符位移汇总 + 预测位移/源间分歧比。
- `adt/decision_value.py`（D）——Vickers 决策曲线 + 固定预算三策略
  （vote_all / admission / random）期望效用；分子级状态机（FAIL 支配 > 不可解决 >
  可解决 > 全 PASS），避免"最差端点"把整分子误判成不可用。
- `adt/dst.py`（E）——Dempster/Yager 组合；all-in（域外=ignorance）vs 证据准入；
  统计"DST 判死但框架弃权"的过度裁决。**发现**：θ=1 是 Dempster 单位元，
  与排除等价；真正的过度裁决来自"已登记域外但仍投概率票"的源。

### 新增文档
- `references/09_reliability_landscape.md`（K）——与多数投票/AD/conformal/校准/DST
  的分工表，明确"证据准入先于证据组合"的定位。
- `references/08_literature_map.md` 增第四节：OneADMET 2026、Parrondo-Pizarro 2025、
  Clark 2014、Fleiss 1971、Vickers 2006、GRADE 30、OpenADMET 2026、NPASS 3.0、
  Honest ADMET 2026、TOXTRUST；并列出五条可证伪命题 P1–P5。

### 新增子命令（7 个）
`independence` / `certainty` / `selective` / `failure-modes`（别名 `failmodes`）/
`perturb` / `decision-value`（别名 `dvalue`）/ `dst`。`reliab` 输出新增
`certainty_modifier` 与四个 GRADE 维度列。

### 实例运行中发现并修复的真 bug（6 个）
1. **SaltRemover 返回零原子分子**（RDKit 2026.09）：`rdMolStandardize.SaltRemover`
   不存在（改 `rdkit.Chem.SaltRemover`），且对醋酸钠会把整个盐剥成空分子 →
   改为"按重原子取最大有机片段"，单片段直接返回原 mol。
2. **互变异构规范化丢立体（C4 同类）**：`TautomerEnumerator.Canonicalize` 把
   咖啡酰的 `/C=C/` 弄丢；且 Mol 对象保留失效 stereo 标记、SMILES 才丢 →
   以 **SMILES 往返后**的立体计数为准，丢失时在 note 显式告警"predictions 模式不得直接用"。
3. **零基线相对变化爆炸**：hba 0→1 时 rel_delta=1e9 → 改 0→0 记 0（invariant）、
   0→非0 记空（只报绝对 delta）。
4. **负相关被当成冗余降权**：组权重原用 max|ρ|，ρ=−1 也降半票 → 改用 max 正相关，
   负相关只标 sign_conflict。
5. **AURC 积分约定**：梯形法从 (0,0) 起算把"全错"压到 0.83 → 改阶梯积分
   （0=完美、1=全错）。
6. **规则查找大小写/别名不匹配**：`rules.get("DILI")` 取不到 `dili` →
   统一走 `reliability._match_rule`（selective/decision_value/failure_modes/independence 全部修正）。

### 实例运行关键结果（详见 `学术升级实例分析_v3.1.0.md`）
- independence：12 个源对 / 2 个独立组；descriptor_ml 组 ρmax=0.574 但
  **hERG 上 admet_ai vs admetlab3 ρ=−0.574（方向冲突）**；57 对因 class vs probability
  单位异构被跳过（C78 的触发条件）。
- failure-modes：126 条命中（domain_block_unwired 56 / single_group_verdict 42 /
  unit_isomerism 28）。
- DST：**42/84 条"DST 判死但框架弃权"**——源共享训练生态时 Dempster 把相关证据当独立。
- perturb：去盐使醋酸钠 MW −28%、clogp −71%；中和使甘氨酸 clogp −102%、
  TPSA −6.6%；互变使 2-羟基吡啶 clogp −52%。
- 严格口径下 reliab 84/84 UNDETERMINED（单位异构 + 单组 + class blocks）——
  这是正确行为，也说明 decision-value 在无真值时只能做 proxy 示意。

### 测试
- 新增 7 个测试脚本（independence/certainty/selective/failure_modes/perturbation/
  decision_value/dst），共 **75 条新断言**；smoke 驱动脚本从 37 → **44 个**。
- `test_help_all` 从 25 → **34 个命令**（含两个别名）。

### 未完成（诚实边界）
- 工作包 B（NPASS 3.0 中等规模演示）与 G（OpenADMET 前瞻盲测）需要外部公开数据；
  本 skill 只提供接入协议，不随包分发数据。
- 决策价值/选择性弃权在**无 truth** 时只能做 proxy/holdout，不得写成准确率。

---

## v3.0.0（2026-10-29）——基于 20 篇 SCI 文献的学术化升级

一句话：**把"工程约定"升级为"有文献锚点的方法"**，并在此过程中用敏感性分析
探针抓出一个门控接线缺陷。逐条依据见 `references/08_literature_map.md`。

### 新增模块（4 个）
- `adt/calibration.py` —— 概率端点校准（Van Calster 2019, BMC Med 17:230）：
  Brier/BSS、校准斜率-截距（logistic 重校准 IRLS）、O:E、ECE、Wilson CI 分箱表。
  **量纲门控**：只有概率量纲且值域⊂[0,1] 才启用；percentile/µL/min/mg 一律拒绝。
  `benchmark` 增 `cal_*` 列 + `calibration_table.csv`。
- `adt/conformal.py` —— split conformal（Norinder 2014, JCIM 54:1596）：
  q=第 ceil((n+1)(1−α)) 个绝对残差；n 不足给 ±∞ 而非编窄区间；
  目标分子若在校准集内标 `self_calibrated`，不参与覆盖率统计。
- `adt/governance.py` —— QAF 四原则（OECD 2023, No.386 + DOI 10.1787/d96118f6-en）
  + Hanser 三层 AD（2016, SAR QSAR Environ Res 27:865）+ PROBAST 四域偏倚
  （Wolff 2019, Ann Intern Med 170:51）。新增 `qaf` 子命令。
- `adt/reporting.py` —— TRIPOD+AI 16 条分节自查（Collins 2024, BMJ 385:e078378）
  + 每源 model card（Mitchell 2019, FAT\* '19:220）+ FAIR 13 条映射
  （Wilkinson 2016, Sci Data 3:160018）。新增 `reporting` 子命令。

### 新增数据/文档
- `references/source_cards.yaml`：8 个预测源的 model card（训练数据未披露就写
  not_disclosed；已知失效带案例编号）。
- `references/desirability_method.md`：几何平均为何成立（Derringer-Suich 1980）、
  w 是**指数不是线性系数**、何时不能用 desirability。
- `references/08_literature_map.md`：20 篇 → 模块的逐条映射与优先级依据。

### 修正（纠错，非新增）
- **G2 Peng 2023 纠正 OATP2B1 先验**：新增 `moiety_rules`，芳环氧苷降一档（direct）、
  脂肪碳糖苷弱降半档（extrapolated）；`transport` 输出
  `plausibility_base/plausibility/adjust_reason/adjust_evidence`，只降不升、不外溢。
  本类 14 分子 OATP2B1 medium → low_to_medium（extrapolated）。
- **真实 bug：`reliability.py` 单位异构分支绕过 `require_sources` 门控**。
  原先 class_map 投射方向一致后直接落 PASS 并 continue，导致把 require_sources
  调到 3 时 MMP 仍判 PASS（"两票半"在异构单位端点失效）。修复后 require=3 翻转 9/9。
  **发现路径**：AD 阈值摄动（Sahigara 2012）跑到 require=3 时"应该翻转却为 0"。
- **QAF P1 缺口**：35 个 reference 端点未声明单位 → 全部补齐
  （vNN 分类端点标 `class_0_1`，与 probability 显式区分，进一步加固 C78）。
- **EHR 前提计分修正**：MW 项（Fagerholm 的"阈值不成立"）不再计入满足数，
  否则所有分子凭空多一票、恒为 plausible。

### PBPK 学术化（5 项）
- `eh_well_stirred()` + `well_stirred_selfcheck()`（Pang & Rowland 1977）：四个解析解
  写成可执行断言，`pbpk` 运行时打印 PASS/FAIL（C81 那类错误再也过不去）。
- `ivive_assumptions()`（Obach 2011）：MPPGL/肝重/fu_mic/血浆比/Qh 五项假设显式化 +
  ±2× 敏感性 + `pbpk_academic.csv`。
- `qualification_statement()`（FDA 2018 / EMA 2018）：七段申报口径，
  含"不用于剂量选择/DDI 豁免/替代临床 PK"。
- `ehr_prerequisites()`（Fagerholm 2008）：EHR 三条机制前提 + 信息项不计分。
- `herg_evidence_route()`（CiPA / Li 2019）：声明单通道 IC50 路线与其局限。

### benchmark 扩展（TDC 2021）
- `scaffold_clusters()` Bemis-Murcko 骨架聚类、`scaffold_split()` 整簇切分
  （容量约束 + 空集整簇迁移并声明 `degenerate`）、`load_tdc_truth()` 读 TDC 格式；
  CLI `--scaffold-from/--split/--truth-format tdc/--tdc-endpoint`。
- **实测发现**：14 个王百合苷只有 **2 个 Murcko 骨架** → 自动报
  "本批不能做三集验证，只能用外部化学类做外部验证"。

### tier / sensitize 扩展
- `tiers.assign(..., rob=)`：**PROBAST high 不得升 T3**；`tier.csv` 增
  `risk_of_bias`；`tier --compounds` 可算骨架簇数进 D1。
- `sensitize --ad`：AD 两旋钮（票数门控 × 域外处置）网格化，分别统计
  **翻转 / 新增判定 / 丢失判定**。

### 测试
- 新增 9 套：test_transport_moiety / test_calibration / test_scaffold_tdc /
  test_governance / test_ad_sensitivity / test_pbpk_academic / test_conformal /
  test_desirability_weight / test_reporting。
- 测试总数 **37 套，pytest 37/37**；`--help` 冒烟覆盖 **25 个子命令**（补 merge/qaf/conformal/reporting）。

### 已知限制（本轮新增）
- TRIPOD+AI 条目文字是按分节语义**重写**的索引，不是官方逐字原文。
- 保形预测只给**边际**覆盖，不保证逐分子覆盖；校准集必须实测。
- `calibration` 在 n<30 或某一类<5 时一律 `insufficient`，不返回可疑数字。

## v2.7.0（2026-10-29）——全模块覆盖测试（7 化合物 × 7 类）驱动的修复与补强

用 7 个跨类化合物（咖啡因/APAP/布洛芬/普萘洛尔/姜黄素/咖啡酸/王百合苷 A）跑完
**全部 20 个命令**，覆盖 5 种转运体化学型 + 酸/碱/中性 + 反应性 + 糖苷立体。
四个网页源（ADMET-AI/ProTox/ADMETlab/vNN）全部实跑成功。据运行中发现的缺陷修复：

### F4（真实 bug）`normalize` 碱性氮 SMARTS 误判
- 旧 `!$(N-*)` 本意排除阴离子氮，实际匹配"任何单键相连的 N"，**把所有胺排除** →
  普萘洛尔（仲胺）报 0 个碱性氮。
- 修复为 `!$([N-])` 并显式排酰胺/磺酰胺/腈；面板实测 propranolol=1、caffeine/apap=0。

### F6（真实 bug）`desire` 覆盖不足仍给 geo_mean=1.0
- 旧逻辑 `cov<0.5` 仍写 geo_mean，1 个 PASS 端点即显示 1.0（"满分安全"）。
- 修复：覆盖不足时 geo_mean 留空，`flag=insufficient_coverage` 保留；正常路径（cov≥0.5）不受影响。

### F2（流程断点）新增 `merge` 子命令
- 此前无合并多源长表能力，全流程必须手写项目脚本。新增 `adt.cli merge`：
  按 (compound_id, endpoint, source, source_version) 去重 + `schema.validate` 校验，
  有问题即中止（`--allow-invalid` 可越过但产物不得用于报告）。

### F3（混合面板误伤）`reliab --chemical-class` 默认改为空
- 旧默认 `cinnamoyl_glycoside` 会把糖苷类的 blocked 端点套到混合面板的所有分子。
- 改为默认空（不过滤），并打印提示；单一化学类批次须显式指定。

### 已知限制（记录，未修）
- F1：`admet_ai` 本地模式 `--local` 导入挂起（>45 s）；改用网页端。本地离线待修。
- F5：`state_sensitive` 对酸/碱/可互变异构仍为空（只标注未触发），列为后续优化。

### 测试
新增 `test_normalize_coverage_fixes`（10 断言，F4+F6 负例回归）。
合计 **28 套 429 断言，pytest 28/28**。


## v2.6.0（2026-10-29）——借鉴 reverse-molecular-docking v2.0：四个定量/治理模块

用户提供了另一台电脑自建的 `reverse-molecular-docking` v2.0 全套材料（SKILL/架构/代码/实例），
要求评估可借鉴项并直接引入。核对发现：**治理层（措辞封顶、预注册、依赖分组、三态、饱和扫描、
物理边界）本 skill 早已具备**——`05_qa_gates.md` 第 12 节本就写明"借自外部对接 skill 治理层"，
说明两者同源交叉演进。v2.0 真正的增量是四个**定量/协议**模块，本次全部移植：

### 1. `adt/background.py` — 稳健 Z 背景归一化（移植 E6a）
- `center=median(bg)`、`scale=max(1.4826*MAD(bg), floor=0.30)`、`z=(S−center)/scale`，
  同时输出 `z_sd`；`|z−z_sd|>1.5` 打 `SCALE_CONFLICT`（**不得静默取一个值**）。
- 按规则 `shape` 定向：`up→+z`、`down→−z`（`z_favorable` 正=更优）；`window/step` 只报 |z|。
- 两种背景：`--bg` 外部长表（跨化学型）/ `--within-set` 留一法（本批内谁离群）。
- **单位守卫（C78 同源）**：背景按 (endpoint, unit) 分组，概率与类别 0/1 不混算。
- 缺失语义：域外/失败 `flag=missing`，不赋分。

### 2. `adt/rank.py` — bootstrap 名次区间 + 并列集合（移植 E7c）
- 仅当 `can_rank` 三条件满足才允许排名；否则默认**拒绝**（写空表），`--force` 才计算且产物标 `OVERRIDE`。
- 按端点/轴 bootstrap 重采样 → 名次 5–95% 区间；成对胜率**按每 replicate 的 composite 计算**
  （相等记 0.5 胜，否则两个相同分子会因排序位置不同被误判为非并列）；胜率落在 [0.4,0.6] 判并列。

### 3. `adt/benchmark.py` — 独立分类基准（移植 E8，**按分类域改造**）
- 反向 skill 的 hit@k/MRR/库外拒答是**检索**指标；ADMET 是**分类**，主终点改为
  **AUROC / AUPRC + 按化学簇聚类 bootstrap CI**，拒答改为**真阳性覆盖率**。
- 消融：**多源中位数（共识） vs 均值（朴素投票）** 的 AUROC 差。`--demo` 生成 3 个不同噪声源，
  仅验证指标与消融代码（输出打 DEMO 横幅，不得作科学结论）。

### 4. `adt/tiers.py` — 运行档位 + 项目级结论封顶（移植 E0/门控状态机）
- **T1 探索 / T2 决策 / T3 发表** → 结论上限 `exploratory_only / decision_support / publication`。
- 规则：T3 = 实测≥1 且独立基准可算 且 有覆盖矩阵；T2 = 实测≥1 或 ≥1 端点 2 独立组；余 T1。
- `enforce()` 拒绝越级；`tier`/`gate` 子命令输出当前档位 + 升级缺口。
- 与行级 `phrasing.allowed_statement()` 叠加：行级管每句话，项目级管整篇上限。

### 5. 顺带（本地材料整合）
- `pbpk.mc_rank_probability()`：MC 参数不确定性下的**P(暴露前3)/P(后3)/平均名次**
  （移植外部会话 exp8-A；`mc_convergence` 此前只返回中位数，无排名概率）。
- `06_in_silico_playbook.md` §1.4：把旧 t½ 5.9–10.5 h 与现行 `pbpk` 的 1.6–2.0 h 并列并说明
  差异来源（CLint 输入不同），避免误引陈旧锚点。

### 测试
新增 6 套：`test_background`(11) / `test_rank`(10) / `test_benchmark`(11) / `test_tiers`(14) /
`test_help_all`(21 个子命令 --help 冒烟，防 argparse `%` 崩溃类静默缺陷) / `test_pbpk_mcrank`(7)。
合计 **27 套 419 断言，pytest 27/27**。


## v2.5.0（2026-10-29 09:55）——肠肝循环（EHR）结构层 + 转运体先验层

用户问"把转运体/肠肝循环这部分实验加进 skill 有意义吗"。答案分两半：
**EHR 是机制，可以建模并量化边界；转运体动力学没有任何计算源，只能建"测什么"的先验。**

### 1. PBPK 加肠肝循环（结构层）

- `adt/pbpk.py` 从 11 状态扩到 **12 状态**（新增胆汁房室）。肝消除拆成
  `elim_liv_total = clint·c_liv` 的两条出口：代谢 `(1−fbile)` 与胆汁 `fbile`；
  胆汁以 `kbile`（默认 0.4/h）排入肠腔，其中 `fre` 被重吸收回门静脉、其余进粪便。
- 关键设计：**总肝清除不变**，只改出口 → 因此 `fre=0` 时模型严格退化为"无 EHR"。
  这条不是装饰，是可测的**不变量**（`test_pbpk_ehr.py` 的 I1：AUC 偏差 <1e-9）。
- 新增 `pbpk.ehr_scan()` + `adt.cli pbpk --ehr-scan`：跑 fbile×fre 网格，
  输出相对基线的 AUC/t½/Cmax 放大倍数。CLI 新增 `--fbile/--fre/--kbile`。

### 2. 转运体先验层（决策层，**不是预测**）

- 新增 `references/transporter_priors.yaml`：5 个化学型（葡萄糖苷 / 肉桂酰酯 /
  邻苯二酚 / 愈创木基 / TPSA>140）× 7 个候选转运体，每条带 `rationale`、
  `evidence_level`、**`recommended_assay`（细胞系+浓度+抑制剂+判据）**。
- 新增 `adt/transport.py` + `adt.cli transport`：按化学型给每个分子输出先验表，
  并在每条记录里写死 `predictive_value = none（不得进 reliab 计票）`。
- 明确声明 `data_availability.in_silico_sources: none`：ADMETlab 只有 5 个肝/胆侧转运体，
  ADMET-AI 只有 Pgp 抑制剂数据集，vNN 本类 14/14 NoPrediction。
- 新增 4 个回填端点（role=reference）：`transporter_oatp2b1_uptake`、
  `transporter_sglt1_uptake`、`fraction_excreted_bile`（= fbile）、
  `ehr_reabsorption_fraction`（= fre）。

### 3. 两个新缺陷（都是自己写出来的，已固化）

- **C86（结构改动的隐形破坏）**：给 ODE 加房室最容易"算错但看不出来"。
  这次靠三条不变量锁住：fre=0 ≡ 无 EHR（AUC 偏差 <1e-9）、fbile=0 时 fre 无效、
  fre 单调增；外加质量守恒 <1e-6。**没有这三条，EHR 版和 v2.4 的结果无法对账。**
- **C87（SMARTS 松模式误判化学型）**：邻苯二酚最初写成 `c1cc(O)c(O)cc1`，
  把**愈创木基**（4-OH-3-OMe）也算成邻苯二酚 → 8 个分子被标 PAINS/邻苯二酚，
  实际只有 C/E/K/L/M 5 个。改用 `[OH1]c1ccccc1[OH1]`（显式两个羟基）后与既有结论一致。
  同源问题：`summarize()` 把"行数"当"分子数"（同分子多化学型重复列同一转运体），
  已改为按分子去重取最高 plausibility。

### 4. 实例运行结果（14 分子）

- **EHR 扫描 168 组合**（14 × 4 fbile × 3 fre）：`fbile=0.6/fre=0.8` 时
  **AUC 平均 ×1.87、t½ ×2.43、Cmax 仅 ×1.13**；单分子最大 N 的 AUC ×1.90（t½ 1.60→4.03 h）。
  **结论：EHR 改终末相而不改峰浓度** → 用 Cmax 做的暴露/hERG 裕度结论对 EHR 缺口稳健，
  但"t½ <2 h、需频繁给药"可能偏悲观（最多差 2.4 倍）。
- **转运体先验 111 条**：OATP2B1 / MRP2-BCRP / OATP1B1-1B3 / 通用原则各命中 14 个分子
  （medium 及以上）；**SGLT1 与 P-gp 命中 14 个但 plausibility=low**（medium 及以上 0），
  MCT/LAT 只 5 个（邻苯二酚组）。

### 5. 测试

- 新增 `tests/test_pbpk_ehr.py`（23 断言：3 不变量 + 极端组合守恒 + "EHR 不改 Cmax" + scan 结构）
- 新增 `tests/test_transport.py`（22 断言：化学型识别/邻苯二酚 vs 愈创木基/实验处方必填/
  非预测声明/按分子去重/无源声明）
- 合计 **22 套 345 断言**，`pytest -q` 21/21。

## v2.4.1（2026-10-29 09:30）——hERG IC50 证据锚定 + 多剂量窗口

用户要求 A（hERG IC50）与 B（剂量扫描）并行做。两项都可由计算完成，A 用
「类似物实测锚点」替代一次湿实验。

### A. hERG IC50：三个计算源都给不了浓度，只能锚定

- **C83（"记录存在 ≠ 有可用的数"）**：14 个目标分子的 ChEMBL 邻居 hERG 记录 **0 条**；
  类似物里咖啡酸的 1 条记录**类型是 `Potency` 不是 IC50**（2.51 µM，qHTS 平台），
  CAPE 的 2 条 IC50/Ki 记录**数值为 None**。若只看"有没有记录"会得出"有数据"的错觉。
- **新增资产 `assets/herg_reference_ic50.csv`**：10 个类似物实测值 + 证据分级
  （`abstract_verified` / `chembl_potency` / `secondary_review`），含
  CAPE 10.6 µM（咖啡酸苯乙酯，**与本项目咖啡酰酯骨架最接近**）、
  taxifolin 3-O-葡萄糖苷 9.6 µM、EPMC（肉桂酸酯）53 µM、curcumin 5.55 / >100 µM、
  咖啡酸 2.51 µM，以及 atractylodin 26.4 / β-eudesmol 33.4 / naringenin 36.5 /
  ligustilide 37.3；人参皂苷 Rg3 为**激动剂**、EGCG 为 PAINS。
- **新增 `pbpk.evidence_ic50_anchor()`**：取与咖啡酰/肉桂酸酯骨架最接近的 3 个
  （2.51 / 10.6 / 53）**几何均值 = 11.2 µM**（全集 10 个中位 29.9 µM）。
- **C84（单点 IC50 不确定度 ≥10×）**：curcumin 手工膜片钳 5.55 µM vs 自动化平台
  >100 µM，**同分子差 20 倍**。→ 明确纪律：**只报档位，不报精确 Margin**。
- **C85（糖苷不必然是阻断剂）**：人参皂苷 Rg3 是 hERG 激动剂（EC50 0.4 µM）；
  taxifolin 糖苷最大抑制仅 **36.9%** 即平台（relative IC50）；CAPE 在动作电位钳下
  反而**增大** I_hERG。→ 用尾电流 IC50 算的 Margin 对门控调节/部分阻断型**偏保守**。
- 规则新增 `herg_ic50_lit_anchor`（role=reference, unit=uM），把上述证据与三条警示写入 note。
- **对既有结论的影响**：E15 的 **10 µM 档站得住**（CAPE 10.6、taxifolin 糖苷 9.6）；
  **1 µM 档无类似物支持**（最接近的低值是 2.51 且非 IC50）。

### B. 多剂量扫描（10–400 mg，6 档）

- 项目脚本 `e16_dose_scan.py` → 84 行（14 分子 × 6 剂量），产物 `dose_scan.csv`、
  `dose_window.csv`；`e18_herg_ic50_anchor.py` 按证据锚点重算剂量上限。
- **自校验**：质量守恒最大误差 **3.9×10⁻¹⁵**；剂量线性（Cmax/dose、AUC/dose 变异系数）
  **14/14 全部 <1%** → 线性动力学成立、可外推。
- **结果**：100 mg 时 Cmax 仅占 IC50（11.2 µM）的 **1.2–4.0%**，Margin **25–86×**；
  Margin≥30 的剂量上限 **J 84.1 mg，其余 152.1–285.6 mg**。
  **400 mg 时全部失守**（J 5.6 FAIL，其余 10.2–19.1 TIGHT）→ 本系列没有"加量换暴露"的空间。
- **决策分叉点**：若 IC50 真是 2.51 µM（最坏情景），J 只能 18.8 mg、其余 34.1–64.0 mg
  → **100 mg 全部不合格**。所以"测 J + 一个代表的 IC50"是剂量策略的分叉点，不是可选项。

### 其他

- 新增 `tests/test_herg_anchor.py`（17 断言：资产分级、关键数值、平台差异 ≥10×、
  锚点计算、与 Margin 对齐、缺资产优雅降级）。
- 合计 **20 套 300 断言**，`pytest -q` 19/19。

## v2.4.0（2026-10-29 08:40）——PBPK 收编 + 安全裕度反推（安全端点接进暴露框架）

两件事一起做：把项目脚本的 PBPK 收编为 skill 能力，并把**安全端点接进暴露框架**
（此前 exposure 与 safety 两层互不相通）。

- **新增 `adt/pbpk.py` + `adt.cli pbpk`**：10 状态灌注限制模型（肠腔/肠壁/门静脉/肝/血浆/
  肾/肌肉/脂肪/富血流/其余），参考生理取自 ICRP/Brown 1997，LSODA 积分。
  **三项强制自校验内建**：质量守恒 <1e-4、CLint×2 排序 ρ≥0.9、MC 折半收敛 <0.05。
- **安全裕度反推**：`Margin = IC50/Cmax`（fu 在分子分母同源约掉，见 `margin_table` 注释），
  按 Redfern 分档（<10 FAIL / 10–30 TIGHT / 30–100 OK / ≥100 WIDE），并给出
  `dose_at_margin = dose × Margin_now / target`（线性动力学）→ **"要在裕度 30 以内，剂量上限是多少"**。
- **14 分子实测（100 mg，IC50 取 1/10/30 µM 三档假设）**：
  - IC50=**10 µM**（最坏情形假定）：裕度 **41–76×（OK）**，**只有 J 22×（TIGHT，仅危及生命适应症）**；
    Margin=30 的剂量上限 **J 75 mg**、其余 136–255 mg。
  - IC50=**1 µM**（若真是强阻断剂）：全部 **2–8×（FAIL）**，剂量上限仅 7–25 mg
    → **若这类化合物碰巧是强 hERG 阻断剂，100 mg 口服就不可接受**。
  - IC50=**30 µM**（极性糖苷更可能）：全部 **68–229×（WIDE/OK）**。
- **两条曲线互相印证**：PBPK 的 F 与 E13 的 F 比值 14/14 落在 0.80–0.88（系统性差 14%，
  PBPK 多算肾清除+组织分布），Cmax 131–445 nM 与既有工作锚点 131–400 nM 同量级。
- 测试：`tests/test_pbpk.py` 19 断言（守恒/剂量线性/t½/裕度分档边界/反推自洽/物理边界/极端输入）。
  合计 **19 套 283 断言**，`pytest -q` 18/18。

## v2.3.9（2026-10-29 06:50）——五问题复核：域外端点终于接线（C82）

用户要求复核对"会写错结论"的五个问题。**逐条读代码 + 跑当前数据**核完：
ESOL 系数（✅ 正确，MAE 复算 0.48）、ProTox Probability 语义（✅ 用 Prediction 入表、
Probability 只进 note）、DeepPurpose（✅ background_only 且长表 0 行）、
ProTox LD50（✅ 有 `ld50_reliability` 标记）、
**ADMETlab DILI/Ames 域外 → 唯一真缺陷，已修**。

- **C82（"写了但没接线"再犯）**：registry 的 `blocked_endpoints_in_class` 登记得很完整
  （ADMETlab DILI 14/14 0.643–0.914、Ames 14/14 0.830–0.990；ADMET-AI 侧 0/14 与 7/14），
  但 **`grep` 全代码库无任何读取点**。后果不是少个字段，而是**结论理由错**：
  DILI 的判读理由写成"源间分歧过大（极差 0.746）"，读起来像两源意见不合，
  实际是"ADMETlab 在本类无区分度"。
  修法：新增 `reliability.apply_class_blocks()`，在 `reliab` 入口按 registry 命中行置
  `out_of_domain`（note 附证据），并打印拦截清单（本次 4 组 × 14 行）；
  加 `--no-class-blocks` 对照开关；`tests/test_class_blocks.py` 10 断言。
- 修后 DILI 理由变为"域内源 1 个但独立方法组仅 1 个"、Ames 变为"全部源域外"。
- 测试：**18 套 264 断言**，`pytest -q` 17/17。

## v2.3.8（2026-10-29 02:20）——物理边界守卫（C80）+ 暴露估计的公式自校验

做筛查级暴露估计时，验证环节抓出两个"数值存在但无意义"的问题：

- **C80（物理不可能值）**：ADMET-AI 的 `Clearance_Microsome_AZ` 在 **APAP 上给 −4.3**、
  甘氨酸 **−31.4**、磷酸乙醇胺 **−10.3**（负清除率），7 个试点分子里 3 个。
  若放行，well-stirred 会算出 Eh<0 → Fh>1，口服暴露估计直接失真。
  - 规则新增 **`phys_range`**（clint_microsome [0,5000] / ppb_fu [0,100] /
    caco2_papp_ab [−12,0] / 概率类 [0,1]）；
  - 裁决层过滤越界值：全越界 → UNDETERMINED 且 reason 写"全部 N 个值越物理边界"，
    部分越界 → 只用合法值并在 reason 记"另有 k 个已剔除"；
  - 新增 `reliability.in_phys_range()` 供下游计算（PBPK/暴露）**共用同一判定**，
    避免"裁决挡掉、下游照用"的两套标准；
  - `tests/test_phys_range.py` 14 断言。
- **well-stirred 公式自校验（教训非代码）**：首版把 fu 乘在 Qh 上，Eh 从 0.34 被抬到 0.80
  （Fh 0.66→0.20）。**量纲检查发现不了这类"参数挂错位置"**，只有教科书算例能发现
  （fu=1 且 CLint_b=Qh 时 Eh 必须 = 0.500）。已写入 `references/06_in_silico_playbook.md`。
- 测试：**17 套 254 断言**，`pytest -q` 16/16。

## v2.3.7（2026-10-29 01:20）——429 守护首次实战成功 + C73 数据修正收尾

- **`admetlab_until_success.py` 实战验证**：14 分子，00:49 启动，第 1–3 次均 post-429，
  **第 4 次（01:12，第 23 分钟）成功**，产出 126 行长表 + 原始宽表。
  → ADMETlab 封禁窗口在 **20 分钟量级**，7–8 min 一轮、4 轮内必中；这比进程内堆退避更可靠。
- **C73 收尾（结构错一行、结论错一档的实例）**：`backup_v4` 的 M 行是旧 M（位置异构体）。
  用 v5 结构重跑后 M 的变化：**`nr_ar_lbd` 0.146 → 0.720（Δ +0.574，低风险变高风险级）**、
  `carcinogenicity` 0.354 → 0.215、`sr_are` 0.513 → 0.417（跨过 0.5）、
  `caco2` −6.04 → −6.14、`PPB` 61.4 → 64.2（% bound）。
  → 再次确认：**换结构后指纹/图模型类端点必须整批重跑**，不能沿用旧批宽表。
- 并入后：`merged14_v231/measurements_merged.csv` = **504 行 / 14 分子 / 22 端点**
  （vNN 210 + ADMET-AI 168 + ADMETlab 126），`validate` 0 问题；L6 端点由 13 补齐到 14。
  严格口径裁决不变（只有 `mmp` 可判：PASS 9 / UNDET 5）。

## v2.3.6（2026-10-29 01:10）——"ChEMBL 补第二组"实测否证 + 湿实验方案

用户批准"把 ChEMBL 邻居实测分位升为质量端点以恢复三项判决"。**先验证后动手**，结果这条路不成立：

- **C79（否证）**：14 分子在 ChEMBL 各有 180–340 条邻居活性记录，但
  **ADMET 实测（Caco-2/蛋白结合/微粒体清除）合计 0 条**——邻居全是 GI50/IC50/细胞毒。
  A 甚至有本体（Tanimoto 1.000），其记录也只有细胞毒。
  → **本化学类无法靠 ChEMBL 给三项湿实验替代补实验第二组**（不是白名单太窄，是类内没有这些测定）。
- **新增端点 `chembl_admet_assay_count`**（role=applicability，unit=count）：
  邻居中 ADMET 实测记录数；为 0 时适配器直接打印警告并写 `meta.n_admet_assays`，
  避免"接口能出数"被误当成"本类有数据"（咖啡因/APAP 有 PPB 是因为它们是已上市药）。
- 关键词表补 **PAMPA / MDCK / 半衰期**（原先漏了 PAMPA——它恰恰是渗透性的独立实测方法）。
- 新增 `tests/test_chembl_admet_count.py`（16 断言）。合计 **16 套 250 断言**。
- 交付两份项目文档：`web_results/merged14_v231/ChEMBL第二组可行性_否证.md`（含 14 行证据表）、
  `admet-pipeline/湿实验最小方案_三项.md`（Caco-2 双向 / HLM CLint / 平衡透析 fu，
  含验收标准、对照品、样品量估算、回填 CSV 格式与命令）。

## v2.3.5（2026-10-29 01:05）——严格口径：单组不下判决 + 类别/概率不得混算

用户要求"把 MMP/CLint 的 require_sources 从 1 提到 2"，执行时暴露出两个更深的缺陷。

- **严化**：`caco2_papp_ab` / `ppb_fu` / `clint_microsome` 的 `require_sources` 1 → **2**
  （`mmp` 本来就是 2）。后果如实记录：这三项从"有判决"退回 **UNDETERMINED 14**，
  值保留在报告的"单组证据"段。
- **报告新增"单组证据"段**：严格化后信息不能丢——列出唯一方法组给出的
  `endpoint=value unit（组名）`，明确标"不作判决，仅作参照"。这样"严格"不等于"没用"。
- **C77（默认值错误，影响面最大）**：`require_sources` 的代码默认是 **1**，而文档写的是
  "两票半"（2 个独立组）。结果 `nr_ar_lbd / sr_p53 / sr_are` 这些没写 require_sources 的端点
  **仅凭 ADMETlab 单源就被判 PASS/FAIL**，而同一张表里显式写了 2 的 `carcinogenicity` 却拒判——
  自相矛盾。已把默认改为 2；需单组可判者必须显式写 `require_sources: 1`。
- **C78（把类别当概率算中位数，产出假 PASS）**：vNN 的 hERG/MMP 输出是**类别 0/1**
  （`unit=class`），ADMET-AI 是**概率**。旧代码直接对 `{0, 0.224, 0.029}` 取中位数得 0.029 → PASS。
  本地版因 hERG 概率比网页低 0.14，恰好把极差压到 spread 守卫 0.30 以下，
  **漏出 6 个假 PASS**（网页版因极差 >0.30 侥幸未中）。
  修法两层：① 域内源单位不一致时**禁止取中位数**；② 规则新增 `class_map`
  （{"0": PASS, "1": FAIL}），逐源先投射到 PASS/FAIL 再比方向——一致才采用，
  方向相反或任一源落灰区即 UNDETERMINED，无 class_map 则拒判并提示补规则。
- 已给 `mmp / dili / herg / ames` 补 `class_map`。
- **严格口径下的实测结论（两版一致）**：全项目**只有 `mmp` 可判**（PASS 9 / UNDET 5），
  其余端点全部 UNDETERMINED。caco2/ppb/clint 需第 2 个方法学独立组才能恢复判决。
- **本地 vs 网页**：数值有系统偏移（Caco2 +0.53 log、PPBR −3.5%），但**严格口径下结论完全相同**
  —— 所以选哪版只影响可复现性，不影响结论（详见 `local14_v234/本地vs网页_严格口径对照.md`）。
- 新增 `examples/admetlab_until_success.py`：429 守护（指数间隔 + 可续跑 + 每次尝试留痕），
  成功判据是"长表有行"而不是 HTTP 200（C76）。
- 测试：新增 `tests/test_strict_and_mixed_units.py`（11 断言）。合计 **15 套 234 断言**。

## v2.3.4（2026-10-29 00:45）——ADMET-AI 本地离线模式（真正摆脱网页端）

- **`web --source admet_ai --local`**：走 PyPI 包 `admet-ai==2.0.1` + Chemprop 2.3.1
  在本机推理，**不需要任何网络**。实测：装好权重后 14 分子 **0.8 s**（模型加载 ~13 s 一次性）；
  用死代理（`HTTP_PROXY=127.0.0.1:9`）模拟断网，预测照常成功 → **确认真离线**。
  环境：`pharma-tools/envs/admetai_local`（torch 2.14.1+cpu / chemprop 2.3.1 / admet-ai 2.0.1）。
- **C74（版本混用陷阱，最重要的一条）**：本地包与网页服务**不是同一套权重**。
  14 分子实测（本地减网页）：分类端点几乎一致（DILI Δ=−0.001、SR-MMP Δ=+0.011、
  hERG Δ=−0.141），但**回归端点系统性偏移**——`Caco2_Wang` **+0.53 log**
  （范围 +0.35~+0.74，14/14 同向）、`PPBR_AZ` **−3.54%**、`Clearance_Microsome_AZ` 中位 +3.8 但范围 ±6.6。
  因此本地模式 `source_version = "2.0.1-local"`（网页为 `"2.0"`），**同一张表里混用会被立刻发现**。
  规矩：**一个分析只用一个来源**；本项目既有结论基于网页值，切换本地必须整批重算。
- 适配器新增 `fetch_local()`：以子进程调独立环境的 `ADMETModel()`，回传 wide rows，
  其后仍走**同一套** `TRANSFORMS` + `unit_for()`（保证换算与单位不会两套实现）。
  失败时为 0 行 + 明确报错（实测首版漏 `import os` 时如实报 `name 'os' is not defined`，未编造数据）。
- 测试：`test_units_and_transforms.py` 增至 **22 断言**（新增 4 条：两模式 version 必须可区分）。
- 合计 **14 套 223 断言**。

## v2.3.3（2026-10-29 00:20）——三项湿实验替代真正接线（Caco-2 / PPB / CLint）

**动机**：用户问"ADMETlab 429 时替代路径还需要直连网页端吗"。核查发现两件事：
① 三项替代在 skill 里**只接了 1/3**（只有 CLint，Caco-2 与 PPB 从未进长表）；
② 就算接了，`caco2_papp_ab` 的量纲也是错的（线性阈值 vs log 值 → 恒判 FAIL）。

- **C70（"写了但没接线"的新实例）**：`references/endpoint_aliases.yaml` 里
  `Caco2_Wang` / `PPBR_AZ` / `caco2` / `PPB` 四列全在 `unmapped` 名单里，
  长表只有 DILI/hERG/Ames。**声称"替代三项湿实验"，实际只有 CLint 一项在管线内**。
  现已全部映射：`Caco2_Wang|caco2 → caco2_papp_ab`、`PPBR_AZ|PPB → ppb_fu`。
- **C71（量纲错配，会导致系统性误判）**：`caco2_papp_ab` 原写
  `unit: cm/s, fail 1e-6, pass 5e-6` + 一个**没有任何代码读取的 `scale` 字段**；
  而 ADMETlab `caco2` 与 ADMET-AI `Caco2_Wang` 给的都是 log10 值（−6.5）。
  `−6.5 < 1e-6` 恒成立 → 若照原规则跑，**14/14 全判 FAIL 且看似合理**（最危险的一类错）。
  已改为 `unit: log10(cm/s), fail −6.0, pass −5.3` 并删死字段。
- **C72（单位硬编码）**：`admet_ai` / `admetlab3` 两个适配器都把单位硬写成
  `"probability"`，于是 CLint 的 23.6 µL/min/mg 在长表里标成了概率（v2.3.2 引入）。
  新增 `adt.endpoints.unit_for()`——**单位只有规则表一个真源**，适配器禁止硬编码；
  非概率端点必须在适配器的 `TRANSFORMS` 里显式换算值。
- **C73（旧结构混入）**：`admet-pipeline/web_results/backup_v4/admetlab_results.csv`
  的 14 行里，M 那一行是**旧 M（位置异构体）**，与 v5 定稿结构对不上（canonical 匹配失败）。
  离线复算时该行被正确丢弃（13/14 匹配），**没有把旧结构数据混进定稿结果**。
  这也说明"14/14 ADMETlab 预测成功"这句话当时并不准确：M 用的是作废结构。
- **`AdmetlabAdapter.to_measurements(rows, prov, can2id)`**：抓取与转换解耦，
  已落盘的宽表可离线复算，**不必重新提交**（429 时这就是唯一可行路径）。
- **14 分子实测裁决（三源合并 495 行 / 22 端点）**：
  `caco2_papp_ab` **FAIL 13 / UNDETERMINED 1**（J 落在 −6.0~−5.3 灰区）；
  `ppb_fu` **PASS 14**（fu 30–39%）；`clint_microsome` **PASS 7 / UNDETERMINED 7**。
  三者 `confidence` 均为 low（ADMETlab + ADMET-AI 同属 descriptor_ml，只算 1 票）。
  M 只有单源（ADMETlab 旧结构行被弃）→ reason 如实写"1 个域内源"。
- 测试：新增 `tests/test_units_and_transforms.py`（18 断言：映射一致、单位真源、
  log 量纲、%bound→fu 方向、APAP/caffeine 文献值核对）。合计 **14 套 219 断言**。

## v2.3.2（2026-10-28 23:58）——两项判据按文献定案

- **CLint 单位核实 → 升级**：TDC 定义 `Clearance_Microsome_AZ` 单位 mL·min⁻¹·g⁻¹，
  与 µL·min⁻¹·mg⁻¹ **数值等价**（1 mL/min/g = 1000 µL/min ÷ 1000 mg）；hepatocyte 列为
  µL/min/10⁶ cells 不可混用。撤销 `clint_microsome_admetai` 参照端点，
  改映射到 `clint_microsome`（quality，`require_sources: 1` 显式单源 → confidence 必 low）。
  **裁决：PASS 7 / UNDETERMINED 7**（<30 PASS，30–100 灰区）。
  note 保留外推警告：高极性糖苷实测 CLint 通常偏低，本批 23.6–50.2 偏高，
  只能作相对快慢参考，不得写定量清除结论。
- **MMP 阈值改三区带**：依据 ADMET-AI 官方说明"分类端点 0.5 是惯例且 arbitrary、
  0.55 与掷硬币无异"+ Tox21 活性判定本身基于 qHTS 曲线类（非概率 0.5），
  把 `mmp` 从 `step fail 0.5` 改为 **`down pass 0.3 / fail 0.7`**（0.3–0.7 → UNDETERMINED）。
  本批结果不变（PASS 9 / UNDET 5），但未来 0.3–0.7 区间不再被强行二分。
- C68 结论更新：原判"单位未核 → 只能参照"，现单位已证 → 解除限制并升级；
  但**保留外推风险提示**（单位对 ≠ 数值可用）。
- 测试：`test_rules_roles.py` 扩到 16 断言（三区带、require_sources=1、单位换算记录）。
  合计 **13 套 201 断言**，`pytest -q` 12/12。

## v2.3.1（2026-10-28 23:55）——MMP 升级为质量端点（数据驱动，一次评估 4 个候选）

**方法**：批量评估 4 个"缺阈值/缺第二组"的候选端点，文献锚定 + 14 分子双源实测后直接执行。

- **MMP → 升级为质量端点**（`mmp`，step fail 0.5，require_sources 2）：
  第 2 独立组 = ADMET-AI `SR-MMP`（descriptor_ml）；vNN MMP 为 neighbor_qsar。
  文献：Tox21 SR-MMP 二分类（qHTS class 1/2 + efficacy>50%；10K 库 11% 降 MMP）。
  实测：两源重叠 9 分子**方向 9/9 一致**（ADMET-AI 概率 0.016–0.060）。
  裁决：**PASS 9 / FAIL 0 / UNDETERMINED 5**（后者因 vNN 域外只剩单组）。
  → 本系列**第一个真正进入安全层裁决的新增端点**。
- **CYP 抑制（5 个）**：vNN 14/14 NoPrediction → 单组 + 无阈值共识 → **保持 reference**；
  同时把 `vnn_cyp*` 改为**源中立**命名 `cyp*_inhibition`，两源数据同表可比。
- **微粒体清除率**：ADMET-AI `Clearance_Microsome_AZ`（23.6–50.2）**单位未核**，
  按"不确定不套阈值"原则建 `clint_microsome_admetai`（reference，unit=unknown，C68）。
- **Pgp 底物**：两源重叠仅 3 个分子，且 TDC 的 `Pgp_Broccatelli` 是**抑制剂**数据集、
  vNN 该列是**底物** → 语义不一致，**不升级**（记录理由，避免以后有人硬凑）。
- 新增 `tests/test_rules_roles.py`（14 断言）：把"谁能投票/谁只能报告"变成可执行契约。
- 测试 **13 套 199 断言**，`pytest -q` 12/12。

## v2.3.0（2026-10-28 23:55）——vNN 全端点进入裁决管线 + 覆盖率矩阵

**变更动机**：v2.2.2 只把 3 个质量端点 + MRTD 放入长表，其余 11 个只留在宽表里，
"全 NoPrediction"这个结论无法被 report 自动引用。本次让 15 个端点**全部进入管线**，
同时用覆盖率矩阵把"有没有值"和"值可不可信"分开。

- **15 个端点全部映射**：`DILI/hERG/AMES` → 质量端点；其余 12 个 → `vnn_*` 参照端点
  （`03_endpoint_rules.yaml` role=reference，reliab 输出 PASSTHRU、不进轴聚合）。
  **升级为质量端点的两个必要条件**：① 有文献阈值；② 有第 2 个独立方法组。
- **新增 `adt/coverage.py` + `adt.cli coverage`**：端点级覆盖率矩阵
  （source × endpoint：n / 可判 / 域外 / 实测 / coverage / flag）。
  flag 四态：`usable` / `insufficient_coverage` / `no_prediction` / `no_data`，
  其中 `no_prediction` 的 note 明确写"不得读作阴性"；整源平均覆盖率 <0.30 → `background_only`（G6）。
- **14 分子实测（v2.3 口径）**：vNN 整体覆盖 **0.171**（15 端点含 MRTD，36/210），
  可判端点 **3/15**（herg 0.643、vnn_mmp 0.643、vnn_mrtd 1.0），**10 个端点全零**。
  `dili` 0.071（仅 A）、`vnn_pgp_substrate` 0.214（F/G/N）判 insufficient_coverage。
  → 即使全部端点进管线，vNN 在本化学类上对质量端点仍**无法独立形成结论**
  （reliab 实测：dili/herg 因单方法组判 UNDETERMINED，ames 全部源域外）。
- 测试：新增 `tests/test_coverage.py`（9 断言）；`test_vnn_parser.py` 扩到 20 断言
  （15 端点全映射、无未映射项）。
- 合计 **11 套 185 断言**，`pytest -q` 11/11。

## v2.2.2（2026-10-28 23:30）——14 分子重跑 + 原始结果留档

- **C67（数据完整性）**：适配器原实现只把 3 个质量端点 + MRTD 写进长表，
  CYP×5/BBB/Pgp×2/Cytotoxicity/HLM/MMP 被**丢弃** → 重跑对账时表现为
  "12/15 变化"（其实是"新表里没有"）。修复：`save_raw()` 把**完整 15 端点**
  落 `vnn_wide.csv`、结果页落 `vnn_checkjob_<hash>.html`。
  **原则：不参与裁决 ≠ 不保存。**
- **14 分子重跑结果（2026-10-28，自动分两批 10+4，分别 76 s / 56 s）**：
  与 2026-10-27 旧结果**逐格一致 210/210 = 1.000**，覆盖率同为 0.112（14 分类端点口径）。
  端点分布完全复现：DILI 仅 A=Yes（13 个 NoPrediction）；hERG 9/14 全 No；
  MMP 9/14 全 No；Pgp_substrate 仅 F/G/N（均 No）；AMES/CYP×5/Cytotox/HLM/BBB/
  Pgp_inhibitor 全 NoPrediction；MRTD 14/14 有值（240–291 mg/day）。
  → **该源在本化学类上的结论是批次稳定的**（同账号、间隔 1 天）。
- 新增 `admet-pipeline/compare_vnn_v22.py`（跨批次逐格对账，支持宽表/长表输入）。
- 测试：`test_vnn_parser.py` 增至 18 断言（新增 save_raw 留档 5 条）。

## v2.2.1（2026-10-28 23:20）——vNN 收编完成（端到端验证）

用户提供账号后，把 v2.2.0 的"人工桥"升级为**可用的全自动适配器**，并抓出两条新教训：

- **vNN 全链路实证**：登录（`POST /login`，失败判据 `login.xhtml?status=error`）→
  ALTCHA 求解（sha256 自校验）→ 同视图逐个 add（total 必须 +1）→ ajax 提交拿到
  `<redirect ...checkjob.xhtml?myjob=hash>` → 轮询 → 解析。实测 2 分子作业 **89 s** 出结果，
  产出 8 行长表：APAP `dili=1 / herg=0 / ames=0 / MRTD 1925`，真 M `dili=NoPrediction(out_of_domain) /
  herg=0 / ames=NoPrediction / MRTD 251` —— 与 2026-10-27 的项目级结论完全一致。
- **C65（判据错误）**：`w5_wait_M.py` 用正则 `<table.*?</table>` 数 33-td 行判断"是否出结果"。
  结果页在 **2 分子**时是嵌套表布局，正则只数到外层表 → 判定"未就绪"，
  **实测白等 6 分钟**（结果其实早就绪）。修复：就绪判据一律用提取器本身
  （`parse_checkjob(html)` 能拿到预期行数），并把这条写成回归测试。
- **C66（移植方式错误）**：适配器第一版 `_viewstate`/`_total` 按"理解"重写，
  与站点实际文案不符（`Total query compounds:`、ViewState 须取 `j_idt32` 表单内最后一个）
  → total 恒 0、add 直接失败。教训：**移植已验证脚本时，易碎的文案/结构解析器必须逐字复用**。
- 新增：`tests/test_vnn_parser.py`（13 断言，用真实 2 分子结果页夹具，
  其中一条专门复现"正则法得 0 行"的旧 bug）；`tests/fixtures/vnn_checkjob_2mol.html.gz`。
- 新增参照端点 `vnn_mrtd`（role=reference，不裁决）；vNN 的 CYP×5/BBB/Pgp×2/HLM/MMP
  不映射，计入 `meta.unmapped_endpoints`（避免无规则端点刷屏，C43）。
- 端点映射：vNN `DILI/hERG/AMES` → `dili/herg/ames`；Yes/No → 1/0（unit=class，note 标明非概率）。
- 测试总数：**10 套 171 断言**，`pytest -q` 10/10。

## v2.2.0（2026-10-28 22:40）——评估报告全项修复（P0/P1/P2/P3）

**驱动来源**：`admet-skill/skill专业评估报告_v1.md`（六维度评估，评级 B+）；
本轮把报告里可代码化的缺陷全部修完并逐项实测。**新增 7 套测试，累计 9 套**。

### P1（科学/工程）
- **C52 chembl 参照层单位/方向混算**：hERG 的 nM 与 uM 不换算直接取分位（差 1000 倍）、
  ppb 把 `% bound` 与 `fu` 两个方向相反的物理量并桶、clearance 混入 `Half Life`。
  改为 `canon()` 归一（浓度→µM、结合→fu 分数、半衰期→h、溶解度→µg/mL 或 µM）+
  按 (物理量, 规范单位) 分桶，无法安全归一**直接丢弃**。
  实测：caffeine logD p50 = **−0.07**（与文献 logD7.4 一致，独立佐证）；
  APAP 溶解度 p50 = 1370 µM（原始记录全为 nM，换算生效）。
- **C53** chembl activity 接口偶发 500 会让整个分子失败 → 降级：保留适用域
  （邻居数/最大 Tanimoto），参照分位写 `chembl_reference_status=error`。
- **C54** `test_desirability.py` 硬编码 `out/reliability.csv`，装机副本无此文件 →
  整套 FileNotFoundError 崩溃。改读 `_pilot/reliability.csv` + 缺失跳过。
- **C55** `schema.validate()`（C48/C49 加固成果）在 CLI **零调用点**（摆设）→
  新增 `adt.cli validate`；reliab/ledger/sensitize 入口强制校验，`--allow-invalid` 可跳。
- **C56** B1 对照"混入队列"协议与实现不符（只在 0 产物时惰性跑）→ 基类加
  `pre_batch()` 钩子，bt 每批开跑前强制跑对照并比对区间，落盘 `batch_qa.csv`。
  实测：APAP 批 6/2 均在区间，无漂移。
- **网页源收编**：`admet_ai / protox3 / admetlab3` 三个适配器进 `adt/adapters/`，
  统一 `adt.cli web --source ...`。实测：ADMET-AI 2/2 对齐 3 端点；ProTox APAP
  LD50=338、DILI=1、mutagen=0（与试点一致）；ADMETlab 今日仍 429（退避生效、
  失败记录为 error 而非编造数据）。**vNN 只做人工桥**——无凭据无法端到端验证，
  按交付规则不写未验证的自动化实现。
- **hERG 裕度判据修正**：v2.1"Margin >10 即足够"作废。按 Redfern 2003 分档：
  <10 红旗 / 10–30 仅危及生命适应症 / 30–100 常规 / ≥100 宽松（轻度适应症、CNS、超量风险）。

### P0
- **E3 阈值敏感性分析**：`adt/sensitivity.py` + `adt.cli sensitize`。
  global（全部阈值同时摄动）与 per_endpoint（逐个）两模式；翻转率 >0.2 → fragile、
  >0.5 → threshold_critical；`report` 自动追加"阈值稳健性"段。
  实测试点：全局最大翻转率 0.14（robust），**hERG 0.33（fragile）**。
- **E1/E2 基准框架**：`examples/benchmark_vs_truth.py`——框架裁决 vs
  "均值投票"基线 vs 金标准，输出一致率与逐条对照；<30 条自动警告"只够自检"。
  **金标准数据仍需湿实验/文献实测提供**（框架就绪，数据待补）。

### P2
- **端点别名表** `references/endpoint_aliases.yaml` + `adt/endpoints.py`：
  显式映射优先、子串兜底**留痕**（reliab 会打印"靠兜底匹配"的行数与端点）。
  顺带修正 registry 的 `admet_asar3` 拼写与 `admet_ai_most_endpoints` 伪源名。
- 饱和扫描 <3 数值不再静默跳过，改为显式告警（`diag`）。
- 概率未校准声明进入 `phrasing.forbidden`（跨模型中位数≠校准概率）。
- manifest 增加 rdkit 版本、cwd，argv 相对化。
- 输入格式显式参数 `--format auto|csv|tsv`（嗅探是启发式，首行含逗号的 TSV 会误判）。
- 工程化：`pyproject.toml` / `requirements.txt` / `LICENSE`(MIT) / GitHub Actions CI /
  pytest 入口（脚本式测试经子进程运行，`pytest -q` 9/9 通过）。

### P3
- **C58** 删除 `phrasing` 的 `consistent_multi_indep` 死层（不可达且模板含未替换 `%d`）。
- **C59** 多实测值不再取第一条 → 中位数 + "多实测不一致"写入 reason。
- **C60** 排名守卫第三参原本硬传 `None`（分歧条件在 CLI 层静默跳过）→ 从
  reliability.csv 的 spread 列计算真实最大极差。
- **C62/C63** `saturated` 契约补上**唯一写入路径**（`saturate --mark-measurements`
  产出 measurements_saturated.csv），并修正 reliab 的 `IN_DOMAIN_FLAGS`——
  否则写回后会把"红旗结论"退化成"全部源域外"。
- `can_rank_full` 的未使用形参标注废弃（保留兼容）。

### 测试
9 套：gates_protocol(21) / reliability(25) / desirability(38) / e2e_cli(11) /
chembl_units(22) / batch_anchor(9) / sensitivity(10) / web_adapters(15) /
saturation_mark(7) —— 共 **158 条断言**，全部通过（`pytest -q` 9/9）。

## v2.1.3（2026-10-28 07:30）——截图问题复查 + 未运行模块实例化

**外部会话五问题复查**：ESOL 系数（数值复验 ✓）、ProTox Probability 语义/DeepPurpose
降级/LD50 无区分/DILI 白名单（registry 四处均已登记 ✓）、无氢输入（SMILES 路径结构性
免疫，不适用）——**本 skill 无同类问题**。

**未运行模块实例化抓出 4 个新问题**：
1. **C48**：validate 放行 predicted-空值行 → 加固（predicted/measured 空值拒绝）
2. **C49**：validate 放行 measured-无 provenance 行 → 加固（溯源链强制）
3. **C50（危险级）**：**bt/chembl 对 TSV 输入静默空转**（exit 0 / 0 行 / 零告警）
   ——DictReader 把数据行当表头。修复：加载层按首行分流 CSV/TSV + 空结果警告。
   实测：修复前 APAP PHASEII 0 行零告警；修复后 1 个葡糖醛酸化产物（predicted）。
4. **C51**：`blocked_endpoints` 疑似判据过时（实为 pilot 宽表 0 invalid，行为正确）+
   `charges_and_ph` 死代码接线到 normalize note；cmd_saturate 恢复 blocked 输出。
- validate 复验：pilot 151 行过新校验 0 problems。

## v2.1.2（2026-10-28 01:45）——欠账清理 + 装机

- **公共层化（C44 销账）**：`load_released_compounds()` 统一硬门过滤，bt/chembl 的
  复制粘贴逻辑删除——以后新适配器一处生效。
- **CLI 级端到端测试**（C42 教训落地）：`tests/test_e2e_cli.py`（11 断言）——用
  subprocess 走真实 `python -m adt.cli` 入口、断言落盘 CSV 列内容。C42 时序 bug
  这一层当年全绿漏过，现在有回归防线。
- **LE 反推审计脚本化**（C9 销账）：`examples/le_audit.py`——双向互证
  （ΔG+LE 反推 HA；ΔG+HA 反推 LE），实测 consistent/MISMATCH 对照全部正确。
- 案例库销账 3 条（C44/C9/C5 部分）；测试 4 套共 **91 断言**。
- **装机完成**：`C:/Users/huawei/.workbuddy/skills/admet-screening`（v2.1.1→2.1.2 同步）。

## v2.1.1（2026-10-28 01:30）

- **C47（bug）**：饱和扫描把 percentile 列（0–100 百分位）误判 invalid——量纲守卫把
  median≈50 当 log 量越界。修复：percentile 列跳过边界与饱和判定（它们是排名信息，
  非物理量）。实测：ADMET-AI 宽表 98 端点 → 49 数值端点，invalid 3→0。
- 试点各源产物齐全（5 源 130 行长表）；W1 ADMETlab 因限流仍在退避队列中，到位后
  用 assemble_pilot.py 补汇编即可。

## v2.1.0（2026-10-28 01:10）——6 类化合物全流程试点（pilot）驱动

**试点组合**（7 分子 + 2 负例，跨 6 类）：真 M（肉桂酰糖苷/域外类）、APAP（苯胺药）、
布洛芬（芳基丙酸）、咖啡因（嘌呤生物碱）、丙戊酸（脂肪酸）、甘氨酸两性离子、
乙醇胺磷酸酯（离子形式）+ 负例 [CH3] 与五键碳。

**实例分析抓出并修复 4 个问题**（修复前 normalize CLI 从未正确标记任何状态敏感）：
1. **C42（高严重性 bug）**：`state_sensitivity` 时序错误——standardize 内对**已中和**
   的 m 重算，dTPSA 恒 0，v2.0 上线以来 CLI 从未触发过状态敏感标记。修复：保存原始
   输入 mol。实测：两性离子 dTPSA 4.5–7.3 正确标记。
2. **C43（设计缺陷）**：chembl 的参照分位（logd_p50 等）与适用域指标（neighbors、
   max_tanimoto）被当质量端点裁决——每分子刷 10 行"无阈值规则"噪音、稀释轴覆盖率
   （caffeine 0.17）、让可判端点恰好多的分子独占 Pareto。修复：**端点角色分类**
   （quality / applicability / reference），rules 23 端点全部标注；reliab 对非 quality
   输出 PASSTHRU；desire 不聚合；report 单独成"适用域/真值参照"节。
3. **C44（流程缺口）**：硬门拦截的分子（NEG_radical）仍被 chembl 提交（bt 上一轮修了、
   chembl 漏了）——**过滤逻辑复制粘贴不可靠，已在两个适配器统一**。
4. manifest 历史链、硬门过滤、饱和扫描等在 pilot 全链路验证通过（130 行长表、
   5 源、schema 0 problems、ledger 0 unsupported）。

**试点科学发现**（预测 vs 已知药理的活案例，印证"预测必须带参照"）：
- vNN 给**甘氨酸 DILI=Yes**（域内近邻伪影——甘氨酸无毒）；给**咖啡因 CYP1A2=No**
  （咖啡因是经典 CYP1A2 底物）。措辞封顶把这些压在"预测指向"级别，防止误读。
- ProTox 对 APAP 相似度 100%（训练集含本体）→ LD50 338 mg/kg 有参照；
  对 M_true 相似度 82% 无近邻 → LD50 5000 无区分力——**同一工具两种行为**。
- BioTransformer：4 个药物样分子 5–8 个代谢产物；糖苷与两性离子 0（out_of_domain）。
- chembl：5/7 分子 Tanimoto=1.0（本体已收录）；**适用域最差的 M_true（T70=0）
  恰是 DILI/hERG 全 NoPrediction 的分子——适用域与拒绝预测互证**。

**试点运营发现**：ADMETlab 对新批次限流极严（连续 5 轮 429，全批 ≥30 分钟）——
协议补条：新化学类首跑先 2 分子探限流窗口，再全量。

## v2.0.1（2026-10-27 23:50）

全功能实例排查（9 项真实数据验证），发现并修复 3 个问题：

- **C38（bug）**：`report --axis` 默认相对路径跨目录污染——全局段显示其他目录的旧
  Pareto 前沿。修复：axis 默认从 outdir 查找。
- **C39（设计欠账）**：`desire --enforce-rank-guard` 的 max_cluster_frac 硬编码 1.0
  （恒拒绝）。修复：新增 `--max-cluster-frac` 参数。
- **C40（bug）**：MD 收敛门解析残基号 >9999 溢出编码（A000）崩溃。修复：容错占位。
- 实测新数据：MD 收敛门在旧 M 23 帧上判 **converged**（末四分 0.852/块误差 0.018，
  门在足帧下行为首次完整验证）；chembl 全量 14 分子——A/B 的 Tanimoto=1.0（ChEMBL
  有本体，可拉真值），J 适用域全班最差与三标尺垫底互证。
- 案例库 +4 条（C38–C41）；测试 80 断言全过。

## v2.0.0（2026-10-27 23:15）

**治理升级**：借入外部对接 skill（v4.3.4）的九条协议，skill 从"能算"升级为"结论永远不超过证据"。

- **硬门**：normalize 自动执行价键/奇电子/radical 检查（`hard_gate_problems` 列，非空禁分发）
- **措辞封顶**：`phrasing.allowed_statement` 模板 + reliab 输出 `allowed_statement` 列；
  禁止 ΔG→Kd、预测值→人体剂量、"证明/无毒"（05 §12）
- **源独立性计票**：registry 全源 `independence_group`；同组只记 1 独立票；
  `require_sources=N` = N 个独立方法组；单组一致 confidence=low
- **预注册**：manifest.py 自动固化判据版本（SHA1 + 历史链）
- **证据台账**：`ledger` 子命令，结论反查支撑记录，unsupported 必须先修
- **跨批锚点**：bt 适配器对照值自动比对 controls.csv 区间，出界标 `batch_drift`
- **状态敏感性**：微状态极差超阈标 `state_sensitive`（阈值实测校准 dTPSA>3 / dClogP>0.2）
- **MD 收敛门**：接触图 Tanimoto 驻留 + 块平均；不收敛/帧不足 → 结论封顶"静态敏感性"
- **案例库**：`references/07_case_lessons.md`——17 轮实测的 症状→根因→预防→捕获机制 四列表
- **MM-GBSA 证据等级**：playbook §9——单帧 provisional → 多帧 → 过收敛门 → 论文级 四级
- **报告生成**：`report` 子命令——从裁决产物自动生成带措辞封顶的结论段
- 新命令 ledger / report（CLI 共 10 个）；测试 3+1 套共 ~100 断言

## v1.3.0（2026-10-27 18:01）

- 借入外部分享会话（王百合苷×DP1 独立工作线）的 playbook（06）：PBPK 方案、
  红ocking Gate、MD 坑清单、PySCF 替代 ORCA、NMR 证据分级（G-NMR）
- ChEMBL 适配器（适用域 + 真值分位）；s5 多源裁决 + 25 断言
- registry 15→18 源；ADMETlab/pkCSM 双线互证

## v1.2.0（2026-10-27 17:35）

- s6 desirability：同轴几何平均 + Pareto 前沿 + 排名四条件守卫（36 断言）
- 规则 YAML 加 axis 分组（exposure/stability/safety/coverage）

## v1.1.0（2026-10-27 17:00）

- ChEMBL 适配器（T40/70 双阈值 + 本地 Tanimoto + 活性分位）
- s5 可靠性裁决（分歧不取平均、三态输出、中位数聚合）
- admetSAR3/Pred-hERG/TOXRIC 探测定性（needs_probe）

## v1.0.0（2026-10-27 16:40）

- 首个可运行骨架：SKILL.md + references 6 篇 + adt 包 + 4 命令
  （normalize/saturate/bt/xeno-prep/xeno-ingest）
- 两个适配器实测（BioTransformer REST 全坑记录；XenoSite 无免费 API → 人工通道）
- RDKit 互变异构立体保护；饱和扫描三态（usable/saturated_in_set/invalid）
