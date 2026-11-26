---
name: admet-screening
description: 虚拟筛选命中物的 ADMET 分层评估与决策。用于"这批 hit 的 ADMET 怎么评""能不能口服/进脑""预测结果能不能信""哪些端点该丢弃"这类问题。内置结构真实性 gate、分子状态标准化、全端点饱和扫描、化学类→源白名单、长表数据契约。适用任何化学类，但对大极性糖苷/天然产物有专门的失效判据。
version: 4.0-dev
doc_revision: "4.35 (2026-11-19)"
---

> ### v4.36-dev 补丁：同行评审 P0 修复（2026-11-22）
>
> 默认测试从 89 个 smoke 脚本扩到 103 例（14 个 pytest 原生测试真正执行，
> 并立即抓出两处过期断言：claims 字段审计 25 unresolved→实际 0、CHANGELOG 4.25→4.35）；
> 修 `trust.physchem_violations` 传整包时越界永远为 0 的静默放行；
> 新增零引用公共 API 门禁（`tools/api_usage_audit.py` + allowlist）；
> 治理扩展层移入 `adt/governance_ext/`（实验性，不接主 CLI，需真实数据标定后
> 按 SHADOW→ENFORCE 接入）。能力等级仍 4.0-dev，不因补丁升级。

> ### v4.37-dev 补丁：c* 边界估计器成为一等命令（2026-11-25，doc 4.36→4.37，能力等级仍 4.0-dev）
>
> `adt cost_boundary`（库）+ `adt cstar`（CLI 命令）：把论文 Table 2b/2c 的临界成本估计器
> 从 tools 脚本提升为标准能力。用户对自己的端点定价 admission 设计时，不必知道论文
> 用了哪个脚本。`tools/analytic_critical_cost.py` 变为薄 wrapper——CLI 与输出逐字不变
> （diff 验证），六个表格 checksum 仍 6/6。新增 `tests/test_cstar_cli.py`（5 例：精确线性
> 恒等式、缺数据返回 None、solve_all 过滤、deposited 回归、CLI 端到端）。

> ### v4.35 未闭合项清零：8 条"只能测试覆盖"的命令接上真实真值（2026-11-19，doc 4.35，能力等级仍 4.0-dev）
>
> **做法**：核实本机已有三份真数据（OpenADMET 实测 25 265/10 738 行 + 两个真实模型源
> + ChEMBL hERG 外部留出 9 443/959），把覆盖率里"需要实测真值"的 8 条命令里 7 条
> 改成真跑（`tools/real_truth_legs.py`），第 8 条确认是**许可边界**而非能力缺口。
>
> **关键结果（全部真实真值）**
> - `ablate`：无准入 0.772/**0.2733**；仅单位守卫 0.760/0.8868；完整准入 0.068/**0.9462**。
>   **同覆盖 725 决定**下 0.946 vs 0.829 vs 0.258 —— 增益不是覆盖假象，但代价是 11 倍覆盖。
> - `prospect`（时序留出 10 738 对）：准入 0.8793 vs 无准入 0.2733；PASS 组失败率
>   45.3%→8.3%（**但仅单位守卫已 7.8%**，域外阻断边际贡献≈0，如实报）。
> - `conformal-class`（hERG 留出，不相交 477/482）：边际 0.913、类0 0.881、类1 0.928、
>   MCG 0.019、CII 0.047 —— "边际达标、类条件小缺口"的教科书情形。
> - `cross-class`：面板 0.973 vs OpenADMET 0.276，方向符合预期（可证伪预测成立）。
> - `decision-value`：admission ≡ vote_all（EU −124）→ **本场景无增量**，不凑数。
> - `pred-shift`：去立体 0.000；互变异构 logP 0.517（=源间 0.83）、TPSA 2.696，
>   **3 个分子净电荷翻反**。
>
> **新修复 3 个缺陷**
> 1. `benchmark` **无端点方向**：9 端点里 5 个 AUROC 整反（mppb 0.082→0.918）。
>    按规则 shape 定向（`down→原值`、`up→取负`、`window→出窗距离`），加 `score_orient` 列；
>    `up/down` 指**好坏方向**不是数值方向（这条自己踩过一次）。
> 2. `pred-shift` 把 **no-op 变体的 0.000 当结论**：现按 `noop=Y` 排除并在全 no-op 时拒绝判读。
> 3. `tautomer` 变体**空转**（`Canonicalize` 返回自身）：改为从 `Enumerate()` 取真正不同的互变体。
>
> **未闭合项**：BioTransformer 由本地 **SyGMa** 引擎接替（30/30 分子、330 产物、
> `bt --engine`）；立体盲区做成**证书**（4/4 结构性失明，max|Δ|=0）；
> XenoSite 确认为许可边界；ChEMBL 重抓。
> 详见 `real_legs/REAL_TRUTH_LEGS_REPORT.md`。
>
> ### v4.34 30 化合物面板全流程实跑 + 9 类缺陷修复（2026-11-19，doc 4.34，能力等级仍 4.0-dev）
>
> **做法**：先设计"覆盖式面板"（30 个化合物、9 个化学类，结构全部由 ChEMBL 的
> InChIKey 锚定，不手写 SMILES），再按"化学腿 / 统计腿 / 治理腿"跑 83 个步骤，
> 让每个 CLI 命令至少被执行一次；跑完按实际报错逐条修。
>
> **面板设计要点**（`panel_spec.json` 里每条都写了 triggers）：
> 羧酸/碱/两性离子/中性四类电离 × 消旋体与单一异构体 × 盐型去盐 × 糖苷四种键型
> × 邻苯二酚/黄酮/多酚三类干扰 × 分子量 180→1202 × Ames 阳性（黄曲霉毒素 B1）
> × 转运体五种化学型 × 窄治疗窗（地高辛/华法林）。
>
> **修复的 9 类缺陷**（全部由实跑暴露，单元测试造不出来；`tests/test_panel_fixes.py` 10 例回归）：
> 1. **消旋药进不了流水线**：闸门提示"须声明是消旋体还是立体缺失"，但代码里**没有声明入口**
>    （`declared_stereo` 的语义是"我是某个特定异构体"）。改为四态
>    `defined / racemic_declared / not_applicable / undefined`，并让 `report --publish`
>    在结论段首屏打印"立体上限"（实测 4/30：华法林、普萘洛尔、特非那定、酮康唑）。
> 2. **BioTransformer 不可达时挂死**：无预检，每分子要等 90s 超时 ×2 重试 + 31s 限流。
>    加 `preflight()`（8s 短超时），现在 11-19s 内 rc=3 并明确"0 产物 ≠ 无代谢"。
> 3. **糖苷轴对非糖苷酯张冠李戴**：阿司匹林被判"糖苷水解风险=high、键型=none"。
>    新增 `axis_applicable` 列并单列"仅酯键"分支；该列同时落盘，下游读表不会再误读。
> 4. **cardiac 静默丢弃 manual 回填**：命令自己打印"cardiac 端点只能来自膜片钳实测或
>    Cardiosim-Tox 回填"，却把 `domain_flag=manual` 的行丢掉 → 用户照做后拿到"没有识别到
>    端点"。现纳入 manual 并提示条数。
> 5. **红线 6 告警漏掉 manual**：人工读网页录入的数值没有区间也可以一路进结论。
> 6. **chembl 无成本旋钮**：30 分子默认 40 邻居要 >20 min（活性分页是主因）。
>    新增 `--max-neighbors`，并在文档里给出成本曲线。
> 7. **退出码语义撞车**：`pbpk-qualify` 用 2 表示"拒绝评估"，与 argparse 的用法错误同码；
>    缺文件时还给 20 行 traceback。现拒绝=4、缺文件=3、干净报错。
> 8. **conformal 拿到宽表就 KeyError**：入口增加长表列校验并说明期望列。
> 9. **acyl_glucuronide 文案串味**：残留"失眠适应症"（别的项目文本）。已清除，并登记
>    已知反例（双氯芬酸判 medium、阿托伐他汀判 high，与临床排序相反 → 该分级不得用于
>    跨分子排序）。
>
> **新增工具**：`tools/panel_fetch.py`（名称→ChEMBL 结构锚定）、`tools/panel_run.py`
> （三腿 83 步跑批 + 台账，超时用 Popen+kill 真能中断）、`tools/panel_coverage.py`
> （命令级覆盖率核算，未覆盖即缺陷）、`tools/panel_legb_split.py`（合成配对，带 SYNTHETIC 标记）。
>
> **边界**：统计腿的 conformal/benchmark 用的是**合成配对**（truth 真、pred ±8% 扰动），
> 只验接线与数学；BioTransformer/NPASS 相关步骤在本网络下不可达，如实记为 REFUSED，
> 不写成"0 代谢产物"。
>
> ### v4.33 外部对照台账门 G14（2026-11-19，doc 4.33，能力等级仍 4.0-dev）
>
> **这一版不加新预测能力，只把"自验会共享盲点"变成机器可检的账。**
> 三轮事故结构相同：selftest 与实现同源，模型错则两边一起错——
> ① t 分布自由度用 n 而非 n−2；② Holm 按 zip 顺序回填（结论完全颠倒）；
> ③ OOT 基线含待检尾部（SD 膨胀 30× → 系统性漏报）。
>
> **新增**：
> 1. `adt/external_comparison.py` — 每个统计量算两遍：`ours`=真正被调用的函数，
>    `ref`=本文件内另行写出的参考实现（scipy / 教科书闭式 / 独立复算），逐点比偏差。
>    覆盖 Clopper-Pearson、Wilson、Newcombe、Holm（两处实现同时比对）、
>    相关系数双尾 p（df=n−2 哨兵）、OOT 基线（前缀哨兵），共 6 模块 28 点。
> 2. `references/EXTERNAL_COMPARISON_LEDGER.yaml` — 台账：`required_modules` 是**棘轮**
>    （新增统计模块必须先进台账），每条挂"对照脚本 + 独立审查报告 + 回归测试节点 +
>    声明容差"，缺一即 blocker。
> 3. **G14_external_comparison（blocker）** 接入 `release-check`：不只查台账格式，
>    而是**实跑**对照，实测偏差超台账声明容差即拦（不采信台账里的数字自述）。
>
> **反向验证**（不是"能跑通"而是"该红时会红"）：参考实现偏移 50% 被抓、
> 容差写死 1e-18 被抓、棘轮漏登被抓、审查报告/回归节点缺失被抓——4 条对抗探针
> 全部转红（`tests/test_external_comparison.py` 9 例，含 OOT 对照组必须同时出现
> OOT 与 IN_CONTROL 两种结论，防止"永远判受控"这种漏报型实现蒙混）。
>
> **同期修掉一个"文档承诺 ≠ 代码行为"的洞**：复现挑战包 README 写着"只交数字不算复现"，
> 但 `replication.score()` 只比对数字，纯数字提交照样 `verdict=pass`。外部审阅者会按 README
> 相信"已要求代码"，实际没查。现 `score()` 与包内 `score.py` 同步要求
> `implementation`（code/repo/files）+ `environment`（python/rdkit/numpy），
> 缺则 `verdict=numbers_only`、退出码 2（与 pass=0 / fail=1 区分）。
>
> **边界**：G14 只声称"实现与参考实现逐点一致"，不声称统计假设成立、不声称结论正确；
> 参考实现若与被测同源于同一公式，公式层误解查不出，故每模块另需人写审查报告。
>
> ### v4.32 技能市场 100 skill 解构移植（2026-11-19，doc 4.32，能力等级仍 4.0-dev）
>
> **市场检索**：46 关键词 → SkillHub API 660 个唯一 skill → **本地严格相关性过滤后 233 个** → 选 100。
> 关键教训：SkillHub 的 score 对专业查询普遍 0.05 且返回全局热度排序（"conformal prediction"
> 会返回公文写作），已按 `LITERATURE_SEARCH_SOP.md` 的"先过滤后排序"纪律重建语料。
> 100 个分 4 组逐条精读描述，标注证据不足处，不脑补功能。
>
> **新增 3 模块 + 2 纪律**（已实跑）：
> 1. `adt/deviation.py` — OOS/OOT 偏差检测与处置状态机（技能市场 pharma-csv-pro）：
>    OOS=单点越规格、OOT=连续 n 点偏离基线 k·SD；处置 pending→confirmed→attributed→closed
>    不可跳跃。补 `silent_failure` 不覆盖的"数值合规但趋势已漂"。
> 2. `adt/retrieval_card.py` — 可复现检索策略卡（search-strategy-builder）：锁查询串/sources/
>    过滤器/深度/日期 + sha256，补上"锁了数据 hash 却没锁查询"的缺口。
> 3. `adt/power_analysis.py` — 前瞻性样本量/功效规划（quantitative-research）：纯标准库
>    NormalDist，与 scipy 独立公式 80 组逐位一致；补 G9 条件②前瞻验证的事前规划。
> 4. SKILL.md 新增"执行器能力边界与交付物唯一来源"（bio-admet-prediction）：
>    只有经核验的本地产物可引用，第三方输出须过准入门，不冒充本框架产出。
> 5. SKILL.md 新增"合规映射矩阵"（legal-regulatory-compliance-mapper）：
>    义务→控制→证据→审查计划四元映射，未覆盖跳标 coverage_gap，不声称合规。
>
> **报告建议同步落地**：`manifest.py` 显式落 compliance_profile / profile_declaration
> （未声明与 academic-internal 可区分）；`schema.py` 增"数值无 uncertainty/CI"warning；
> 新建 `references/LITERATURE_SEARCH_SOP.md`（相关性优先 + IF 对数压缩，防选择偏差）。
>
> **独立代码审查**（`code_review_market100.md`）三路核验（scipy 80 组 + 30 万次 Monte Carlo +
> 对抗探针）又抓出 selftest 漏检的 1 个 Blocker：`deviation` OOT 未给 history 时把待检尾部
> 计入基线（SD 膨胀 30× → 系统性漏报）；已修为取前段，NaN/Inf 改判 INVALID_DATA。
> power_analysis 数学正确（0 mismatch），另修 alpha/rounding 校验 2 Warning。
> `tests/test_estimand.py` 达 45 例（新增 5 个永久回归）。
>
> ### v4.31 100 篇高分文献精读移植 + 代码审查（2026-11-19）
>
> **实证基础**：用 PubMed E-utilities 10 个主题检索 → 511 篇去重 → 按领域相关性 + JCR2025 IF
> 选出 100 篇（语料 `lit_search_100/corpus_100.json|md`，IF 5.7–7.9 为主 + 少量顶刊），
> 4 组各 25 篇逐篇精读（原文摘要，非标题臆测）。
>
> **新增 3 个模块**（均纯标准库、逐篇标注 PMID，selftest 全过）：
> 1. `adt/evidence_streams.py` — 证据流互补/冗余判定。据 PMID 42798706（ML vs docking
>    r=0.090,p=0.37 → complementary）把"多源准入先于组合"变成可判定数值门；
>    `complementarity()` + `admission_report()`，近零相关→COMPLEMENTARY、高相关→REDUNDANT/CONFIRMATORY、
>    样本不足→INDETERMINATE(ESCALATE)。**人确认必填，不声称统计独立**。
> 2. `adt/silent_failure.py` — 静默失败率 SFR（高置信但错误）与置信-误差对齐审计。
>    据 PMID 42003704（SFR 12.02%→1.8%）、39005492（OOD overconfidence）、42734510
>    （数值提升不显著但 UQ 对齐改善）。补 skill 工作包 J 的盲点（空源 ≠ 自信错误）。
> 3. `adt/perm_contribution.py` — 组件贡献置换检验。据 PMID 40899589（protein embeddings
>    贡献极小），`permutation_contribution()` + `batch_contribution()`（Holm 校正），
>    贡献不显著→负结果默认"不采纳"；与已有 `randomization_null_control`（结构位移）用途不同。
>
> **增强**：`claims_audit.significance_gate()`（效应量+显著性双准入，"数值好看但不显著"
> → FRAGILE，据 PMID 42734510）。CLI 新增 `evidence-streams` / `silent-failure` /
> `perm-contribution --selftest`。回归测试 +6 例（test_estimand 共 32 例）。
>
> **独立代码审查发现并修复 2 个 selftest 漏检的 Blocker**（见
> `logs/peer_review_20261117/code_review_100papers.md`）：
> ① `evidence_streams._p_two_sided` t 分布 df 错配（用 n 而非 n−2，小 n 低估 p 达 34%，
> 与 scipy 对照误差 3.5e-2 → 修复后 1.4e-15）；
> ② `perm_contribution.batch_contribution` Holm 结果按 zip 顺序回填而非 idx，
> **结论完全颠倒**（噪声被判显著、真信号被判不显著）——已按 idx 回填并加永久回归断言。
> 另修 10 项 Warning（置换不足、无效 CI 误判、非数值输入、git_commit 误绑调用方仓库等）。
>
> ### v4.30 三个 prior art 的精华移植（2026-11-19）
>
> 对 TRUST-ADMET / SciForge / AdmitOR 做一手源码级解构后，**只移植可用的、并修掉其缺陷**：
> 1. **新增 `adt/trust.py`**（单分子可信决策 + 数据忠实性门 + 预注册判据报告）：
>    - 移植 TRUST-ADMET 的"单分子当场分级/动作/硬拒答 + 字段级 breakdown"产品形态，
>      **并先修它三个缺陷**：①uncertainty 与 confidence 共线（禁止 `1-2|p-0.5|` 计分，
>      同源信号直接 UNDETERMINED）；②模型级 ECE 是常数（逐样本校准误差缺失时标
>      `model_level_only_not_counted` 且不计分）；③invalid SMILES 静默零特征（改为硬 REFUSED）。
>    - 移植 AdmitOR 的 **numeric-coverage check**（提取数值必须在源文本出现，否则 ESCALATE；
>      诚实标注抓不到"打印精度取整"共模错误）。
>    - 移植 SciForge §4.7 的**预注册判据未达成报告**：主/次判据分层 + 噪声底对照 + no post-hoc。
>    - 证书显式带 `assumptions` / `not_a_proof_of`（AdmitOR 语义），不冒充概率保证。
> 2. **`adt/claims_audit.py` 新增 claim 五类脆弱性分类**（SciForge §4.3：supported/fragile/
>    unsupported/needs_narrowing/needs_experiment + 可执行 remediation），**强制人确认，
>    不做自动判定**——SciForge 论文自己也写 scientific judgment remains with the researcher。
> 3. **`adt/manifest.py` 新增 git_commit / git_rev_status 字段**（TRUST-ADMET P2；
>    取不到写 null+unavailable，不伪造）。
> 4. CLI 新增 `trust`、`claims-fragility`；`tests/test_estimand.py` 新增 6 例回归（共 24 例）。
> **明确不移植**：TRUST-ADMET 的 CP（分类集合、无覆盖率回检，弱于本 skill）、校准/TDC 式外部验证、
> provenance/门禁（本 skill 全面更强）；SciForge 的硬度量表（实际不存在）与主张判定深度；
> AdmitOR 的二值 family 标签（本 skill 的 ρ/误差方差分解更细，family 只作补充）。
> prior-art 一手解构全文见 `references/PRIOR_ART_2026_SCAN.md` 与本轮报告。
>
> ### v4.29 策略裁决与投稿就绪（2026-11-18）
>
> **v4.29 增量**（用户授权"需要裁决的直接按专业判断执行"）：
> ① **5 项学术分歧全部裁决并落地**（`references/STRATEGIC_DECISIONS_2026-11-18.md` +
> `references/POSITIONING.md` §6）：framing=失效边界检测框架；走 Stage 1 RR；
> soundness 刊主线不投 Nature Methods；estimand 按"当前致命/Stage1 冻结"两阶段处理；JONNPR 末位。
> ② **Stage 1 注册包** `PREREG_STAGE1_PACKAGE.md`：冻结 H1/H0/H2/H3、完整 SAP、estimand 绑定、
> OSF 提交交接与**实测 HTTP 200 的网址**（真人操作，我方不冒充已注册）。
> ③ **投稿就绪论文草稿** `PAPER_STAGE1_v4.28.md`：主图=失效边界图，图表绑定产物，
> 已撤回图/结论明确禁止入稿，prior-art 逐条区分。
> ④ **第二实现者独立复现**：`logs/peer_review_20261117/second_replicator/`（冻结规范 + 独立实现 +
> 8/8 数值比对 + 对规范自身两处笔误的裁决）。诚实边界：非外部人类复现，G9 条件③仍未满足。
> ⑤ **两项 PK/PD 欠账诊断**（`logs/peer_review_20261117/pkpd_diagnosis.md`）：实跑**推翻**了
> "PK-Sim 静默丢仿真"的旧断言（37 条仿真可完整往返；真因是引用的 ObservedData 缺失），
> 已勘误 interop.py / SKILL.md / CHANGELOG；nlmixr2 仅 V 可辨识为数据设计导致的结构性不可辨识，
> 固定 F 对照无效，不改模型。
>
> ### v4.28 同行评审整改（2026-11-18）
>
> **v4.28 增量**：① **G10 证据链从字面量升级为字段级**——27 条主张中 2 条撤回，其余 25 条
> 全部绑定结构化证据（24 条 JSON `expect_field_path` + 1 条代码 AST 符号 `expect_code_symbol`），
> `structured=25/25 / mismatch=0 / literal_only=0`，G10 门禁由 `warn` 升为 `info`；
> 新增 `tools/bind_claim_fields.py`（可复现的绑定生成器 + 自检）；verifier 新增 code-symbol 证据类型。
> ② **env-audit 退出码**：新增 `--required-only`（必需层全绿即 rc=0），修正 SKILL 命令段
> "退出码 0 才继续"的错误判据。③ 6 项回归测试补入 `tests/test_estimand.py`（共 15 例）。
>
> ### v4.27 同行评审整改（2026-11-17）
>
> 本轮为**外部硬核同行评审**的落地，遵循"发现一个 bug 补一个测试 + 新增模块必须实跑并接线"：
>
> 1. **【G13 · estimand 绑定门】** 补齐 `RETRACTION_NOTE.md` 自己列为撤回前置条件、但仓库里
>    从未创建的 `references/ENDPOINT_ESTIMAND_CARDS.yaml`（4 端点 estimand 卡 + 量纲/基线字典 +
>    C01/C18 已知违规式）。新增 `adt/estimand.py`（`check_comparison` / `check_claim` /
>    `validate_text` / `audit_artifact`），把"跨量纲比较"从教训变成可判定的阻断；
>    发布门禁新增 **G13_estimand_binding（blocker）**，CLI 新增 `estimand` 子命令，
>    回归测试 `tests/test_estimand.py` 11 例。已对真实 C01 产物
>    `out_ext/external/external_cuts_summary_v2.json` 实跑审计通过。
>    **注意**：estimand 绑定门只拦"可静态举证的跨量纲/未绑定"，不能替代专家对 estimand 是否
>    科学恰当的判断；本门通过 ≠ 结论正确。
> 2. **【修复① prereg 事后锚定】** `prereg.anchor_status()` 旧实现无论是否 post_hoc 都置
>    `claim_allowed=True`，而 SKILL 授予条件①正是拿这个标志当判据——等于事后锚定点一下就满足①。
>    已改为 post_hoc 一律 `claim_allowed=False`（G9 原有兜底保留，现为双防线）。第一手复现证据见
>    `tests/test_estimand.py::test_posthoc_anchor_cannot_grant_claim`。
> 3. **【修复② 版本分歧台账】** D3 重构把 pyproject.toml 改为 dynamic version 后，
>    `adt.version --strict` 由 rc=0 退化为 rc=1（3 条台账仍写 '3.2.1'，实际读到 None）。
>    按"登记真实分歧、不伪造统一"纪律更新台账为 None，rc 恢复 0。未改任何版本号。
> 4. **【环境事实】** 本轮实测发现环境再次漂移：默认解释器所有核心包缺失、`D:/mm/envs/pkpd`
>    无 python.exe。已用 `bootstrap.py --core-only --skip-tests` 从华为云镜像重建并逐项验证；
>    `env-audit --quiet` 现 rc=2（仅可选层 6 项缺，必需层全绿）——与 SKILL 命令段"退出码 0 才继续"
>    的字面表述不符，正确判据应为"必需层 0 缺失即可继续"，见报告。
>
> 三条修复均已实跑验证，未削弱任何守护项。能力等级仍为 4.0-dev（G9 四条件①②③仍未满足）。

> ### 版本语义（C10 修复：三条轨，互不替代）
>
> 此前 `version: 4.0-dev` 与文档里的 v4.1 / v4.2 / v4.3 / v4.4 **双轨并行**，
> 引用者无法确定"某个数字是哪个版本产出的"。现明确三条独立的轨：
>
> | 轨 | 字段 | 语义 | 谁来改 |
> |---|---|---|---|
> | **能力等级** | `version:` | 只在 v4.0 标签授予四条全部满足时才去掉 `-dev`；**不随文档迭代变化** | 发布门禁 G9 强制 |
> | **材料修订** | `doc_revision:` | 文档/代码的修订号（各版摘要见 `CHANGELOG.md`，当前值见文件头；4.23 全量环境排查 + 换机可复现层，4.22 环境自检与一键重建，4.21 外部工具实装，4.20 回填通道，4.19 菌群，4.18 互操作，4.14–4.17 依次为 pKa/心脏/PD/PBPK 资格），每次实质改动 +0.1，逐条记入 `CHANGELOG.md` | 作者 |
> | **产物身份** | `manifest_sha1` + 快照 sha256 | 某个具体数字的**唯一身份**；任何对外数字必须能追到它 | `adt/manifest.py` 自动写 |
>
> **引用纪律**：论文/汇报引用数字时，写"产物身份"（manifest_sha1 前 12 位 + 产物路径），
> 而不是写"v4.4 的结果"。材料修订号只用于沟通"哪一版文档"，不构成证据。
> 三者混用 = 无法审计。

# ADMET 分层评估（admet-screening）

## 何时用这个 skill

- 已有一批虚拟筛选命中物（docking / 药效团 / 相似性搜索），要先做 ADMET 过滤再决定买哪几个
- 手上有多个 ADMET 预测源的结果，但相互矛盾、不知道该信谁
- 需要判断"某个源在我的化学类上到底能不能用"
- 需要把 ADMET 结论写进决策（继续/淘汰/补哪个实验）

**不适用**：只要一个分子的 logP/logS 这类单点查询（直接跑 RDKit 更快）；
需要 regulator-grade PBPK（要用 Simcyp/GastroPlus，本 skill 只给量级估算）。

> ### v4.0 标签授予条件（R32 / 评审 R3-1）
> `version: 4.0-dev` 中的 `-dev` **不是谦虚，是约束**：它是"未满足授予条件"的机器可读标记。
> 要把它改成 `4.0`（去掉 `-dev`），以下**四条必须同时满足**，缺一条不得改：
>
> 1. **预注册已第三方锚定**：`Prereg.anchor_status()['claim_allowed'] == True`，
>    且锚定日期**早于**本版本首次引用任何评测数据的时间（否则只能写"标准已登记、待锚定"）。
> 2. **外源前瞻盲测完成**（R11）：使用预注册时点**之后**产生的数据、盲态评估、
>    结果不论正负全部公布。随机切分不算前瞻。
>    **⚠ 条件②的排除清单（R-B 外部评审，2026-11-03）**：以下三种**不满足**②，
>    无论数字多漂亮：
>    - ❌ **随机切分**（train/test 同分布）——那是内部效度；
>    - ❌ **数据集发布时已固定的时序切分**（如 OpenADMET 的 train 1321–20100 /
>      test 20101–27239）——你在设计评测方案时**已经知道** test 集存在与其分布，
>      这是 *temporal holdout*（时间留出），不是前瞻；
>    - ❌ **post-cutoff 外源重组**——阈值是见到数据后才定的，属事后解释。
>    ✅ 唯一满足②的设计：评测方案（含代价网格、判读规则、分析代码 hash）在
>    **某个从未接触过该批数据**的分析者手里**先冻结并第三方存证**，之后该批数据才
>    产生/解封，由该分析者执行并发布。做不到这一点，就只能写"标准已登记，②未满足"。
>    详见 `references/TEMPORAL_HOLDOUT_DISCIPLINE.md`。
> 3. **外部第二实现者复现通过**：由**非本仓库作者**独立实现，`counted=true` 的指标全部落在
>    容差内。若同时触发 `suspicious_identical`，须由人审其实现代码确认独立编写
>    ——**不能仅凭"数值太像"判定照抄**：规范越完整，零偏差越是必然结果，两者逻辑上不可分
>    （本条已在 v4.1 修正；旧版把 `suspicious_identical` 当作否决条件，与"规范必须可执行"自相矛盾）。
> 4. **9 条红线在生产路径上接线**（见 §红线）：不是文档承诺，也不是"测试里能通过的函数"，
>    而是**生产命令路径上真的会开火**的守卫。机器判据：`python -m adt.redlines` 全 OK
>    （AST 探测生产调用点 + `REDLINE-<id>` 集成测试），且硬度普查如实公示
>    （当前 **7 hard / 1 soft / 1 conditional**——soft 的 R1 不得在材料里写成"已阻断"）。
>    **2026-11-03 更正**：本轮之前，R3/R6/R7/R8/R9 在生产代码中**零调用点**，
>    G8 读的是硬编码 `ok=True`；条件④当时**不成立**。现已修复，见 `adt/redlines.py`。
>
> **当前状态（2026-11-03 复评）**：
> ① 未锚定（`UNANCHORED`）；
> ② 未满足（现有外源证据全部是 temporal holdout / post-cutoff 重组，按上面的排除清单**不算前瞻**）；
> ③ 仍无外部第三方（self-audit 6/6 通过不构成外部复现）；
> ④ **已接线**（9/9；7 hard / 1 soft / 1 conditional，`python -m adt.redlines` 可验）
> → 因此**只能是 `4.0-dev`**，且**不得**在材料里写"红线已全部阻断"（R1 是 soft）。
> 任何材料在 ①②③ 完成前写"v4.0 已完成"均属违规，`phrasing` 与发布门禁会拦截。
>
> ### 定位（R31 / 评审 B7）
> 本工作是**方法学贡献**（证据准入先于证据组合），不是工具箱。对外应组织为
> **「方法学主文 + 基准伴文」**两篇，并对标 OECD (Q)SAR 五原则与 selective prediction
> 文献，而非在 ADMET 工具箱里比功能；主文必须写明**失效边界与负面结果**。
> 完整定位、形式化命题、可证伪预测、对标表与"不是什么"清单见 `references/POSITIONING.md`。
>
> ### v4.1 新增模块（评审 42 项落地 + 黑榜闭环）
> ```
> adt/snapshot.py        快照层：sha256 + fetched_at + 离线重放（ADT_REPLAY=1）
> adt/release_gate.py    发布门禁 9 门（G1 锁版 … G8 六红线、G9 标签授予）
> adt/units.py           单位换算：同族线性/百分比/log10(M)↔M；class vs probability 判语义拒换
> adt/mmp.py             MMP 校准检验：TOST + 正负对照（替代"随机无关分子对"零假设）
> adt/gate_audit.py      gate 误放/误杀 + gate-as-classifier 的 ROC/PR
> adt/compliance.py      4 档合规 profile + 调用日志归档
> adt/pubchem.py         输入硬化：InChIKey 锚定 + PubChem 字段漂移（禁 ConnectivitySMILES 当主）
> adt/replication.py     复现挑战包：tol=k·sd_seed、弱判别指标降 INFO、反循环依赖闸门
> adt/guards.py          红线代码化（v4.4 起 9 条，由 G8 读取，可 BLOCK）
> adt/weights.py         四种源级权重方案（equal/shrink/bma/diversity）的实测裁决接口
> adt/alerts.py          结构警示层（专家规则，17 条）+ ICH M7 双方法合成判定（v4.3 库/基准；v4.4 reliab --enable-alerts 生产接线）
> run_ad_multicriteria.py 多判据 AD 判别力对比（kNN/conformal p/描述符距离/一致性）
> run_p8_mmp_regression.py 回归型端点的 MMP 检验（位移幅度比 R 的 TOST）
> run_leakage_attribution.py 近邻泄漏归因：源间误差相关是否由"记忆"驱动
> run_external_holdout.py   时间留出外源集（ChEMBL，**本地**按 document_year 切分；**非**前瞻预注册）
> adt/tdc_local.py       本地 TDC 切分读取器：优先官方 `tdc` 包，未装则读缓存 CSV（去硬依赖）
> ```
> 黑榜闭环的实测结论（含对框架不利的五条：C9 准入层无显著优势、A1 收缩权重方向不一致、
> S4 连未校准基线都打不过、nr_ar_lbd 档位偏保守、V8 干净机抓出漏依赖）见
> `references/BLACKLIST_CLOSEOUT.md`；端点分级的外部文献依据见
> `references/ENDPOINT_TIER_EVIDENCE.md`（含 ICH M7(R2) 原文条款）；
> 未解决项收口见 `references/UNRESOLVED_CLOSEOUT_v4.3.md`。

> ### v4.4 新增（第三轮评审 §A–§G 的落地）
> ```
> adt/claims_audit.py          主张登记表审计：每条数字必须绑产物路径 + 字面量命中（门禁 G10）
> adt/defaults.py              负结果→默认配置：8 条默认值各带产物级证据（门禁 G11）
> adt/threshold_audit.py       阈值冻结审计：登记值 vs 代码字面量的漂移检查（门禁 G12）
> adt/guards.py                红线 7/8/9（评测分布标注 / 非预注册前瞻 / 三端点并列）
> run_tail_risk_stratified.py  外源集按 Tanimoto 分层：AUC 是否随距离单调上升（E1 决定性实验）
> run_external_cuts_summary.py  三切点并排（时间混合 / ≥2021 / ≥2023）：哪条结论稳健、哪条是切法产物
> run_indifference.py          A4 无差异曲线（**2026-11-04 已撤回 / C18**）：脚本仅审计保留；
>   其 c*≈0.21–0.26 是 Δu(c)=a−q·c 会计恒等式的零点，不得用于推断（见 RETRACTION_NOTE §五）
> run_spec_multiverse.py       A6 规格敏感性：216 规格的方向翻转率（0.398 → fragile）
> run_independence_gradient.py A1 受控独立性梯度：共享训练比例 α 0→1 的机制检验
> run_leakage_confound_check.py E2 复核：近邻归因代理的负值成因（两候选机制均不成立）
> references/TAIL_RISK_THESIS.md        E1+E3：门的价值在尾部，不在平均（含认识论分层）
> references/CLAIMS_REGISTRY.yaml       17 条数字主张 → 产物路径 + 字面量（G10 真源）
> references/NEGATIVE_RESULT_DEFAULTS.yaml 8 条负结果 → 默认值（G11 真源）
> references/THRESHOLD_REGISTRY.yaml    11 条阈值的来历/冻结/敏感性（G12 真源）
> ```

> ### v4.7–v4.12 新增（评审整改 + 黑榜闭环；2026-11-03）
> ```
> adt/efflux_heuristic.py    P-gp/BCRP 外排共识药效团启发式（Seelig 1998 + Penzotti/Crivori 2002/2006）→ 三通道决议外排层「有结构依据的待验证假设」；强制 Caco-2 ± verapamil/elacridar 验证、不得进 reliab 计票（v4.11）
> adt/uptake_heuristic.py    OATP1A2 大体积有机阴离子 / LAT1 大中性 L-氨基酸 / GLUT1 仅游离单糖 共识药效团启发式 → 三通道决议摄取层「有结构依据的待验证假设」；强制过表达细胞 ± 竞争抑制剂验证（v4.12；SGLT1 因 BBB 内皮无功能表达不纳入）
> adt/stats_ci.py 增强       + holm()（Holm–Bonferroni 多重比较校正）；_z() 改标准正态分位数（修复 alpha/3 静默退回 1.96 的伪校正）；registration_gate / gate_pass_probability（F1 源注册门实现，**v4.13 起由 `adt.cli source-admit` 真实调用**，此前已单测但无任何执行入口）
> adt/bbb.py 增强           apply_dual_layer(rec, smiles=None) 现带 SMILES 时同时跑外排+摄取两套启发式，写入 rec["efflux_heuristic"]/["uptake_heuristic"]；postprocess 自动透传 rec.smiles（向后兼容）
> run_gate_audit.py         R19/R20 真实数据 gate 审计：三端点 AUC 三口径 + 95% CI（percentile bootstrap）+ 四态 verdict_ci + Newcombe 差值区间；--dump-scores 落盘逐分子分数
> run_gate_multiplicity.py  Holm 校正三端点 Fisher p（hERG/DILI/BBB_Martins）→ m=3 校正后无一项显著
> run_gate_metrics.py       校准斜率 / Brier / AP-lift / MCC / DCA / 富集因子 EF@k（读出「域过滤在决策净收益上为负贡献」「EF 饱和不可解读」）
> run_b2_coverage.py       BBB 转运体先验覆盖度量化（黑榜 B2）：转运体级 1/18、分子级 ≤7.1%，OATP2B1 仅黄酮专属；**v4.13 起产 `out_ext/tdc/b2_coverage.json` 并登记进脚本注册表 + 主张表**
> ```
> ### v4.13 全量可达性审计（2026-11-03/04）：把"写了但没人调"的东西接上线
> ```
> adt/cli.py source-admit   **新增命令**：F1 源注册门真实执行入口（registration_gate + gate_pass_probability）；输入 source,n,observed_failures，输出 n/observed_rate/ci_lower/ci_upper/passes/decision/disclosure_required
> adt/cli.py transfer       **新增 --truth**：此前 transfer.decided_accuracy 无任何 CLI 入口（死代码），现给 --truth 即算，不给则显式输出 not_evaluated
> adt/adapters/biotransformer.py  删除 batch_drift()：与 adapters/base.py:91 的 meta["batch_drift"] 重复且从未被调用
> adt/stats_ci.py          gate_pass_probability 返回值 float() 化（此前泄漏 np.float64 到输出）
> tests/test_help_all.py   CMDS 改为「静态清单 ∪ 源码自动发现」，覆盖 41/60 → 60/60 子命令（24 个此前从未做过 --help 冒烟）
> tests/test_transfer.py   新增 3 例：decided_accuracy 语义、--truth 存在性、source-admit 端到端（含 n 不足须带 CI 标注进入）
> run_b2_coverage.py       补 argparse + `out_ext/tdc/b2_coverage.json` 产物；登记进脚本注册表（此前从未入网）与 CLAIMS_REGISTRY → G10 26/26 → **27/27**
> ```
> **审计方法与结论**：模块级用「绝对导入 + 相对导入 + `from . import X` 三种形式的引用图」核对 → adt/ 下 0 个孤儿模块；
> 函数级用 vulture（AST）复核，60% 置信度报的 37 个函数逐个回查，**大多数其实活着**（测试/内部/注册表字符串引用），
> 真正不可达的只有 `transfer.decided_accuracy`（已接线）与 `biotransformer.batch_drift`（已删除）。
> 值得注意的是：`conformal_scale`/`defaults`/`threshold_audit` 一度被判孤儿，实为**函数体内** `from . import X as Y` 造成——正则审计会误报，AST 才是准绳。

> ### v4.14–v4.20 扩展（截图工具收编 + PK/PD；裁决书见 `references/EXTENSION_ANALYSIS_v4.14.md`）
> ```
> adt/ionization.py         **pKa/电离状态层**（v4.14）：可电离基团 SMARTS + **类别级文献 pKa 区间**
>                           → pH 7.4 电离分数区间 / 净电荷区间 / logD−logP 位移区间。
>                           补的是 00_scope 里写明的缺口（此前"本机没有可靠 pKa 源"，normalize 只按 SMARTS 猜电荷）。
>                           **禁止**把 pKa 点值当实测写入任何表；`pka_grade=literature_category_range` 随值输出。
> adt/cardiac_panel.py      **心脏离子通道三联**（v4.15）：hERG + Cav1.2 + Nav1.5 通道覆盖率闸门 +
>                           通道级裕度分档（Cmax,u/IC50 或 %抑制@Cmax）。**不做 ORd 净效应、不给概率**；
>                           只有 hERG 时 verdict 强制带 `herg_only_*` 并禁"已排除风险"表述。
> adt/pd_link.py            **PK/PD 连接**（v4.16）：Hill/Emax、效应室（ke0）、fT>EC50、fT>EC90、
>                           效应 AUC/峰效应/达峰、最小 TMDD（**缺 5 个参数直接抛错**，不许默认值凑）。
>                           EC50 与 C 量纲不一致时抛 PDParameterError（C71 教训）。
> adt/pbpk_qualify.py       **PBPK 资格认定**（v4.17）：AFE / AAFE / 2倍内 / 3倍内 / rmse(log10)，
>                           三条拒绝条件（n<5、每化合物<2 时点、单位不一致）。
>                           阈值明标 `convention`（EMA 2018 未规定通过线）。
> adt/interop.py            **外部 PK/PD 工具互操作桥**（v4.18）：PK-Sim 化合物参数表（含 unmapped 显式列表）
>                           + **OSP 快照导出**（`--snapshot`，Version 80）+ NONMEM/nlmixr2 数据集
>                           （含 EVID/MDV/排序契约校验 + **ID 必须整数** + **给药/观测腔必须分离**
>                           + **非正观测必须屏蔽** 四条硬校验）+ nlmixr2 R 骨架
>                           （`pk_initials()` 从 C(t) 推初值、`mask_nonpositive_obs()` 处理数值零）。
>                           **v4.21 起分级标注实测程度**：`validated_against_tool` 不再是一个布尔值——
>                           `pk_sim_cli_snap_passed`（PK-Sim 12.3 真机往返）/ `pharmpy_dataset_ok`（Pharmpy 2.3 真读）
>                           / `nlmixr2_fit_passed`（编译+收敛已过，但只有 V 可辨识）。
>                           见 `references/MODULE_MAP_v4.21.md` §4。
> adt/gut_microbiome.py     **肠道菌群代谢子模块**（v4.19）：BioTransformer `HGUT` + **biosystem 过滤**
>                           + **反应标注一致性 QC**（质量差 vs reaction_type）+ 阳性对照闸门 + 0 产物判 out_of_domain。
> adt/readback.py           **通用回填通道**（v4.20）：给"没有 API、只能在浏览器里跑"的工具
>                           （SwissADME / AOMP / Graph-pKa / CardioSafe / Cardiosim-Tox / MicrobeTCM / GutBugDB）
>                           一条合规入口：结构对齐（不符进 unmatched 报表）+ 未映射列报出 + measured 必须带显式引文。
> references/readback_schemas.yaml  各回填源的列映射；`endpoints: {}` = 列名未实测，必须 `--map`
> adt/cli.py                7 个新子命令：pka / cardiac / pd / pbpk-qualify / interop / gut-micro / readback
> adt/cli.py pbpk           + `--dump-curves`：落 C(t) 曲线（pbpk_curves.csv），直接喂 `pd`
> references/EXTENSION_ANALYSIS_v4.14.md  **逐项裁决书**：14 个工具的"加/不加/怎么加"与理由
> references/MODULE_MAP_v4.21.md  **模块全景 / 运营流程 / 交叉印证矩阵**（v4.21）：
>                           四层定位（L0 结构状态 / L1 证据采集 / L2 裁决 / L3 交付）、每模块"意义 + 不做会怎样"、
>                           10 步主链 + 三分支、五组"互相印证"矩阵（含"对不上时怎么办"）、本轮四条硬结论
> ```
> **这一轮的三个关键实测（都有产物，不是推断）**：
> 1. **pkCSM 仍然死，但死法变了**：域名迁到 UQ 后前端全活（首页 200、表单完整、示例页 200），
>    `POST /pkcsm/admet_prediction` 在 8/8 种 `pred_type` 下全 **500**；上传单列头文件同样 500
>    （说明**通过了校验、崩在预测引擎**）。→ 维持 `dead`，把 8 条复现证据写进注册表，
>    防止下一个人"基于首页 200"重新采纳。**首页能打开 ≠ 服务可用**。
> 2. **BioTransformer 的 `reaction_type` 是规则名，不是机理描述**：`HGUT` 对 APAP 产 3 个、
>    对 quercetin 产 7 个代谢物，但 **7/7 条 `reaction_type` 与质量差矛盾**
>    （4 个葡糖醛酸苷 Δm=+176.03 被标"脱羧"；2 条被标"羟化"而产物少一个 O，Δm=−15.99）；
>    同一次查询里还混进一条 `biosystem="Human"`。→ **只可引用 smiles/inchikey**，
>    且 **biosystem 过滤不是可选项**（否则人体代谢被算成菌群代谢）。
> 3. **"加源"几乎不提升准确率，只有补结构性缺口才提升决策质量**：本 skill 自己的 A1/S4
>    已证明同族多源增益 ≤0。所以本轮只加 5 个**新证据形式**，其余 9 个要么是死源、
>    要么无可验证入口（登记 `paper_only`），**不写适配器硬凑**。
>
> ---
> **v4.7–v4.12 这一轮最重要的四个结论**（三条对框架不利，照实记录）：
> 1. **【2026-11-04 已撤回 / C01】** ~~门的价值在尾部……域外强制预测在三个切分上
>    都崩（全部低于同批平凡基线）……**域外处处不可用；门全拒是"保守的正确"**~~。
>    旧句的唯一量化支点 `auc < always_positive_accuracy` 是**跨量纲比较**（AUC 基线
>    0.5；always-positive accuracy = prevalence）。正确双轨口径下
>    `accuracy_below_majority_class` = True/False/True，三切点为嵌套子集；
>    hERG 端点 estimand 未绑定实验金标准，AUC 不承载决策含义。
>    **不得翻转为"域外仍有弱排序能力"**；处置为 `inference_revoked_pending_estimand`。
>    保留项：「AUC 随 Tanimoto 单调上升」只在时间混合集成立、两个真时间留出切点
>    均判 `trend_not_robust`（与 C01 无关）。见 `references/RETRACTION_NOTE.md`。
>    正确产物：`out_ext/external/external_cuts_summary_v2.json`。
> 2. **【2026-11-04 已撤回 / C18 + 外审 A】** 旧表述「准入层优势是条件性的：
>    c\* ≤ 0.21–0.26 时 S4 才赢 / 存在条件性优势区」已撤回——Δu(c)=a−q·c 是
>    一阶线性会计恒等式，代价未进入决策 π(c)，「无差异点」只是该线性函数的零点，
>    不是可证伪结论。216 个规格方向翻转率 **0.398** 仅登记为规格敏感性
>    （有效 n=20，非 216 次独立实验），**不得**据此改写为条件性优势。
>    见 `references/RETRACTION_NOTE.md` §五。
> 3. **"共享训练数据"不是独立性瓶颈（A1，对框架不利）**：α 0→1 时误差相关
>    0.655→0.978（伪共识签名），但两源均值增益在所有 α 上都不为正——
>    **方法同源吃掉了大部分独立性红利**；"换个数据集重训同类模型"不构成第二个独立源。
> 4. **近邻归因代理无效（E2，对框架不利）**：两个候选机制（记忆驱动/一致率驱动）都不成立，
>    BBB 的 −0.212 **仍未解释**；该项从"部分关闭"**回退为未关闭**。
>
> ### ⚠ v4.4 自查更正（本包自己发现，不是评审提的）
>
> **那批被叫做 "post-cutoff 外源留出" 的分子（n=9443）不是 post-cutoff。**
> 时间条件交给了 ChEMBL 服务端 `document__year__gte`，而该端点**实测不执行**这个过滤：
> `>=2015/2021/2022/2023` 返回同一个 `total_count=19130`，缓存里 `document_year` 覆盖
> **1995–2025**，≥2023 仅占 **9.6%**。数字可逐位复现（`--year-mode none`），**错的是标签**。
>
> - 修：`fetch_activities` 改为**本地按 `document_year` 切分**，`year_filter` 元数据落盘；
>   顺手修掉 `_get()` "先 import requests 再查缓存"导致离线复现直接崩的缺陷。
> - 后果：真时间留出（≥2021 n=1941 / ≥2023 n=959）上，**桶级单调趋势不复现**（`trend_not_robust`），
>   故结论 1 的强表述被撤回。
> - 【2026-11-04 更正】~~仍在的：域外处处不可用~~ —— **这一条也已撤回（C01）**：
>   它同样由跨量纲比较推出，且三切点并不同向（y2021 方向相反）。v4.4 自查更正
>   本身（post-cutoff 标签错误）仍然成立且予以保留；被撤回的是由错误口径导出的
>   外部效度结论，不是标签更正。
>
> 这是本 skill 第四次"自己推翻自己"。判据：**一个连标签都能被自己查出来的框架，
> 才有资格要求别人相信它的数字。**

### 守护项（评审 v4.0 明确肯定，任何拔高不得削弱）
1. **科学自我意识**：负结果如实报、故障注入当证据、Simpson 假象自查、novelty claim 主动降级、C89 真 bug 自我暴露——这些是高分 SCI 审稿人最想看到、多数工作最缺的东西，列为不可删。
2. **证据准入先于证据组合**（核心贡献）：源资格是组合/排序/校准**之前**的独立、可审计、带归因决策层（**九类归因**：弃权归因 8 类 + 源可靠性归因 1 类，唯一真源见 `adt/abstain_attrib.TAXONOMY`；C7 更正）。
3. **结构不真全废**（铁律1）：无可争议，结构 gate 恒为第一关。
4. **kNN Tanimoto 域判别的诚实定位**（0.35 饱和 / 0.7 污染筛查）：做得比多数论文好，保留。
5. **G5 故障注入拦截正确性验证**：保留，并显式标注其仅为"充分性测试"，不替代必要性/合理性验证。
6. **复现性骨架**：每条结论挂 `out_ext/run_*.py`、G4 freeze/verify(sha256)/supersede/diff、换机复现指南、F0 wheel 实测、black-list 清零台账——升级为"**命令→数据hash→环境指纹→结论**"四元组（`manifest.json`）。

## 三条不可妥协的原则

1. **结构不真，后面全废。** 先过结构 gate（InChIKey 三级判定 + 一手数据），
   本项目 14 个分子里 2 个是错的，其中一次还是"用自建参照核对自家结构"的循环论证。
2. **不知道源能不能信，就不要投票。** 同一批 14 个分子，DILI 上四个源给出四种失效
   （ADMETlab 14/14 阳、ADMET-AI 0/14 阳、ProTox 13/14 阴、vNN 13/14 拒绝预测）。
   四个都在域外的模型投票，产出的是"3:1 阴性"这种假结论。
3. **排序默认关闭；只在校准证据充分且 n≥30 时才允许，且必须带不确定度。** 对定量回归端点
   （solubility、logD、CLint——恰是本框架处理的主力端点）排序/分层是 ADMET 优化的主要使用方式，
   故铁律 3 为**条件命题**而非无条件：*当校准证据不足或 n<30 时拒绝排序*；定量端点默认输出
   带不确定度的分位（bootstrap 名次区间，见 `rank`）。同一批分子换一套安全性口径，MPO 排序
   Spearman ρ 从 0.024 起跳，正是欠校准/小样本下排名不可信的实证。

### 九条红线（R34–R42 / 评审 §7.1 + 第三轮 §G）——**在生产路径上接线，不是文档承诺**

> 判定标准很简单：**能不能用一条命令绕过**。能绕过就不是红线。
> **2026-11-03 更正（C1）**：本节此前声称"九条全部落在 guards.py，由 G8 读它"，
> 而实测是：`guards` 里的守卫函数在**生产代码中零调用点**，`red_lines_status()`
> 返回的是**硬编码 `ok=True`**，G8 检查的是自声明。按本节自己的判据，
> 当时它们**都不是红线**。现已改为真接线：
>
> - 接线注册表：`adt/redlines.py::REGISTRY`（每条登记 `文件::函数::代码记号`）；
> - 机器自检：`python -m adt.redlines`（AST 探测生产调用点 + `REDLINE-<id>` 集成测试，
>   二者缺一即 FAIL）；发布门禁 G8 读它；
> - 文本类红线（6/7/8/9）在 `adt.cli report` **落盘前**统一开火：
>   任一命中 → **不写 `conclusions.md`**、落 `REDLINE_VIOLATIONS.md`、`exit 4`；
> - 成对回归：`tests/test_v44_guards.py`（违反必抛 + 合规必放行）+
>   `tests/test_redline_wiring.py`（subprocess 端到端绕过尝试）。
>
> **硬度必须如实引用（禁止合并表述）**：当前 **7 hard / 1 soft / 1 conditional**。
> 红线 1 是 soft（默认告警 + `--strict-input` 升级），红线 3 是 conditional
> （仅 `--publish` 阻断）。任何材料写"九条全部阻断"均属**不准确**，会被
> `hardness_census()` 的字符串对不上。

| # | 红线 | 守卫 / 落地位置 | 违反时 |
|---|---|---|---|
| 1 | 禁止名称→SMILES 直连；入口必须 **InChIKey 锚定**；立体缺失即 fail | `pubchem.pipeline_guard` + `guards.admission_line`；`normalize` 默认产出 `input_gate.csv`，`--strict-input` 时返回码 3 | `NormalizeInputError` |
| 2 | **n<30 打横幅**；**n<10 只出定性结论** | `guards.sample_size_guard`；`reliab` 入口自动打印 | level=qualitative 时禁报率/差/排序 |
| 3 | 论文/决策数字**必须**来自快照重放模式 | `guards.require_replay` + `snapshot.replay`（`ADT_REPLAY=1`） | `ReplayRequired`；应急 `ADT_ALLOW_ONLINE=1` 会留 `override=True` 痕 |
| 4 | DILI/Ames 等需 `--i-accept-low-validity` 且**留痕** | `guards.low_validity_line` + `reliab --i-accept-low-validity` + `endpoint_tier_blocks.csv` | `LowValidityError` |
| 5 | 商用必须 `--profile commercial`，**调用日志归档** | `compliance.enforce`（基类强制，绕过 CLI 也拦）+ `compliance.archive_call`（`ADT_CALL_LOG`） | `ComplianceError` |
| 6 | 禁无区间措辞；**护栏不可关闭** | `phrasing.flag_unqualified_superiority` + `guards.interval_line` | `RedLineError` |
| 7 | **gate 判别力数字必须带「评测分布」+ **95% CI**；域内 AUC 不得用来评价门 | `guards.gate_distribution_line(stmt, eval_distribution, auc, auc_ci)` | `RedLineError`（C3：点估计与约定工作点比较不再作为判据） |
| 8 | **外源/时间留出数字必须同句标「非预注册前瞻」，且不得把回溯式年份切分叫 post-cutoff** | `guards.provenance_line(text)` | `RedLineError` |
| 9 | **端点依赖类结论必须三端点并列**，禁单端点外推 | `guards.endpoint_plurality_line(claim, endpoints)` | `RedLineError` |

注意红线 4 与红线 2 的**方向相反**：红线 4 允许"显式自担风险后使用低有效性端点"，
红线 2 则不允许"小样本假装正常"。前者是知情选择，后者是伪装。

**红线 7–9 的来历（第三轮评审 §G，每条都对应本包自己踩过的坑）**：
- **7**：hERG 上 gate AUC 0.580 曾被写成"门没用"——而那次评测是**域内**（TDC 随机切分），
  门在域内没有可增加值，AUC≈0.5 是构造必然。门只能靠**域外强制预测**评价。
- **8**：0.581 一度被与"前瞻"并置。该设计是 temporal external validation，
  阈值与口径是见到数据后才定的，**不是**预注册前瞻。
  **v4.4 追加**：连"temporal"这个标签都曾用错——服务端年份过滤失效，那批分子其实是时间混合集
  （`document_year` 1995–2025，≥2023 仅 9.6%）。现在是**本地切分**的两个时间留出集
  （≥2021 / ≥2023），且标签与产物内的 `year_filter` 元数据必须对得上。
- **9**：hERG/BBB 判"模型对悬崖迟钝"后曾外推到 DILI——而 DILI 只有 31 对 MMP
  （需 61），状态是 `insufficient_power`，是"测不了"不是"有病"。

### 本框架的核心贡献（证据准入先于证据组合）
多数集成框架将源资格**隐含在组合器内部或假定为已解决**；本框架将源资格**显式化为独立、可审计、带归因的决策层**（16 模块 + adapters，单向数据流），并用真实双源 / 时序前瞻 / 污染筛查数据给出实证。九类归因（弃权 8 类 + 源可靠性 1 类，`adt/abstain_attrib.TAXONOMY`）+ 计票账目使"为何拒信"可反查。这是评审 v4.0 确认的真实贡献（原"共同跳过"措辞已删，防御性更强），任何拔高不得削弱。

## 本地无 API 工具（local_admet）——admet-pkpd 6 个工具的离线替代

`admet-pkpd` skill 的 6 个工具（ADMET Predictor / AOMP / OBA / Graph-pKa / DeepEsol /
Molecular Descriptors）原本通过 **SciMiner API** 调用（需 `~/.config/sciminer/credentials.json`
+ 账户积分）。**积分不足或无法联网时**，用本 skill 随包的 `local_admet/` 子包离线运行，
无需 API、key、积分、网络。

| 原工具（SciMiner） | 本地函数 | 本地方法 | 保真度 |
|---|---|---|---|
| Molecular Descriptors | `molecular_descriptors()` | RDKit 精确计算 | **高** |
| DeepEsol | `deep_esol()` | Delaney ESOL 溶解度 + ΔG 代理 | 中 |
| Graph-pKa | `graph_pka()` | 官能团 SMARTS + 文献 pKa 经验值 | 低-中 |
| OBA | `oba()` | Martin(2005) 评分 + 剂量-溶解度粗判 | 低 |
| AOMP | `aomp()` | AOX 结构警报 + SOM 启发 | 低 |
| ADMET Predictor | `admet_predictor()` | 多端点规则/警报筛查 | 低 |

```bash
# 列出工具 / 自检（6 分子 × 6 工具）
python -m local_admet --list-tools
python -m local_admet --selftest

# 单分子单工具（JSON）；--tool all 一次跑 6 个
python -m local_admet --tool "Molecular Descriptors" --smiles "CC(=O)Oc1ccccc1C(=O)O"
python -m local_admet --tool all --smiles "Cn1cnc2c1c(=O)n(C)c(=O)n2C"

# 批量（每行：SMILES [id]）；只跑 ADMET Predictor 的毒性类(T)
python -m local_admet --tool "ADMET Predictor" --smiles-file lib.smi --features T --out out/admet.json

# 输出 measurements.csv 兼容长表（source=local_admet, domain_flag=predicted）
python -m local_admet --tool "Molecular Descriptors" --smiles-file lib.smi \
    --format long --out out/local_admet_desc.csv
```

**诚实边界（必须遵守，否则视为误用）**：

- 这些是 **`rule-based-local-proxy`**，**不是** SciMiner 训练模型；数值仅供**筛查排序**，
  **不得**当作 SciMiner 输出、**不得**用于对外定论或论文数字。
- `ADMET Predictor` 的 `prob_proxy` 是**名义值**，不是校准概率；`E` 类（清除/t½）尤其粗糙。
- `Graph-pKa` 不建模取代基/邻位效应；`DeepEsol` 的 `dG_solv_proxy` 与真实 ΔG_solv **不等价**。
- `--format long` 的 `source=local_admet` **不在** `references/02_source_registry.yaml` 注册源内，
  属**探索/筛查层**，**不得**直接进 `reliab` 计票；需正式数据时走 `readback`（带 `--provenance-url`）
  回填实测，而不是把它冒充预测源。
- 详细说明见 `local_admet/README.md`。

## 结构干扰红旗层与源健康探针（2026-11-11 新增，全离线）

**补齐的缺口**：「PAINS / 邻苯二酚 / 醌类等易报假阳性的结构，务必过滤」此前在本 skill
**只有教训、没有代码** —— 全库 PAINS 仅出现在文档/yaml（含 `04_decision_funnel.md:63`
「阶跃硬红旗」的设计意图）；`adt/alerts.py` 是 ICH M7 致突变专家规则，
`transport.py::chemotype_flags` 的邻苯二酚 SMARTS 是转运体/成醌机制用，
两者都不是实验干扰过滤层。现由 `adt/interference.py` 补齐，基于 **RDKit 自带
FilterCatalog**：无需 API、key、积分、联网。

**覆盖与分档**（实测 RDKit 2026.09.1 条目数）：

| catalog | 条目 | 分档 |
|---|---|---|
| PAINS_A / B / C | 16 / 55 / 409 | `strong` → `suspect_interference` |
| BRENK / NIH | 105 / 180 | 默认 `weak`（开发性官能团警报，非实验干扰证据） |
| BRENK 两条例外 | `beta-keto/anhydride`、非酸上下文的 `Michael_acceptor_1` | `strong` |

分档依据是 **catalog 来源 + 结构上下文，不是规则名**。这里纠正一次实测误读：
`Michael_acceptor_1` / `catechol` / `beta-keto/anhydride` **全部来自 BRENK**，
真正的 PAINS 条目是 `catechol_A(92)`（PAINS_B）—— 把 5 个 catalog 合并成一个
会看不见这点，本模块因此为每个 catalog 单独建实例。
`Michael_acceptor_1` 且分子是 **α,β-不饱和羧酸/酯** 时保持 `weak`：依据
`alerts.py` 已记录该子类（肉桂酸/对香豆酸/咖啡酰）多为 GRAS、Ames 阴性，
以及 C87 松 SMARTS 把愈创木基误判成邻苯二酚的教训。

**三条纪律**：

1. **红旗层不是一票**：`not_a_vote=True`，不产生 verdict、不写 measurements 长表、
   不进 `reliab` 计票。只给 `flag` + `gate_action`。
2. **永不判 FAIL、永不淘汰分子**：PAINS 命中 ≠ 化合物无效，只说明该次检测/计算
   可能不可信。类药性（Lipinski/Veber/QED）同样 `admissible_for_rejection=False`
   —— 实测 WBLG-A/B 的 Veber 均为 False，若当淘汰判据会直接误伤糖苷类天然产物。
3. **措辞封顶**：`suspect_interference` → 结论须降级/转 UNDETERMINED 并做正交实验确认；
   `weak_only` → 单列「需实验确认」，不折减既有结论、不得写确认阳性。
   `claims_audit --interference-phrasing` 把这条做成可执行断言。

```bash
# 7 例正/负对照自检（含 C87 愈创木基回归）
python -m adt.cli interference --selftest
python -m adt.cli interference --in out/compounds.csv --outdir out_interference
python -m adt.cli interference --smiles "CC(=O)Oc1ccccc1C(=O)O" --compound-id aspirin

# 源健康：只做 GET、带时间戳、不提交预测作业、不自动改写注册表
python -m adt.cli source-health --outdir out_source_health --timeout 8

# 干扰措辞封顶审计（flags 由 interference 产出）
python -m adt.claims_audit --interference-phrasing \
    --flags out_interference/interference_flags.csv --texts report.md
```

**实测（2026-11-11，本机）**：自检 7 例全过（姜黄素/EGCG/槲皮素/咖啡酸判红旗，
咖啡因 0 命中，阿司匹林 `weak_only`，阿魏酸不命中 catechol）；真实
`out_wbh/compounds.csv` 的 WBLG-A/B 均为 `weak_only`（不饱和酯 GRAS 子类，
`n_strong=0`）；两次批量产物 CSV/JSON 的 sha256 **逐字节一致**；
源健康探针 4 个源首页**全部 200**，而 pkCSM 注册表仍为 `dead` —— 实证
「首页 200 是引诱」，探针不据此升级状态。

**端点口径补强**：`03_endpoint_rules.yaml` 新增 `f_oral`（`role=reference`、
`shape=none`，不进计票），**三分口径** `assumption | predicted_proxy | measured`：
PBPK 里手工设的 Fa（王百合苷案例 0.26）是**情景假设**，写成「预测 F」或
「实测 F」都是误用；且 `F = Fa·Fg·Fh`，Fa 与 F 不是同一 estimand。
另加 `not_covered_endpoints` 顶层段，**显式登记 5 个真实缺口**：CYP 诱导、
CYP TDI、胶体聚集、荧光干扰、成醌/氧化还原循环（部分覆盖）—— 静默缺失会让下游
误读成「已评估且阴性」。`VERSION_POLICY.yaml` 台账同步补登记 4.22→4.25，
修复 `test_version_divergences_all_declared` 的真实失败（不靠改数字假统一）。

**诚实边界**：PAINS/BRENK/NIH 是**结构警报**，不覆盖胶体聚集、荧光/发光干扰、
氧化还原循环的定量判据（已登记 `not_covered`）；命中不等于化合物无效，
未命中也不等于已排除干扰。`source-health` 只做 GET，`prediction_available`
恒为 null，状态升级必须人工跑通一次真实预测并留第一手证据。以上均为规则型
离线筛查，不是训练模型，**不得**用于对外定论或论文数字。

**全量套件的既有环境性失败（2026-11-11 实测登记，非本轮引入）**：`pytest tests/`
跑到 `test_smoke_pytest.py` 的 SCRIPTS 末尾时，4 个红线相关 `test_script_passes`
会因 `redlines._run_redline_tests` 的第三层 subprocess 集成节点返回全 False 而失败；
**单独跑 4 个红线文件、单独跑对应 smoke 参数、模拟两层调用（python script → pytest）
均 rc=0**，`adt.redlines` 九条自检也全 OK。属长跑后的嵌套环境抖动（smoke 注释已记录
rdkit C 扩展 0xC0000005 偶发并为此加了重试）。全量日志 `logs/pytest_full_20261111.log`
（6 FAILED）→ `logs/pytest_full_20261111_v2.log`（4 FAILED；未登记测试文件、
`FLAG_WEAK_ONLY` 命名误撞、版本守卫 3 项已修）。**刻意不改红线核心**去掩盖这 4 项：
那会改变 9 条红线的判定行为，风险大于全绿的收益。

## 补齐登记不接线、物理干扰层与统一入口（2026-11-11 第二轮，全离线）

### 缺口是怎么界定的

「补齐」以**可静态举证的缺口**为准，不臆造新功能、不加第 N 个预测源
（`BLACKLIST_CLOSEOUT.md` 实测三源误差相关 0.80–0.91，加源稀释可信度）。
盘点 `adt/` 85 个模块、70 个 CLI 命令、测试引用矩阵与自登记缺口后，确认 4 类：

| 缺口 | 证据 | 本轮处置 |
|---|---|---|
| **登记表不接线（C82 复发）** | `not_covered_endpoints` 只有 `tests/test_interference.py` 读，`adt/` 零生产调用；`07_case_lessons.md` C82 已记录同类坑 | 新增 `adt/coverage_gate.py`，接进 `report` 与 `claims_audit` |
| **物理/光学/反应性干扰无实现** | `colloidal_aggregation` / `fluorescence_interference` 登记 `not_covered`；PAINS 层识别不了这三类 | `interference.py::physical_interference()` 补离线结构预警，状态升 `partially_covered` |
| **6 工具只有子包入口** | `local_admet` 未出现在 `adt/cli.py`，主 CLI 调不到 | 新增 `adt.cli local-tools` |
| **9 个命令无文档 / 3 个模块零引用** | `SKILL.md` 只提到 61/70 命令；`paired_stats`/`saturation`/`tdc_local` 无直接测试引用 | 补命令索引 + 补回归测试，明确零引用模块的定位 |

### 1. 未覆盖端点强制声明（C82 闭环）

`report` 生成结论段时**无条件追加**声明段；生成失败即 `exit 4`（与红线同级，
不写半成品）。改 `not_covered_endpoints` → 声明自动变化 → 缺标记被
`claims_audit --coverage-declaration` 检出，**e2e 已实跑**：注入删掉
`cyp_tdi` 的规则表后，产物少一条标记、校验立即报 `missing=['cyp_tdi']`。

```bash
python -m adt.cli coverage-gate --selftest           # 正反双向 4 例
python -m adt.cli coverage-gate --emit               # 打印声明段
python -m adt.cli coverage-gate --check report.md    # 缺标记即 exit 1
python -m adt.cli coverage-gate --outdir out         # 写 coverage_declaration.md
python -m adt.claims_audit --coverage-declaration    # 扫活跃文本 + out*/conclusions.md
python -m adt.cli report --reliability out/reliability.csv --outdir out

# ---- v4.33：G14 外部对照台账（统计量必须与参考实现逐点一致，release-check 会实跑复核）----
python -m adt.cli external-compare --selftest        # 6 模块 28 点：ours vs scipy/闭式/独立复算
python -m adt.cli release-check | grep G14           # 门禁项：实测偏差超台账容差即 blocker

# ---- v4.27：estimand 绑定门（G13；C01 跨量纲撤回的可执行防复发）----
python -m adt.cli estimand --selftest                          # 6 例正反自检
python -m adt.cli estimand --compare auc always_positive_accuracy   # 跨量纲 -> exit 4
python -m adt.cli estimand --claim "域外没有排序能力" --endpoint hERG  # 未绑定推断 -> exit 4
python -m adt.cli estimand --text "AUC 低于 always-positive accuracy" # 已知违规式 -> exit 4
python -m adt.cli estimand --artifact out_ext/external/external_cuts_summary_v2.json

# ---- v4.28：证据链 / 可信度工具 ----
python tools/bind_claim_fields.py              # 主张字段绑定的 dry-run 生成器（--write 才落盘）
python tools/independent_recompute.py          # 第二实现者交叉复算（24 项独立核验，rc=4 表示不一致）
python -m adt.cli knn-sensitivity --selftest   # kNN Tanimoto 阈值敏感性自检
python -m adt.cli knn-sensitivity --outdir out_sensitivity   # 真实数据网格扫描（关闭 RISK_COVERAGE §3 欠账）
python -m adt.cli env-audit --quiet --required-only          # CI 友好：必需层全绿即 rc=0
# 定位/对标证据链见 references/POSITIONING_EVIDENCE_2026-11-18.md（联网核实，含 prior-art 风险排序）
```

审计语义：纯方法学文本 `applicable=False`（**不误伤**）；出现 CYP/DDI 类结论
则 `cyp_induction` 与 `cyp_tdi` 为硬要求，缺任一即违规。这两项
`required_evidence` 是湿实验，**代码不会补造计算值**。

### 2. 物理 / 光学 / 反应性干扰结构预警

`interference.py::physical_interference(mol)` 在 PAINS 层之外补三类，同为
**规则型离线代理**：`not_a_vote=True`、`admissible_for_rejection=False`、
`requires_experiment=True`，flag 只有 `suspect/possible/none`，**没有 FAIL 态**。

| 类别 | 判据（公认经验，非训练模型） | 正交实验判据 |
|---|---|---|
| 胶体聚集 | cLogP≥3 且芳香环≥2 → `suspect`；单因子 → `possible`（Aggregator Advisor 主要风险因子） | ±0.01% Triton X-100 对照 + DLS/NMR |
| 自荧光/内滤 | 香豆素·色酮发色团或共轭双键≥4 → `suspect`；多酚≥2 OH 或芳环≥3 → `possible` | 无酶/无靶本底荧光 + 内滤测定 |
| 成醌/氧化还原 | 严格 SMARTS：邻苯二酚 / 对苯二酚 / 邻氨基酚 → `suspect` | GSH 捕获 + HRMS/MS（±NADPH） |

**C87 纪律复验**：咖啡酸（邻苯二酚）判 `suspect`，阿魏酸（愈创木基 4-OH-3-OMe）
判 `none` —— 严格 SMARTS 不会重演旧松匹配把 8 个数成 5 个的误判。
产物新增 `phys_aggregation` / `phys_fluorescence` / `phys_redox_cycling` /
`phys_requires_experiment` 四列，CSV+JSON 仍逐字节确定。

### 3. 主 CLI 统一入口

6 个离线工具此前只能 `python -m local_admet ...`；现在 `python -m adt.cli local-tools`
参数形态完全一致（显式重建 argv，不用 `REMAINDER`——实测它把 `--list-tools`
交给主解析器报 unrecognized arguments）。每次调用都打印代理边界提示。

```bash
python -m adt.cli local-tools --list-tools
python -m adt.cli local-tools --tool "Molecular Descriptors" --smiles "CC(=O)Oc1ccccc1C(=O)O"
python -m adt.cli local-tools --tool all --smiles "Cn1cnc2c1c(=O)n(C)c(=O)n2C"
python -m adt.cli local-tools --tool DeepEsol --smiles-file lib.smi --format long --out out/esol.csv
# 长表默认带运行时间戳；--deterministic 写固定占位，两次运行可逐字节比对
python -m adt.cli local-tools --tool DeepEsol --smiles-file lib.smi \
    --format long --deterministic --out out/esol_det.csv
```

### 4. 此前已注册但无文档的 9 个命令

| 命令 | 用途 |
|---|---|
| `endpoint-tiers` | 端点分级证据（T1/T2/T3）与可裁决性 |
| `env-fp` / `env-audit` | 运行环境指纹 / 环境审计（OneADMET SI、ORCA、外部工具） |
| `indep-power` / `indep-bayes` | 独立性检验功效 / 贝叶斯对照 |
| `prereg-status` | 预注册哈希链状态 |
| `release-check` | 发布门禁 G1–G12 汇总 |
| `snapshot-summary` / `snapshot-verify` | 快照摘要 / 逐字节重放校验 |

`paired_stats`（被 `mmp.py` 调用）、`saturation`（被 `abstain_attrib.py` 调用）、
`tdc_local`（TDC 本地 CSV 回落，无生产调用）均补了回归测试；`tdc_local`
定位为**备用回落模块**，不是主链路必需件，不伪装成已接入。

### 未覆盖端点声明（强制 · 由 coverage_gate 自动生成）

> 本节由 `adt/coverage_gate.py` 读 `03_endpoint_rules.yaml` 自动生成；
> **任何 CYP / DDI / 安全性结论都必须连同本节一起引用**。
> 未覆盖 ≠ 阴性结论；`partially_covered` 仅表示有结构级预警，
> 仍无实验判据，不得据此下 PASS/FAIL。

- <!-- coverage:colloidal_aggregation --> **colloidal_aggregation**（胶体聚集导致的假阳性）：**部分覆盖（仅结构预警）**。
  - 现有覆盖：adt/interference.py::physical_interference（cLogP≥3 且芳香环≥2 → suspect；离线结构级预警，不投票、不判 FAIL）
  - 缺口：2026-11-11 补上结构级预警，但仍是 rule-based proxy：无浓度依赖、无去污剂对照、无 DLS/NMR 实测，不得据预警下「已聚集/已排除」结论
  - 所需证据：±0.01% Triton X-100 的活性/抑制曲线对比 + DLS 或 NMR 聚集证据
  - 约束：与 PAINS 互补，不是同一机制；命中 PAINS 不等于会发生聚集。
- <!-- coverage:cyp_induction --> **cyp_induction**（CYP 诱导（PXR / AhR / CAR））：**未覆盖**。
  - 缺口：ADMETlab 3.0 的 122 列里没有 CYP 诱导端点（02_source_registry.yaml 已实测登记）
  - 所需证据：人肝细胞 PXR/AhR 报告基因或 mRNA/酶活诱导倍数（≥2 独立供体）
  - 约束：抑制 ≠ 诱导。只报 CYP 抑制就下「无 DDI 风险」结论属系统性漏洞。
- <!-- coverage:cyp_tdi --> **cyp_tdi**（CYP 时间依赖抑制（TDI / 机制性失活））：**未覆盖**。
  - 缺口：目前只在 04_decision_funnel.md 的湿实验清单（第二批）里，无任何计算实现
  - 所需证据：±NADPH 预孵 0/15/30 min 的 IC50 位移，或 kobs / k_inact / K_I
  - 约束：可逆抑制 IC50 不能替代 TDI；DDI 结论必须显式标注本项未覆盖。
- <!-- coverage:fluorescence_interference --> **fluorescence_interference**（荧光/发光检测干扰（自荧光、淬灭））：**部分覆盖（仅结构预警）**。
  - 现有覆盖：adt/interference.py::physical_interference（香豆素/色酮发色团、共轭双键≥4、多酚内滤 → suspect/possible）
  - 缺口：2026-11-11 补上发色团与共轭体系的结构预警，但无激发/发射光谱、无内滤定量，不得据预警给出实测光学结论
  - 所需证据：无酶/无靶对照下的化合物本底荧光与内滤效应测定
  - 约束：中药多酚/黄酮类高发；须用正交（非光学）读数复核。
- <!-- coverage:redox_cycling --> **redox_cycling**（氧化还原循环 / 成醌反应性）：**部分覆盖（仅结构预警）**。
  - 现有覆盖：Gate 3 定性提示 + transport.py 化学型 + interference.py 严格 SMARTS（愈创木基不命中，C87 回归）
  - 缺口：只有定性提示/结构预警，无 GSH 加合物与过氧化氢定量
  - 所需证据：GSH 捕获 + HRMS/MS（± NADPH）、或 DCFH/过氧化氢定量

> 登记与产物一致性：改 `not_covered_endpoints` 后本段自动变化；
> 缺任一 `<!-- coverage:<id> -->` 标记即视为声明不完整（可用
> `python -m adt.claims_audit --coverage-declaration` 校验）。

## 流程（10 步，详见 references）

```
Gate 0    结构真实性        InChIKey 三级 / 糖基切片 / 取代位 / 3D 手性（含镜像对照）
Gate 0.5  分子状态标准化    去盐 / 电荷中和 / 互变异构（**必须保立体**）
Gate 1    理化 + 化学稳定性  logD7.4 / 溶解度 / 剂量数 / pH-血浆稳定性
Gate 2    渗透与转运        Caco-2·PAMPA（≥2 源同向）/ P-gp 外排比
Gate 3    代谢与反应性      SOM/BDE + 反应性（成醌/GSH）+ 代谢产物
Gate 4    安全              hERG / DILI / Ames / 致癌 / 内分泌  —— 先做饱和扫描
Gate 5    靶点结合（可选）   多构象对接 → Pose_conf → 必要时 MD / MM-GBSA
Gate 6    暴露与安全裕度     fu → Cmax,u → Margin = IC50,u / Cmax,u（只给三档）
Step 9    输出               PASS / FAIL(reason) / UNDETERMINED(补哪个实验)
Step 10   实测回写           重算源权重、重算适用域中心、连续 2 批恶化自动降级
```

## 命令

```bash
# 换机可复现：先跑 `python bootstrap.py`，再 `python -m adt env-audit --quiet --required-only`（rc=0 才继续）。
# 注意退出码语义：0=必需层全绿 / 1=必需层缺失（阻断）/ 2=仅可选或外部层告警。
# 裸 `--quiet` 在可选层缺 6 项（pytdc 运行集等合法可选状态）时返回 2，此时**可以继续**——
# 判据是报告里的"必需层缺失: 无"。若要在 CI 里用 `&&` 链，加 `--required-only` 即可让 rc=2 归一为 0。
# 解释器一律用环境变量，不要写死任何一台机器的绝对路径（详见 SETUP_REPRODUCE.md）。
PY="${PYTHON:-python}"

# 环境层：一键重建 + 机器可判的自检
$PY bootstrap.py
$PY -m adt env-audit --quiet

# Gate 0.5：标准化，产出 compounds.csv（calc_smiles 才是送进所有源的 SMILES）
$PY -m adt.cli normalize --in hits.txt --outdir out

# QA gate #11：全端点饱和扫描（对任何宽表都能跑）
$PY -m adt.cli saturate --wide source_wide.csv --outdir out

# 代谢产物（BioTransformer REST，2 POST/min，实测可用）
$PY -m adt.cli bt --in out/compounds.csv --outdir out --option CYP450 PHASEII

# 反应性（XenoSite 无免费 API，只能人工跑 + 回填）
$PY -m adt.cli xeno-prep   --in out/compounds.csv --outdir out
$PY -m adt.cli xeno-ingest --file xenosite_readback.csv --outdir out

# 适用域 + 真值参照（ChEMBL，无需 key；v2.2 参照层已做单位/方向归一）
$PY -m adt.cli chembl --in out/compounds.csv --outdir out --threshold 40

# 网页源（v2.2 收编进 skill，不再依赖项目级脚本）
$PY -m adt.cli web --source admet_ai  --in out/compounds.csv --outdir out
# 本地离线（无需网络；需 admet-ai 包，与网页服务权重不同版本，勿混用）
$PY -m adt.cli web --source admet_ai --in out/compounds.csv --outdir out \
    --local --local-python "$ADMETAI_LOCAL_PYTHON"   # 指向装了 admet-ai 包的解释器
$PY -m adt.cli web --source protox3   --in out/compounds.csv --outdir out
$PY -m adt.cli web --source admetlab3 --in out/compounds.csv --outdir out
$PY -m adt.cli web --source vnn --in out/compounds.csv --outdir out   # 需凭据（env 或 ~/.workbuddy/vnn_cred.json）
$PY -m adt.cli web --source vnn --in out/compounds.csv --outdir out --prepare-only  # 无凭据时的人工桥

# 域外端点会在 reliab 入口按 registry 的 blocked_endpoints_in_class 自动置 out_of_domain
# （--no-class-blocks 可关闭，仅用于对照实验；--chemical-class 指定化学类）

# 长表契约校验（predicted/measured 空值、measured 无 provenance 都会拦）
$PY -m adt.cli validate --in out/measurements.csv

# 合并多源长表（v2.7.0）：全流程断点补齐——多源 measurements 拼一张表（去重 + 契约校验）
$PY -m adt.cli merge --inputs out/measurements_admet_ai.csv out/measurements_admetlab3.csv \
    out/measurements_protox3.csv out/measurements_vnn.csv --outdir out

# desirability + Pareto（同轴几何平均；默认不排名，只给前沿）
$PY -m adt.cli desire --in out/reliability.csv --outdir out \
    --rules references/03_endpoint_rules.yaml

# 多源裁决（PASS / FAIL / UNDETERMINED，绝不输出综合分）
#   独立性分组自动从 registry 读取；输出带 allowed_statement（措辞封顶）
#   每次运行自动写 run_manifest.yaml（判据版本预注册）
$PY -m adt.cli reliab --in out/measurements.csv --outdir out \
    --rules references/03_endpoint_rules.yaml \
    --saturation out/admetlab_results_saturation.csv
#   v3.3.0：当 BBB 端点（vnn_bbb 等）裁决为 UNDETERMINED/PASSTHRU，reliab 内部自动强制
#   改写 action 为"P-gp 底物概率评估（双层机制）"并激活 transporter_priors.yaml 先验/assay
#   处方；输出带 bbb_mechanism=dual_layer_activated 列，可审计（不再泛泛"补实验"）
#   v4.4：Ames 的 ICH M7 双方法现已真实接线（不再是"只写文档"）：
#     --compounds out/compounds.csv   # 含 compound_id,calc_smiles；默认在输入同目录/cwd 找
#     --enable-alerts                 # 默认开：用 SMILES 跑 adt/alerts.py，置 expert_rule_layer
#     --no-alerts                     # 关闭（ames 维持 UNDETERMINED，仅用于对照实验）
#   启用后 ames 出真实 PASS/FAIL/UNDETERMINED，并写 expert_rule_layer/alert_hit 列留痕；
#   找不到 compounds.csv 时不静默放行——ames 仍 UNDETERMINED（ICH M7：两法缺一不判）

# 证据台账（每条结论反查支撑记录；unsupported 必须先修证据或改结论）
$PY -m adt.cli ledger --reliability out/reliability.csv \
    --axis out/axis_scores.csv --measurements out/measurements.csv --outdir out

# 端点级覆盖率矩阵（源 × 端点：有没有可判值；全 NoPrediction ≠ 阴性）
$PY -m adt.cli coverage --in out/measurements.csv --outdir out

# PBPK + 安全裕度反推（v2.4.0）：Cmax/F/t½，并把 IC50 接进暴露框架算 Margin 与剂量上限
$PY -m adt.cli pbpk --in out/measurements.csv --compounds out/compounds.csv \
    --exposure out/exposure_screening.csv --dose-mg 100 --ic50-list 11.2,2.5,30,50 --outdir out
# ↑ IC50 用证据锚点（assets/herg_reference_ic50.csv，11.2 µM 为最接近骨架的几何均值）

# 转运体先验（v2.5.0）：**决策清单，不是预测**——告诉你该做哪个实验
$PY -m adt.cli transport --in out/compounds.csv --outdir out

# SAR 预筛轴（v3.3.0，深水区拔高 2.1）：TPSA/MW/HBD/HBA/XlogP 与 BBB± 参照集比较，
# 输出"结构-通透性瓶颈"诊断（被动渗透筛选 + 最近邻 + 瓶颈因子）
$PY -m adt.cli sar --in out/compounds.csv --outdir out
#   compounds.csv 需含 compound_id,input_smiles,calc_smiles（calc_smiles 为标准化后送源的 SMILES）

# acyl glucuronidation 结构警示（v3.3.0，深水区拔高 2.3）：羧酸存在 / α-碳取代 / 共轭程度
# -> 风险分级（high/medium/low）。这是结构警示 + 风险分级，不是外部预测端点
$PY -m adt.cli acyl-glucuronide --in out/compounds.csv --outdir out
#   报告里所有糖苷（酯键，无自由羧酸）将判 low；自由羧酸苷元（如咖啡酸/阿魏酸）判 high

# 稳健 Z 背景归一化（v2.6.0，移植反向对接 E6a）：相对"同化学型背景"的异常度
#   默认 within-set（以本批为背景、留一法）；--bg 给外部背景长表（跨化学型）
#   输出 z / z_sd / SCALE_CONFLICT：z_mad 与 z_sd 差>1.5 时**不得静默取一个值**
$PY -m adt.cli background --in out/measurements.csv --within-set --outdir out

# bootstrap 名次区间 + 并列集合（v2.6.0，移植 E7c）：默认**拒绝** underpowered 排名
$PY -m adt.cli rank --in out/axis_scores.csv --outdir out
#   n<30 或未给簇占比时只写空表；演示须 --force，产物标 OVERRIDE，不得作正式排名

# 独立分类基准（v2.6.0，移植 E8 并按分类域改造）：AUROC/AUPRC + 聚类 bootstrap + 消融
$PY -m adt.cli benchmark --predictions out/measurements.csv --truth truth.csv --outdir out
$PY -m adt.cli benchmark --demo --outdir out     # 合成真值，仅验证指标代码，非科学结论

# 运行档位 + 项目级结论封顶（v2.6.0，移植 E0/T1-T3）
$PY -m adt.cli tier --reliability out/reliability.csv --coverage out/coverage_matrix.csv \
    --benchmark out/benchmark.csv --request T3 --outdir out   # T3 越级会被拒

# 肠肝循环：结构层 + 参数边界扫描（fbile×fre），量化"缺 EHR"能偏多少
$PY -m adt.cli pbpk --in out/measurements.csv --compounds out/compounds.csv \
    --dose-mg 100 --ehr-scan --outdir out
$PY -m adt.cli pbpk ... --fbile 0.23 --fre 0.6        # 有实测时直接用单点

# 阈值敏感性（E3：阈值是文献起点值，必须报告结论对它有多敏感）
$PY -m adt.cli sensitize --in out/measurements.csv --outdir out --factors 0.2 0.5

# 适用域阈值摄动（v3.0.0 / Sahigara 2012）：票数门控 × 域外处置，分别报
#   "翻转 / 新增判定 / 丢失判定"——放松 AD 常常是"新增"而不是"翻转"
$PY -m adt.cli sensitize --in out/measurements.csv --ad --require-grid 1 2 3 --outdir out

# 校准（v3.0.0 / Van Calster 2019）：判别力 ≠ 概率可信
#   只对概率量纲端点启用；percentile/µL/min/mg 一律拒绝（不适用就明说）
$PY -m adt.cli benchmark --predictions out/measurements.csv --truth truth.csv \
    --scaffold-from out/compounds.csv --split --outdir out
#   ↑ 顺便算 Bemis-Murcko 骨架簇（TDC 标准切分）；骨架簇太少会显式报 degenerate
$PY -m adt.cli benchmark --predictions out/measurements.csv \
    --truth tdc_DILI.csv --truth-format tdc --tdc-endpoint DILI --outdir out

# 保形预测区间（v3.0.0 / Norinder 2014）：有限样本覆盖率保证 P(|y−ŷ|≤q)≥1−α
$PY -m adt.cli conformal --predictions out/measurements.csv --truth truth.csv \
    --alpha 0.2 --min-n 20 --outdir out

# 监管治理评估（v3.0.0）：OECD QAF 四原则 + Hanser 三层适用域 + PROBAST 偏倚风险
$PY -m adt.cli qaf --reliability out/reliability.csv --coverage out/coverage_matrix.csv \
    --measurements out/measurements.csv --compounds out/compounds.csv --outdir out
#   ↑ 输出 qaf_compliance.csv / ad_levels.csv / probast.csv；tier 会读偏倚风险

# 报告规范与可复现（v3.0.0）：TRIPOD+AI 自查 + 每源 model card + FAIR 映射
$PY -m adt.cli reporting --reliability out/reliability.csv --measurements out/measurements.csv \
    --benchmark out/benchmark.csv --version 3.0.0 --outdir out

# 报告生成（措辞已按 §12 封顶，写作时不得越过模板；有 sensitivity.csv 会自动加稳健性段）
$PY -m adt.cli report --reliability out/reliability.csv --axis out/axis_scores.csv --outdir out

# ================= v3.1.0 学术化升级（工作包 A/C/D/E/H/I/J；详见 references/09） ==========

# A 独立性量化 + 校准计票：把"两票半"从断言变成可检验的假设
#   pairwise Spearman / Fleiss κ；组内 ρ>=0.90 降为半票；负相关标 sign_conflict
#   有 truth.csv 时拟合"k 票阳性 -> 错误率 u(k)"（Jeffreys 平滑；Clark 2014 仅为启发来源）
$PY -m adt.cli independence --in out/measurements.csv --registry references/02_source_registry.yaml \
    --truth truth.csv --outdir out
#   产物：independence_pairs.csv / independence_groups.csv / effective_votes.csv
#         / vote_calibration.csv / vote_monotonicity.csv
#   ⚠ 只度量，不改 verdict；effective_votes 暴露"整数两票、有效不足一票半"的伪共识

# I GRADE 式确定性修饰符：把 UNDETERMINED 分成 可解决/不可解决/需实验
$PY -m adt.cli certainty --reliability out/reliability.csv --measurements out/measurements.csv --outdir out
#   产物 certainty.csv；reliab 输出已自动带 certainty_modifier 列

# H 选择性预测 risk–coverage：结构性弃权 vs 分数型弃权
#   无 truth 时可用 --proxy holdout（留一源，非循环）或 majority（循环，仅示意）
$PY -m adt.cli selective --measurements out/measurements.csv \
    --proxy holdout --holdout-source admetlab3 --outdir out
$PY -m adt.cli selective --reliability out/reliability.csv --truth truth.csv --outdir out
#   可加 --conformal out/conformal.csv（取 width 列）作为第三条分数型基线
#   产物 risk_coverage.csv / selective_summary.csv（AURC、risk@80/90、status）

# J 失效模式检测：把 C50/C74/C78/C80/C82/U6/C16 变成可自动检测的不变量
$PY -m adt.cli failure-modes --in out/measurements.csv --reliability out/reliability.csv \
    --chemical-class cinnamoyl_glycoside --outdir out
#   有标签时（mode,compound_id,endpoint,is_failure）算 precision/recall
$PY -m adt.cli failure-modes ... --labels labels.csv --outdir out

# C 结构扰动：去盐/中和/互变/立体翻转，量化"标准化改变了什么"
#   默认用 input_smiles（原始输入）；--use-calc 才用已标准化的 calc_smiles
$PY -m adt.cli perturb --compounds out/compounds.csv --outdir out
$PY -m adt.cli perturb --compounds out/compounds.csv \
    --predictions variant_predictions.csv --outdir out   # 长表：cid,variant,endpoint,source,value

# D 决策价值：实验预算三策略（vote_all / admission / random）+ Vickers 决策曲线
#   无 truth 时可 --proxy majority（伪标签，只能写"期望效用"不能写"准确率"）
$PY -m adt.cli decision-value --reliability out/reliability.csv \
    --measurements out/measurements.csv --proxy majority --budget 10 --outdir out

# E DST 对照：all-in（域外=ignorance）vs 证据准入；并统计"DST 判死但框架弃权"
$PY -m adt.cli dst --in out/measurements.csv --chemical-class cinnamoyl_glycoside \
    --reliability out/reliability.csv --outdir out

# ---- v3.4.0 深水区增量 ----
# 糖苷水解-苷元暴露轴：O-糖苷键型 + 位阻位置 + 酯/乙酰化 -> 水解与首过风险
$PY -m adt.cli glycoside-hyd --in out/compounds.csv --outdir out
# 类条件（Mondrian）保形：修边际保形在少数类上的系统性低覆盖
$PY -m adt.cli conformal-class --predictions out/measurements.csv --truth truth.csv \
    --endpoint vnn_bbb --alpha 0.1 --outdir out
# 跨化学类裁决行为一致性：检验"弃权率随可裁决性单调变化"
$PY -m adt.cli cross-class --reliability rel_glycoside.csv rel_openadmet.csv \
    --labels glycosides,openadmet --expected-high glycosides --expected-low openadmet --outdir out

# ---- v3.5.0 三次评审增量 ----
# 方向A 准入层消融：无准入 / 仅单位守卫 / 完整准入 / 准入+保形（同 coverage 比较）
#   注意：源请用**原始预测**（measurements_baseline_*.csv）+ --rules；
#   不要用 *_risk.csv（其 value 是方向对齐后的原始量纲，不是 0–1 分数）
$PY -m adt.cli ablate --sources "m_rdkit.csv=rdkit:desc_ml,m_morgan.csv=morgan:fp_ml" \
    --truth truth.csv --rules references/03_endpoint_rules.yaml --outdir out
$PY -m adt.cli ablate ... --corrupt domain --outdir out    # 受控失效注入
# 方向B Regaloside A vs B（真实结构，9× 口服暴露差异的区分能力 case study）
$PY -m adt.cli regaloside-ab --outdir out
# 模块M 结构性弃权 vs 模型依赖弃权（跨端点 AURC 一致性，可给负结果）
$PY -m adt.cli abstain-cmp --reliability out/reliability.csv --truth truth.csv --outdir out
# 模块N UNDETERMINED 结构化归因（domain_block/phys_range/unit/spread/...）
$PY -m adt.cli abstain-why --reliability out/reliability.csv --outdir out
# 模块O 失效模式三层检测（契约级/裁决级/架构级）+ 特异性约束说明
$PY -m adt.cli fail-layers --in out/measurements.csv --rules references/03_endpoint_rules.yaml \
    --expect-sources admetlab3 admet_ai --curated --outdir out
# 模块L 跨数据集可迁移性（弃权行为是否随数据质量按预期方向移动）
$PY -m adt.cli transfer --datasets "a.csv=dsA,b.csv=dsB" --expected-order dsA,dsB --proxy --outdir out
#   v4.13 接线：给 --truth（compound_id,endpoint,truth_class）才计算 decided_accuracy；
#   不给时输出 decided_acc=not_evaluated（此前该函数无任何 CLI 入口 = 死代码）
$PY -m adt.cli transfer --datasets "a.csv=dsA,b.csv=dsB" --truth truth.csv --proxy --outdir out

# ---- v4.13 F1 源注册门（CI 化）真实执行入口 ----
# 候选源准入判定：Clopper-Pearson 95% CI 上界 ≤ tol（默认 5%）才算"有统计把握地不过线"
# 输入 CSV 必需列：source,n,observed_failures；不通过 ≠ 源不可用，输出带 CI 标注 + disclosure_required
$PY -m adt.cli source-admit --results src_validation.csv --outdir out
# 可选 --design-p <真失败率>：输出各 n 下注册门通过概率（论证"CI 化后需 n≳60"）
$PY -m adt.cli source-admit --results src_validation.csv --design-p 0.03 --outdir out

# ---- v3.6.0 未闭环项处理 ----
# G 时间留出（temporal holdout）裁决：早期数据训练的模型裁决晚期分子，报 PASS 组实测失败率（非预注册前瞻，C08）
#   OpenADMET-ExpansionRx 的 train/test 就是官方**时序切分**（train ID 1321-20100 / test 20101-27239，零重叠）
$PY -m adt.cli prospect --measurements late_ms.csv --truth late_truth.csv \
    --rules references/03_endpoint_rules.yaml --baseline both --outdir out
# A 真实源间相关性 ρ（同一批分子的两个真实源宽表，按 SMILES 对齐）
$PY -m adt.cli source-rho --source-a admetlab3_raw.csv --source-b admet_ai_raw.csv \
    --label-a ADMETlab3 --label-b ADMET-AI --outdir out
# A/C 结构变体提交清单（original/去立体/互变体 + 控制分子 + 分批）
$PY -m adt.cli ac-plan --compounds out/compounds.csv --controls --batch-size 5 --outdir out
# C 预测值位移 vs 源间分歧（拿回真实源变体预测后跑；ratio>1 ⇒ Gate 0 必要）
$PY -m adt.cli pred-shift --variants variant_preds.csv \
    --source-shift out/source_rho_by_endpoint.csv --outdir out

# ================= v4.14–v4.20 扩展（截图工具收编 + PK/PD；裁决书 references/EXTENSION_ANALYSIS_v4.14.md）=====

# v4.14 电离状态 / pKa（Gate 0.5 的补证；**区间估计，不是实测 pKa**）
$PY -m adt.cli pka --in out/compounds.csv --ph 7.4 --outdir out
#   产物 ionization.csv：charge_class / net_charge(±区间) / logd_7_4(±区间) / bracket_straddles_ph
#   ⚠ 禁把 pka_centres 当"这个分子的 pKa"引用；需要数值走 readback --source graphpka

# v4.15 心脏离子通道三联（hERG + Cav1.2 + Nav1.5）
#   输入是长表里的 cardiac_* 端点（膜片钳实测或 readback 回填；**没有计算源提供**）
$PY -m adt.cli cardiac --in out/measurements.csv --exposure out/cmax_uM.csv --outdir out
#   产物 cardiac_panel.csv：n_channels / missing_channels / worst_tier / panel_verdict / allowed_statement
#   ⚠ 只有 hERG 时 verdict=herg_only_*，**不能**据此排除多通道风险；不做 ORd 净效应

# v4.16 PK/PD 连接：先用 --dump-curves 拿 C(t)，再算 PD 指标
$PY -m adt.cli pbpk --in out/measurements.csv --compounds out/compounds.csv \
    --dose-mg 100 --dump-curves --outdir out          # -> pbpk_curves.csv
$PY -m adt.cli pd --curves out/pbpk_curves.csv --compounds out/compounds.csv \
    --ec50 0.5 --emax 100 --hill-n 1.2 --dosing-interval 12 --outdir out
#   --ke0 0.8 走效应室；--tmdd-params "R0,kon,koff,kint,kdeg" 才跑 TMDD（缺项直接报错）
$PY -m adt.cli pd --curves out/pbpk_curves.csv --compounds out/compounds.csv \
    --ec50 0.5 --emax 100 --ke0 0.8 --tmdd-params "10,0.05,0.5,0.1,0.05" --outdir out

# v4.17 PBPK 资格认定（**没有这一步，PBPK 只是"会算"**）
$PY -m adt.cli pbpk-qualify --pred obs_pred.csv --intended-use screening_level_exposure --outdir out
#   判定：insufficient_n / insufficient_timepoints / qualified_conventional / not_qualified
#   阈值是 convention（EMA 2018 未规定通过线），引用时必须写明

# v4.18 外部 PK/PD 工具互操作（PK-Sim / nlmixr2 / Pharmpy）
$PY -m adt.cli interop --what all --compounds out/compounds.csv \
    --curves out/pbpk_curves.csv --dose-mg 100 --outdir out
#   口服布局默认 --dose-cmt 1 --obs-cmt 2（同腔会让 NONMEM ADVAN2 把观测读成胃肠道）
#   非正观测（ODE 数值零）自动置 MDV=1 并报条数；BLQ 删失似然本模块不做
#   产物 pk_sim_compounds.csv / nonmem_dataset.csv / nlmixr2_skeleton.R
#   + --snapshot 追加 pk_sim_snapshot.json（OSP 快照，Version 80，PK-Sim `snap -p` 可直接吃）
#   ⚠ v4.21 实测分级（不再是布尔 False 一刀切）：
#     pk_sim  = pk_sim_cli_snap_passed   PK-Sim 12.3.173 真机 snap -p 往返，32/32 化合物逐位一致
#     pharmpy = pharmpy_dataset_ok       Pharmpy 2.3 真读 11228 行 / 28 受试者（ID 必须整数）
#     nlmixr2 = nlmixr2_fit_passed       COMPILE_OK + FOCEI 收敛；但只有 V 可辨识
#   → 直接 `Rscript out_case/interop/nlmixr2_skeleton.R` 即可复现（骨架内是绝对路径）

# v4.19 肠道菌群代谢（HGUT；**biosystem 过滤 + 反应标注一致性 QC** 强制）
$PY -m adt.cli gut-micro --in out/compounds.csv --option HGUT --dump-raw --outdir out
#   产物 metabolites_gut.csv（含 label_check/label_delta_mass）+ bt_raw_<cid>.json
#   ⚠ reaction_type/enzymes 是"规则名"，只可引用 smiles/inchikey

# v4.20 没有 API 的工具：人工导出 → 回填（SwissADME / AOMP / Graph-pKa / MicrobeTCM / GutBugDB ...）
$PY -m adt.cli readback --source swissadme --file swissadme_export.csv \
    --compounds out/compounds.csv --outdir out
#   列名与 schema 不符时显式覆盖（**不做模糊匹配**）：
$PY -m adt.cli readback --source aoamp --file aoamp.csv --compounds out/compounds.csv \
    --map "hERG=herg:probability" "pIC50=pka:log" --outdir out
#   measured 必须带 --provenance-url（工具主页不算引文，否则自动降级 manual）
```

### v3.2.0 外部公开数据（随包分发；工作包 B/G）

两个公开数据集已随包放在 `assets/external/`（许可证/来源见各目录 README）：

- `openadmet/` **OpenADMET-ExpansionRx**（CC-BY-4.0）：train 5,326 / test 2,282 分子，
  9 个 ADMET 终点；真实项目数据，适合做"前瞻性"基准。
- `npass/` **NPASS 3.0 curated**（学术免费）：1,307 个大鼠 LD50 化合物 + 76 条 ADME；
  天然产物化学空间，适合做毒性/适用域基准。

```bash
# 1) 外部数据 -> 三张契约表（compounds/measurements/truth + rules）
$PY -m adt.cli external --dataset openadmet --data-dir assets/external/openadmet \
    --split test --outdir out_ext
$PY -m adt.cli external --dataset npass --data-dir assets/external/npass --outdir out_npass

# 2) 基线预测（Ridge on RDKit 描述符 / Morgan 指纹）
#    ⚠ source=baseline_rdkit / baseline_morgan，是**基线**不是外部工具
$PY -m adt.cli baseline --train-meas out_ext/measurements_train.csv \
    --test-meas out_ext/measurements_test.csv \
    --train-compounds out_ext/compounds_train.csv \
    --test-compounds out_ext/compounds_test.csv \
    --method both --rules out_ext/external_rules.yaml --outdir out_ext

# 3) 真实 AUROC/AUPRC（必须用 *_risk.csv：方向已按 shape 对齐）
#    直接拿原始预测值跑 benchmark 会让"越高越好"的端点 AUROC 系统性 <0.5
$PY -m adt.cli benchmark --predictions out_ext/measurements_baseline_rdkit_risk.csv \
    --truth out_ext/truth_test.csv --rules out_ext/external_rules.yaml \
    --outdir out_ext/bench_rdkit
```

> 诚实边界：`baseline_*` 是**本项目训练的 Ridge**，不是 ADMET-AI/ADMETlab 等外部工具；
> PASS/FAIL 阈值（如 LD50 300 mg/kg、KSOL 10 µM）是**分析选择**，不是监管阈值。
> 评审材料里提到的"NPASS 3.0 三工具基准（201,905 化合物）"不在官方 NPASS 下载包里，
> 本 skill 分发的是**官方 NPASS 实测 ADME/Tox curated 子集**；三工具预测可用 `web`
> 适配器自行重建。

### 工作包 F：conformal 区间宽度能否独立验证弃权（v3.2.1）

评审要求：对每个（源或共识值）用 split-conformal 生成区间，检查**框架标记为
UNDETERMINED 的化合物×端点，其区间宽度是否系统性大于 PASS/FAIL**。本 skill 分三步：

```bash
# F-1 难度尺度：训练集描述符空间第 k 近邻距离 -> sigma（离训练集越远越宽）
#     ⚠ 不用源间分歧，与弃权逻辑相对独立
$PY -m adt.cli conformal-scale --train-compounds out_ext/compounds_train.csv \
    --target-compounds out_ext/compounds_test.csv --k 5 --outdir out_ext

# F-2 归一化 conformal 区间：width = 2·q·sigma(x)，宽度随化合物变化
#     absolute 模式所有化合物同宽（无法检验 F）；必须用 normalized
$PY -m adt.cli conformal --predictions out_ext/measurements_merged.csv \
    --truth out_ext/truth_cal.csv --alpha 0.2 --mode normalized \
    --scale-file out_ext/conformal_scale.csv --outdir out_ext

# F-3 一致性核验：UNDETERMINED vs PASS/FAIL 宽度分布 + AUC(宽度预测弃权)
#     跳过 self_calibrated / insufficient / 空 width（否则自我校准窄区间拉偏）
$PY -m adt.cli conformal-check --conformal out_ext/conformal_intervals.csv \
    --reliability out_ext/reliability.csv --outdir out_ext
#   结论三档：支持(AUC≥0.65 且 中位比≥1.2) / 反向(AUC≤0.35) / 证据弱
```

> 诚实边界（OpenADMET 实测，v3.2.1）：UNDETERMINED 中位宽度 48.6，是 PASS
> (16.1) 的 2.2 倍、但窄于 FAIL (128.6)，AUC=0.635 → **"证据弱：区间宽度不能替代
> 弃权逻辑"**。即 conformal 宽度只是**弱互证**，不是独立证明；这正是不把 F 当成
> "新伪精度"的纪律体现。

### 工作包 K：可靠性方法生态位分工表（v3.2.1）

写作/定位交付：把"本框架 vs 多数投票/AD/DST/校准/conformal"的分工渲染成
机器可读 + Markdown，保证论文的表与 skill 立场一致（避免手改漂移）。

```bash
$PY -m adt.cli landscape --config references/reliability_landscape.yaml --outdir out
#   产物 reliability_landscape.csv / .md；thesis 见 yaml 顶部
```

## 判据速查（写死的，不要靠感觉）

| 判据 | 阈值 | 出处 |
|---|---|---|
| 端点在本集合内无区分度 | ≥90% 同向，或概率极差 <0.05 | 本 skill 的饱和扫描 |
| 端点数值不可用 | 越物理边界（log Papp < −8、logS < −12、logP > 10） | DeepPurpose caco2_mpnn 探到 −13.4 |
| 源在本化学类不可用 | 覆盖率 <0.30，或 ≥10 个分子上取 ≤2 个不同值 | vNN 0.17 vs 官方 0.73；caco2_cnn 恒 −5.808 |
| 可排名 | 候选 ≥30、最大同类簇 <30%、源间分歧 <阈值，三者同时满足 | MPO ρ=0.024 的实测反例 |
| 换结构后可否复用 | 仅纯描述符（MW/TPSA/HBD/HBA/cLogP）可复用 | 位置异构体：E1 一列未变，ADMETlab 95/120 在动 |
| 安全裕度 | **分档**：<10 红旗 / ≥30 常规安全 / ≥100 宽松安全（轻度适应症、CNS、超量风险）；10 倍**仅**适用于危及生命适应症；fu 单源时只给档位 | Redfern 2003 暂行边际；本项目 PPB 换结构动 7 个点 |
| 适用域（邻居） | **用 Tanimoto ≥40 判**；≥70 档经常为 0 会误判"完全无参考" | 真 M：T40 有 537 个邻居、最近邻 0.676，T70 为 0 |
| **适用域门是否可信** | gate 作为"模型是否会做对"的分类器 **AUC ≥0.65** 才可称"域外诚实"，且**必须逐端点测**；不足时 PASSTHRU 只能表述为"未加权弃权"，**禁止**称谨慎 | 实测（`GATE_AND_P8_MMP_v4.2.md` §1.5，**三端点均已补 95%CI，P2.4-b**）：BBB **0.514 [0.440, 0.595]** → 区间上界也低于 0.65，**已证明无判别力**；hERG **0.580 [0.456, 0.701]** → 区间跨 0.65，**不可判**（只能说"未证明有判别力"，**不得**说"已证明没有"）；DILI **0.668 [0.543, 0.793]** → AUC 同样不可判，但域内外准确率差 **−0.193 [−0.321, −0.030]（不含 0）** → "域外更差"这条**成立**，"PASSTHRU 在 DILI 上有据"可以写，"门有判别力"不可以写。**两条判据分开写，一条成立≠另一条成立；也不能全局宣称"域外诚实"** |
| **结构扰动合格线** | 模型翻转率与 **MMP 真实标签翻转率 TOST 等效**（±0.10）；"位移小"不是合格，是可能迟钝；`n_pairs < min_pairs_for_power(p)` 时判 `INSUFFICIENT_POWER`，不许下结论 | hERG 127 对（需 63）：标签 13.4% vs 模型 0.0%；BBB 479 对（需 74）：16.3% vs 4.8% → 均 `insensitive`；**DILI 31 对（需 61）→ `insufficient_power` 不判** |
| **回归端点的结构扰动** | 分类端点的"翻转率"对连续标签无意义，改用**位移幅度比 R = median\|Δpred\|/median\|Δlabel\|** 的 TOST（0.5–1.5）。**R<1 对"回归到均值"的模型是数学必然**，故必须与 `sign_agreement` 合读：符号一致率显著>0.5（二项符号检验 `sign_z≥3.0`，约定值）且 R 判迟钝时，判 **`compressed`（幅度保守、方向可靠）**，**禁止**写成"对结构变化不敏感" | Caco2（220 对）：R 0.417/0.234/0.170（rf_morgan/rf_maccs/ridge_desc），ensemble **0.286** [0.204,0.331] → `insensitive`，符号一致率 0.53–0.58（近随机）= 真迟钝；脂溶性（4636 对）：R 0.32–0.41 但符号一致率 **0.67–0.73** → **`compressed`**，不是迟钝；溶解度（5684 对）：2 模型 `equivalent`、2 `inconclusive`，**无一迟钝** |
| **准入层是否优于"无准入层"** | 必须同时与**校准基线**和**未校准基线**各比一次；只比校准基线时，"没增益"可能是基线过强而非准入层无用 | S4 完整准入 vs S5 未校准置信度：hERG **−0.133**、DILI **−0.115**、BBB **−0.219**（均 SIG 更差）→ **基线过强这一解释被否证**；真正代价来自 AND 串联（cov 0.55→0.18） |
| **多判据 AD 是否救得活 gate** | 至少并列测 4 种判据（kNN-Tanimoto / conformal p / 描述符距离 / 一致性），并以 AUC≥0.65 为"有判别力" | 三端点 × 4 判据全部 **<0.65**（最高 DILI kNN **0.648**）；conformal p 与 kNN **AUC 几乎相同**（同一非一致性度量的单调变换），不构成独立证据 |
| **门的价值怎么测**（**2026-11-04 C01 已撤回，待重估**） | ~~只能在域外强制预测上测；允许的最强表述是"域外处处不可用，门全拒是保守的正确"~~。**旧判据失效**：其唯一量化支点是 `auc < always_positive_accuracy` 的跨量纲比较（AUC 基线 0.5；always-positive accuracy = prevalence）。当前允许的表述只有：`external_cuts_summary_v2.json` 的**双轨数值**（AUC+95%CI vs 0.5；acc@0.5 vs prevalence + 配对 bootstrap CI）+ `inference_revoked_pending_estimand` + 撤回说明。**禁止**：「域外处处不可用」「保守的正确」「边界方向正确」「门外可用」，**也禁止翻转成「域外仍有弱排序能力」**（外审 B：hERG 端点 estimand 未绑定实验金标准，AUC 不承载决策含义） | v2 实跑：AUC 0.581 [0.569,0.593] / 0.584 [0.560,0.610] / 0.598 [0.562,0.635]，CI 下界全 >0.5；acc−prevalence −0.005 / **+0.002** / −0.008，配对 CI [−0.0084,−0.0005] / [−0.0062,+0.0108] / [−0.0209,+0.0063]；`accuracy_below_majority_class` = True/**False**/True，三切点为嵌套子集（伪重复）。桶级单调只在时间混合集成立（`trend_not_robust` 保留）。见 `references/RETRACTION_NOTE.md` |
| **准入层何时值得用**（v4.4） | 只在**弃权代价 ≤ c\*** 时；超出即转劣。报结论必须同时给 c\* 与规格分布，不得写"准入层普遍优于/劣于" | 无差异曲线（`keystone_indifference.json`）：c*(abstain) hERG **0.26** / BBB **0.2091** / DILI 未识别；216 规格方向翻转率 **0.398**（`keystone_spec_multiverse.json`） |
| **源独立性的瓶颈在哪**（v4.4） | 不是"共享训练数据"，而是**方法同源**（同算法/同特征）。"换个数据集重训同类模型"**不构成**第二个独立源 | 受控梯度 20 种子（`independence_gradient.json`）：α 0→1 时误差相关 **0.655→0.978**、一致率 0.939→0.977（伪共识签名），但两源均值增益在**所有 α 上 ≤0** |
| **阈值能否事后改**（v4.4） | 影响结论的阈值必须登记**来历 + 冻结状态 + 敏感性证据**；登记值与代码字面量漂移即 BLOCK | 11 条阈值：literature 1 / calibrated 3 / ad_hoc 7；`ad_anchor 0.35` **有意不冻结**（分层显示 0.35 附近无断点，它只是工作点） |
| **✅ 能不能不附产物**（v4.4） | 不能。实验类必须附**数据产物**，且所引数字必须以**字面量**出现在该文件里（四舍五入需注明） | `CLAIMS_REGISTRY.yaml` 17 条逐条核验；空心 ✅（`out_gate/` 从未生成那类）从此被门禁 G10 拦 |
| 跨源分歧 | 概率类极差 >0.30 即判分歧，**不取平均**；一致时取中位数 | hERG 三源 0.014/0.409/0，极差 0.37 |
| NMR 判连接性 | 证据分级：HMBC 双向 > 乙酰 δH 类型 > 糖苷化 13C > 拓扑类比 > 单项归类；**无 HMBC 的数据页只能标"推定"** | 两条独立工作线对 M 得出相反结论的复盘 |
| 对接资质 | **红ocking Gate**：共晶配体回原口袋 best RMSD ≤ 2 Å 才能开跑（看前几名的最小 RMSD，不看 top-1）；共晶配体成键对 PDB CCD 核对 | 外部会话实测 BW245C mode4 = 1.09 Å |
| 输入氢原子 | QC/构象搜索前必查 H 计数；警报信号：gap < 1 eV、日志 `atoms = heavy`、molden 氢数 0 | 外部会话 13/14 化合物无氢重跑 |
| 外来数据包审计 | LE 反推：`HA = |ΔG| / LE`，与图上分子重原子数对不上 = 图错数据对 | 抓到 J 被画错而数据正确 |
| 两轴合并 | 合并任意两轴证据前先算轴间相关；相关但因果互反时（如结合-暴露 ρ=−0.76）合并必须声明 | 外部会话 PBPK 互证 |
| 源独立性 | **同 independence_group 只记 1 独立票**（admetlab3/admet_ai 同属 descriptor_ml；protox3/vnn 同属 neighbor_qsar）；require_sources=N 的语义 = N 个独立组 | registry 18 源已全部分组 |
| 源注册门（F1，CI 化） | 源注册/准入的失败率门改为 **Clopper-Pearson 95% CI 上界 ≤5%**（`adt/stats_ci.registration_gate`），输出须带 `n/observed_rate/ci_upper`；**不得**用点估计≤5% 当通过。小源因 n 不足 CI 宽，**带 CI 标注进入**而非二值拒绝（构成偏差：注册表向大源系统性倾斜，每份材料须声明） | 真实计算：真失败率 3% 时 n=100 通过概率仅 4.8%、n=500 才 56.8%（见 `STATISTICAL_POLICY.md` §1.1） |
| 措辞封顶 | 每条结论只允许 phrasing.allowed_statement 模板内的表述；UNDETERMINED 禁方向词；禁止 ΔG→Kd、预测值→人体剂量、"证明/无毒" | 05_qa_gates §12 |
| 输入合法性 | normalize 自动执行价键/奇电子/radical 硬门（hard_gate_problems 列非空即禁分发）+ 状态敏感性标记（state_sensitive 列） | [CH3] 双警报实测拦截 |
| 跨批可比 | 网页源批量提交必须混入对照分子，出 expected 区间即标 batch_drift，跨批比较降级 | **v2.2：每批开跑前强制跑对照**（pre_batch 钩子，bt 实测 6/2 无漂移） |
| 源版本混用 | 本地 admet-ai 与网页服务**不是同一套权重**：分类端点一致、回归端点系统性偏移（Caco2 +0.53 log、PPBR −3.5%）。本地 `source_version=2.0.1-local`，一分析只用一来源 | C74；14/14 同向偏移 |
| 湿实验替代 | Caco-2 / 微粒体 CLint / PPB 三项**不依赖 ADMETlab 网页端**：ADMET-AI 同列可取（`Caco2_Wang`/`Clearance_Microsome_AZ`/`PPBR_AZ`），且 ADMETlab 与 ADMET-AI 同属 descriptor_ml → 只算 1 票。**v2.3.5 起单组不下判决**（`require_sources=2`），只出"单组证据"数值 | C70：曾只接了 1/3；C71：log 值与线性阈值混用会恒判 FAIL；C77：默认要求曾是 1 |
| hERG IC50 | 三个计算源（ADMETlab/ADMET-AI/vNN）**都只给概率或类别，没有一家给浓度**。IC50 只能用类似物实测锚点：`assets/herg_reference_ic50.csv` + `pbpk.evidence_ic50_anchor()` → **11.2 µM（2.51–53）**，全集 10 个中位 29.9 µM。**只报档位，不报精确 Margin**（同分子跨平台差 20 倍） | C83（Potency≠IC50、空值记录）/ C84 |
| 转运体 | 三个计算源**都不给肠侧转运体**（ADMETlab 只有肝/胆侧 5 个，ADMET-AI 只有 Pgp 抑制剂，vNN 本类全 NoPrediction）→ `transport` 只输出**先验 + 实验处方**，`predictive_value=none`，**不得进 reliab 计票** | C87：邻苯二酚 SMARTS 松模式会把愈创木基误判进来；C88：汇总须按分子去重 |
| 肠肝循环 | `pbpk --ehr-scan` 给**边界不给点值**：fbile≤0.6/fre≤0.8 时 AUC 最多 ×1.87、t½ ×2.43、**Cmax 仅 ×1.13** → 用 Cmax 的结论（暴露、hERG 裕度）对 EHR 缺口稳健，t½/给药间隔不稳健 | C86：加机制前必须写不变量（fre=0 ≡ 无 EHR） |
| 糖苷 hERG | 糖苷不必然是阻断剂：人参皂苷 Rg3 是**激动剂**；taxifolin 糖苷最大抑制仅 36.9% 即平台、CAPE 在 AP clamp 下反使 I_hERG 增大 → 尾电流 IC50 算的 Margin **高估**扭转风险 | C85；报 Margin 须注明"假定 Hill=1、满抑制" |
| 单位异构 | 同一端点若既有**类别 0/1**又有**概率**，**禁止取中位数**；必须用规则里的 `class_map` 投射成 PASS/FAIL 再比方向，方向不一致即 UNDETERMINED | C78：曾把"类别 0"当"概率 0"算出 6 个假 PASS |
| 严格口径 | 默认要求 **2 个独立方法组**（两票半）。单组端点一律 UNDETERMINED，值进报告"单组证据"段 | C77；v2.3.5 实测：全项目只有 MMP 可判 |
| 单位真源 | 端点单位只从 `03_endpoint_rules.yaml` 读（`endpoints.unit_for()`）；非概率端点必须在适配器 `TRANSFORMS` 里显式换算（如 % bound → fu = 100 − x） | C72：硬编码 probability 把 µL/min/mg 标成概率 |
| 端点升级 | 升级为 quality 需**同时**满足：① 文献锚定阈值；② **有值且语义一致**的第 2 独立组（"存在另一列"不算） | C69；Pgp 抑制剂≠底物、vNN CYP 名义上有第二组但全 NoPrediction |
| 阈值稳健性 | 阈值 ±20%/±50% 摄动后翻转率 >0.20 → `fragile`；>0.50 → `threshold_critical`（结论只能写"待实测确认"） | E3；试点实测 hERG 0.33 |
| 输入格式 | 默认嗅探；首行含逗号的 TSV 必须 `--format tsv` | C50/C61 |
| 背景异常度 | 相对**同化学型背景**的稳健 Z（median+1.4826MAD，floor 0.30）；\|z\|≥2 判离群；n<5 不计算、n<50 标 SMALL_N；**\|z−z_sd\|>1.5 判尺度冲突，不得静默取一个值** | E6a；用随机小分子做背景会虚构选择 |
| 结论档位 | **T1 探索（不得进论文表）/ T2 决策（无实测可，但需 ≥1 端点 2 独立组）/ T3 发表（需实测+独立基准+覆盖声明）**；越级由 `tier` 强制拒绝 | E0/门控状态机；与行级 `phrasing` 叠加 |
| 源独立性 | 组内 **正相关** ρ≥0.90 降为半票；0.70–0.90 线性降权；**负相关不是冗余，标 sign_conflict（方向/语义冲突）**；无配对数据不降权但显式标注；**v4.1 实测：收缩权重的 log-loss 与等权差异 ≤0.001 且方向不一致（DILI/BBB 上显著更差），因此权重只能作为可解释的审计量，不得作为有效性贡献**（见 `references/BLACKLIST_CLOSEOUT.md` §3） | 工作包 A；OneADMET"多平台≠多来源"；A1 实测 |
| 校准计票 | `u(k)=(err_k+0.5)/(n_k+1)`（**Jeffreys/Laplace 伪计数平滑**）；`vote_confidence=1-u`；某 k 的 n<5 标 insufficient；u(k) 不单调 = 校准失败，不得据此设门控 | Jeffreys 1946；Agresti & Coull 1998；Clark 2014 仅为**启发来源**（C4 更正） |
| 确定性修饰 | UNDETERMINED 必须细分：`low_resolvable`（补源/统一单位/补版本）/ `low_unresolvable`（域外，只能湿实验）/ `medium_needs_experiment`（有信号未过门槛） | 工作包 I；GRADE Guidelines 30 |
| 选择性弃权 | 报告 **AURC、risk@80、risk@90**；结构性弃权与分数型（spread/conformal 宽度/vote_confidence）并列比较；无 truth 只能用 holdout/majority，且标 label_source | 工作包 H；Honest ADMET 2026 |
| 结构噪声 | 去盐/中和/互变/立体翻转的位移与源间分歧比 **ratio≥0.5 即"源间分歧含结构伪影"**；2D 描述符对立体不敏感（E1 级可复用），指纹/图模型必重跑 | 工作包 C；C4/C5 |
| 决策价值 | 固定预算下比较 vote_all / admission / random 的期望效用（TP − cost_fp·FP）；**只说"期望效用"，不说"准确率提高"**；UNDETERMINED 是信息缺口定位信号 | 工作包 D；Vickers 2006 |
| DST 分工 | 域外源赋 ignorance（θ=1）是 Dempster 单位元，与排除等价；真正过度裁决来自"已登记域外但仍投概率票"；统计 **DST 判死但框架弃权** 的条数 | 工作包 E；TOXTRUST/Belief 函数 |
| 失效模式 | 7 类不变量：unit_isomerism / domain_block_unwired / version_drift / phys_range_violation / pseudo_consensus / single_group_verdict / silent_empty_source；有标签才算 precision/recall | 工作包 J；C50/C74/C78/C80/C82/U6 |
| 外部基准 | OpenADMET 9 终点（CC-BY-4.0）/ NPASS 1,307 LD50（学术免费）；`baseline_*` 是 Ridge **基线**不是外部工具；PASS/FAIL 阈值是分析选择；benchmark 必须用 `*_risk.csv`（方向已对齐），否则"越高越好"端点 AUROC <0.5 | 工作包 B/G；`assets/external/README.md` |
| conformal 验证弃权 | normalized conformal 宽度（2·q·sigma）作为**分数型基线**，独立检验 UNDETERMINED 是否更宽；结论三档（支持/反向/证据弱）；self_calibrated/insufficient/空 width 不参与比较 | 工作包 F；Norinder 2014；Honest ADMET 2026 |
| 可靠性生态位 | 论文 Discussion 主动划清"本框架 vs 多数投票/AD/DST/校准/conformal"的分工；机器渲染保证表与立场一致 | 工作包 K；`references/reliability_landscape.yaml` |
| **心脏毒性能不能下结论**（v4.15） | **只有 hERG 一律不能**：verdict 必须是 `herg_only_*`，措辞里禁"已排除"。要下结论需 3 通道齐备；即使齐备也只给"通道级最高风险 + 缺口"，**不给净效应**（无 ORd 即无净效应）。裕度分档 <10 HIGH / 10–30 INTER / ≥30 LOW（Redfern 2003 惯例，非法规线） | 实测：Terfenadine 三通道齐备 → `panel_high`（hERG margin 0.62）；Quercetin/Digoxin 仅 hERG → `herg_only_low` 且 allowed_statement 强制写"不能排除" |
| **PBPK 能不能用**（v4.17） | 先资格认定再用：`AAFE≤2 且 2倍内≥80%` → `qualified_conventional`；n<5 或**每化合物<2 时点**或单位不一致 → 拒绝。**只对 Cmax 的比对不算资格认定** | 实测两路径：5×1 时点 → `insufficient_timepoints`；5×8=40 配对 → `qualified_conventional`（AAFE 1.20、2倍内 98%）。阈值是 convention，EMA 2018 未规定通过线 |
| **PK/PD 指标怎么读**（v4.16） | `fT>EC50` 是"在给定 EC50 假设下暴露覆盖阈值的时间"，**不是疗效**；Hill 系数固定时 `fT>EC90` 由 `EC90=EC50·9^(1/n)` 反算，**不是独立信息**；TMDD **缺 R0/kon/koff/kint/kdeg 任一项必须报错**，不许默认值凑 | 实测：5 分子 × 12 h 间隔，fT>EC50 0–105 h，2/5 覆盖 ≥50% |
| **pKa 能不能引用**（v4.14） | **只能引用区间与分区**：`pka_grade=literature_category_range`（±1 log），类别级文献值，不建模取代基/糖苷化；**禁止**把 `pka_centres` 写成"本分子的 pKa"；`bracket_straddles_ph=True` 时必须用实测 pKa 复核 | 实测 14 分子：3 个显著电离；甘氨酸/阿莫西林正确判两性离子；咖啡因/葡萄糖正确判中性（嘌呤环 N 已知高估碱性 ~5 log，结论不变） |
| **菌群代谢产物能不能引用**（v4.19） | 只引 `metabolite_smiles/inchikey`；**`reaction_type/enzymes` 是规则名，会串底物类**，不得引用；**biosystem 必须过滤**（同一次 HGUT 查询会混入 `biosystem=Human`）；0 产物在阳性对照 >0 时记 `out_of_domain` | 实测：APAP→3（对照 PASS）、quercetin→7，但 **7/7 条反应标注与质量差矛盾**（葡糖醛酸苷 Δm=+176 被标"脱羧"；"羟化"却 Δm=−15.99） |
| **无 API 的工具怎么接**（v4.20） | 只走"人工导出 → `readback` 回填"：**结构对齐不符进 unmatched 报表**（不硬配名字）、**未映射列逐列报出**（不静默丢）、`measured` 必须带**显式引文**（工具主页不算）。不做列名模糊匹配 | 实测 SwissADME：3 行→12 长表行/2 分子；1 行结构不符被丢弃并报出；`index.php` POST **403** → 爬虫不可行 |

## 数据契约（三张表，禁止宽表）

- `compounds.csv`：`compound_id, input_smiles, calc_smiles, state_flag, formula, inchikey, mw`
- `measurements.csv`（长表）：`compound_id, endpoint, value, unit, source, source_version, retrieved_at, domain_flag, uncertainty, provenance_url, note`
- `metabolites.csv`：`compound_id, metabolite_smiles, metabolite_inchikey, name, reaction_type, enzymes, biosystem, source, provenance_url`

`domain_flag` 取值：`measured | predicted | out_of_domain | saturated | manual | error`。
**`out_of_domain` 必须不带数值**——带了就会被下游误算，schema 里有断言拦这个。

## 已知限制（要主动告诉用户）

- XenoSite 的程序化 API 是收费许可项（站点 Terms 明示），只能网页人工跑。
- BioTransformer 对肉桂酰糖苷类**无规则覆盖**：对乙酰氨基酚 6 个产物、苯酚 2 个、甲苯 3 个都正常，
  但咖啡酸 0 个、真 M 0 个、对香豆酸给出化学上荒谬的产物。0 必须记为 `out_of_domain`。
- ADMETlab 122 列里没有 CYP 诱导端点；转运体只有 OATP1B1/1B3/BCRP/BSEP/MRP1（无 MATE/OCT）。
- 覆盖率口径要说清：vNN 的 0.17 是 15 端点含 MRTD（36/210）；只算 14 个分类端点是 0.112。
- ChEMBL 相似性阈值只接受 40–100（30 会 400）；返回里没有分数，最大 Tanimoto 要本地算。
- admetSAR3 的作业要私有 access_key，未出现在 POST 响应里 → 暂列 `needs_probe`，不硬凑适配器。
- **vNN**：v2.2.1 起**全自动可用**（2026-10-28 端到端验证：登录 → ALTCHA → 提交 →
  轮询 89 s → 2 分子 8 行）。需要账号（`VNN_USER`/`VNN_PASS` 或
  `~/.workbuddy/vnn_cred.json`）；**单作业上限 10 个分子**，超过自动分批。
  站点只给 Yes/No 类别（不给概率），`NoPrediction` 一律记 `out_of_domain` 且不带数值。
  **15 个端点全部进入长表**：3 个质量端点（dili/herg/ames）+ 12 个参照端点
  （`vnn_cyp*`/`vnn_hlm`/`vnn_bbb`/`vnn_pgp_*`/`vnn_cytotoxicity`/`vnn_mmp`/`vnn_mrtd`，
  role=reference，进管线但不投票）。完整宽表另存 `vnn_wide.csv`、结果页存
  `vnn_checkjob_<hash>.html`（审计与跨批次对账用）。
  无凭据时退回人工桥（`--prepare-only` + `ingest`）。
- **ChEMBL 不能给本化学类补实验第二组**（C79 实测）：肉桂酰糖苷 14 分子的邻居活性记录
  180–340 条，但 ADMET 实测 **0 条**（全是 GI50/IC50）。跑 `chembl` 看
  `chembl_admet_assay_count` 与日志警告即可判断，不要再假设"参照分位能升为质量端点"。
- ChEMBL 参照端点（v2.2 起）：hERG 统一到 µM、ppb 统一为 fu 分数、半衰期与清除率分桶；
  无法安全归一的单位**直接丢弃**（不凑数）。
- ADMETlab 对新批次限流极严（连续 5 轮 429），适配器内置最长约 1 小时退避；
  新化学类首跑建议先 2 分子探窗口。
- **ADMET-AI 本地模式（`--local`）当前导入会挂起**（`pharma-tools/envs/admetai_local`
  的 `import admet_ai` >45 s 无返回）。全流程覆盖测试改用网页端
  （`https://admet.ai.greenstonebio.com/`，实测 200）。本地离线能力待修（v2.7.0 已知）。
- **`reliab --chemical-class` 默认空 = 不做域外端点过滤**（v2.7.0 起）：混合类面板安全；
  单一化学类批次（如糖苷）须显式 `--chemical-class cinnamoyl_glycoside`，否则类内
  blocked 端点不会生效。
- **v3.1.0 新增限制（必须主动告诉用户）**：
  - `independence` 的组权重是**校准选择**，报告必须同时给出 ρ 原值；负相关只标
    `sign_conflict`，不降权（它不是冗余）。无配对数据时权重 1.0 但 `no_rho_data`。
  - `selective` 无 `truth.csv` 时只能 `--proxy holdout/majority`；可配对 n<10 会标
    `insufficient`，AURC 只作代码自检，**不得写进论文结果**。
  - `decision-value` 的 proxy 结果只能写"给定预算下的期望效用"，**不得写"准确率提高"**。
  - `perturb` 的互变异构变体可能丢失立体（C4），note 会显式告警；`predictions` 模式
    需要使用者自行保证立体一致，或只用去盐/中和变体。
  - 工作包 B（NPASS 3.0）与 G（OpenADMET 盲测）**v3.2.0 起已随包分发**（`assets/external/`）；
    但 `baseline_*` 是本项目训练的 Ridge **基线**，不是 ADMET-AI/ADMETlab 等外部工具；
    PASS/FAIL 阈值是分析选择；评审材料里的"NPASS 三工具 201,905 化合物"基准不在官方
    NPASS 下载包中，本 skill 分发的是官方实测 ADME/Tox curated 子集。
- **v4.4 新增限制（三条，都是本轮实测逼出来的，必须主动告诉用户）**：
  - **外源结论仍只有单一来源**：`AUC 随距离单调上升` 只在 ChEMBL_37 hERG
    （文献年≥2023，n=9443）一个外源集上成立。第二外源集（不同端点或不同年份切点）
    未做 → 该结论只能算**单源证据**，不得写成普适规律。
  - **源独立性无法由"换数据集"获得**：受控梯度实测显示 α=0（训练集完全不共享）时
    两源误差相关仍有 **0.655**、两源均值增益 **0**。含义：本框架计票逻辑里
    "不同源 = 独立票"的默认假设**在方法同源时不成立**。使用计票前必须先问
    "这两个源是不是同一算法/同一特征族"。该项（次轮 A1）**仍未关闭**。
  - **近邻泄漏归因项回退为未关闭**：v4.3 曾写"部分关闭、方向不支持原担忧"；
    v4.4 复核发现两个候选机制（记忆驱动 / 一致率驱动）**都不成立**，
    BBB 的 Δ=−0.212 仍未解释，代理**不具备判定力**。不得引用它来支持任何归因结论。
    （`out_ext/tdc/leakage_confound_check.json`）
- **v4.14–v4.21 新增限制与已修契约（十四条，都是实测逼出来的）**：
  - **心脏通道端点没有任何计算源**：`cardiac_*` 六个端点只能来自膜片钳实测或
    `readback` 回填。`cardiac` 命令在没有这些值时会直接告诉你"没识别到端点"，
    而不是给一个 hERG 概率假装能算。**hERG 单通道永远不能下"安全"结论**。
  - **PBPK 资格认定未做 bootstrap CI**：AFE/AAFE/2倍内都是点估计，n<10 时应视为不稳定；
    观测自身误差（LC-MS/MS 常 ±15%）已占去 2 倍判据的大半 → 2 倍内比例高**不等于**机理正确。
  - **外部工具只闭环到"化合物层"**（v4.21 更新，此前写"全部未安装"已不成立）：
    PK-Sim 12.3.173 / MoBi 12.3.136 / Pharmpy 2.3.0 / R 4.5.3+nlmixr2 5.0.0 **均已装上并实测可运行**。
    但闭环程度不同，`validated_against_tool` 因此**三分级**：
    `pk_sim_cli_snap_passed`（OSP 快照 `snap -p` 往返，32/32 化合物逐位一致——
    **仅化合物层**，仿真层未闭环，见下条）/ `pharmpy_dataset_ok`（真读 11228 行、
    ID 1..28、EVID{0:11200,1:28}）/ `nlmixr2_fit_passed`（COMPILE_OK + FOCEI
    正常退出；**但只有 V 可辨识**，见下条）。
  - **nlmixr2 只估得出 V**（v4.21 实测）：屏蔽 ODE 数值零后剩 3163 条有效观测，
    V=1433 L（RSE 3.8%）可估；CL / ka / F 的 95%CI 跨四个数量级——flip-flop 加
    "F 与 V 经典混淆"。**不得把这些数当估计结果写进报告**。
  - **数据集里 ID = 化合物，不是人体受试者**：eta 是"化合物间变异"不是 IIV/BSV
    （实测 eta_cl 收缩 −427%）。任何"群体 PK"说法都必须先声明这一点。
  - **非正观测必须屏蔽**：pbpk 曲线 12–30 h 已衰减到 0，之后约 370/400 个时点
    是 ODE 数值零。当真实观测喂进去会得到"收敛但错误"的拟合
    （实测 tcl 停在初值、tv 估成 2978 L 而真实 t½≈1.6 h）。
    `mask_nonpositive_obs()` 置 MDV=1 并报条数；真做 BLQ 需 CENS=1 删失似然。
  - **仿真层往返：真因已定位（2026-11-18 第一手复测，勘误此前结论）**：本 skill 的
    `pk_sim_snapshot()` 只写 `Compounds`，`Simulations` 生来就是 `[]`（不是 CLI 丢内容）。
    实测证明 CLI **支持**仿真往返：官方 Midazolam 快照（37 条仿真）完整往返 →
    `.pksim5` 的 SQLite `SIMULATIONS` 表 =37（ObservedData=115、Protocols=33 全保留）；
    裁成 1 条并保留其引用 ObservedData 时 =1。
    此前"裁成 1 条依然丢、已排除 ObservedData 诱因"的结论**不成立**：把仿真引用的
    ObservedData 清空会直接报 `Cannot load Simulation`（`WeightedObservedData..ctor`
    空引用），但退出码仍为 0 —— 这才是"静默丢"的真机制。
    **验收标准必须是产物计数（读 .pksim5 的 `SIMULATIONS` 表），不是退出码或日志字样**；
    本 skill 自身不构造仿真，故其快照仿真层仍为空，不得声称已完成仿真层往返。
  - **pKa 是类别级区间**（±1 log），不建模取代基/邻位位阻/糖苷化；嘌呤/黄嘌呤环 N 高估碱性
    约 5 个 log（咖啡因/茶碱结论仍为中性）；邻苯二酚第二解离（pKa≈13）未单列。
    **禁止**把 `pka_centres` 写成"本分子 pKa"。
  - **菌群模块的两个已知缺陷**：① `reaction_type/enzymes` 是规则名会串底物类
    （32 分子实跑 17 条菌群产物：**9 条与质量差矛盾 / 7 条一致 / 1 条待定**），
    只可引用 smiles/inchikey 与 `label_check`，**不得把 reaction_type 当化学事实引用**；
    ② `HGUT` 对糖苷/多酚覆盖极差（本类 ALLHUMAN 实测 0 产物），
    0 必须记 `out_of_domain` 而非"无代谢"。
  - **AOMP / Graph-pKa / CardioSafe / Cardiosim-Tox / HerbToxNet / KAN-PROSPECT 的列名未实测**，
    schema 里是 `endpoints: {}`，不 `--map` 就报错。这六个源在 registry 里分别是
    `needs_probe` / `paper_only`，**不得**在材料里写成"已接入"。
  - **MASI 不可达**（`web.idrblab.cn` DNS 解析失败，2026-11-04）；网址照留，换网络再试。
  - **心脏模块曾把"有数据缺暴露"误报成"无通道数据"**（v4.21 修复）：
    仅有 IC50/抑制率、缺 Cmax,u 时旧逻辑给 `undetermined_no_channel_data`，
    把注意力从"补 Cmax"引向"再测一遍通道"，方向反了。
    现拆成 `has_data` / `tiered` 两态，新增 `undetermined_missing_exposure`
    （附"已测 k/3 通道"计数）。
  - **NONMEM / Pharmpy 要求 ID 是整数**（v4.21 修复）：`ID=A-1` 会让
    `create_datainfo` 抛 `ValueError: invalid literal for int()`。
    `nonmem_dataset` 现默认走 `nonmem_id_map()` 生成整数 ID 并落 `nonmem_id_map.csv`，
    `validate_nonmem` 对非整数 ID 直接报错（不静默转换、不丢行）。
  - **回填通道不许声明"域外/饱和/失败"**（v4.20 修复）：`readback` 只接受
    `predicted` / `measured` / `manual`（`BACKFILL_FLAGS`）。`out_of_domain` / `saturated` /
    `error` 会改变**可判性**与**是否入票**，只能由 `reliability.apply_class_blocks` 与饱和扫描产生
    —— 否则任何人只要在回填 CSV 里写一列就能把分子踢出裁决。该约束由
    `adt/flag_audit.py` 的写入点白名单 + CI 持续保证，不是一次性声明。

## 守护项细化（评审 v4.0 肯定项的不削弱承诺）

> 以下四项（对应守护项 04–06）是评审明确肯定的内容，v4.0 拔高**只增不改**：
> 保留其诚实定位，仅补充报告要求的敏感性 / 必要性边界 / 证据链升级，绝不削弱原结论。

- **04｜kNN Tanimoto 域判别（0.35 饱和 / 0.7 污染筛查）**：保留诚实定位（评审原话"做得比该领域多数论文都好"）。
  **敏感性已实测闭合（2026-11-23）**：`adt/knn_sensitivity.py` 在真实 `gate_scores`（637 分子）上跑一维网格
  ——0.35 网格 [0.25,0.30,0.35,0.40,0.45,0.50] 的 max|Δacc| = hERG 0.142 / DILI 0.194 / BBB 0.193；
  0.7 网格 [0.60…0.90] 的 max|Δacc| = 0.080 / 0.250 / 0.367。产物 `out_sensitivity/knn_threshold_sensitivity.json`。
  **关键读法**：Δacc 算在**变化了的覆盖子集**上，属 risk–coverage 权衡（模块同时给 n_new_decided/n_lost_decided）；
  因此 0.35 **按设计不冻结**（G12 持续告警），任何依赖 τ 的结论必须同时报出该敏感性带。
  未做 SALib：单旋钮 Sobol 退化为方差占比 1，网格扫描才是正确工具（理由写在模块头）。
- **05｜G5 故障注入拦截正确性**：保留 22 项故障注入作为优秀的**拦截正确性**验证（testing-as-evidence）。
  **边界声明**：G5 是**充分性测试**（证明框架能拦住已知坏输入），**不能替代必要性/合理性验证**
  （阈值为何合理需敏感性分析）。两类论证在汇报中必须分开陈述，不得用 G5 暗示"阈值合理"。
- **06｜复现性骨架升级为四元组**：保留 `out_ext/run_*.py` 复现命令、G4 freeze/verify(sha256)/supersede/diff、
  换机复现指南、F0 wheel 实测、black-list 清零台账。**升级目标**：每个关键数字生成机器可读
  `manifest.json = {value, script_sha, data_sha, env_digest, generated_at}`（见 P7 / L1-2）。

## 高专业度使用规范（SOP，评审 v4.0 §8）

> 强制纪律：任何对外数字/结论都必须遵守以下**十条**。违反任一条产出的数字视为**不可发布**。

1. **版本钉死**：任何对外数字必须携带 `{框架版本, 源版本快照, 环境 digest}` 三元组（见 P7 / manifest.json）。
2. **三态不改判**：UNDETERMINED 不得人工改 PASS/FAIL；确需改判必须走 `prereg.py` 的 supersede 留痕（同 G4 机制）。
3. **每端点必带归因**：引用任何裁决时必须连同归因标签一起引用，不得只报 verdict。归因分类以 `adt/abstain_attrib.TAXONOMY` 为**唯一真源**（弃权 8 类 + 源可靠性 1 类 = 九类；`other` 为兜底不计）。禁止再手写"第 N 类"。
4. **排序默认关闭**：确需排序时先查 regime 限定条件（校准证据充足且 n≥30；定量端点输出带不确定度分位），见 铁律3 条件化。
5. **多项目共用**：ρ 是**数据集条件量**，不是普适常数；换化学类/数据集须重新登记（见 `INDEPENDENCE_DECISIONS.md` §4 / `SOURCE_REGISTRATION_POLICY.md`）。
6. **负结果入库**：任何 badcase 按模板入库（结构扰动/单位异构/域外/源冲突），不得删除"难看"的样本。
7. **PASS 是门禁不是排序**：合成优先级必须调用连续风险层（D1）并显式声明所采用的**代价比**（见 `BAYESIAN_DECISION.md`）。
8. **红线信任边界**（2026-11-03 新增，C1 教训）：引用"框架保证 X"之前，先跑 `python -m adt.redlines` 确认该保证**在生产路径上接线**。无调用点的守卫只能表述为"文档约定"，不得表述为"已阻断"。硬度普查须如实引用（当前 7 hard / 1 soft / 1 conditional）。
9. **产物-结论配对**：任何汇报/论文中的数字必须能在 30 秒内定位到产物文件 + 生成命令 + `manifest_sha1`；`CLAIMS_REGISTRY.yaml` 是唯一入口，禁止截图/口头数字。
10. **跨课题组外推禁令**：在某个化学类上登记的 `blocked_endpoints`、`independence_group`、ρ **全部是数据集条件量**，不得跨课题组/跨化学类复用；复用前必须重新登记（`SOURCE_REGISTRATION_POLICY.md`）。

### 常见反模式（教学要点，必须规避）
- 把 UNDETERMINED 当"模型失败"而绕行；
- 对 n<30 报 ρ 结论（必须标 SMALL_N + Fisher z CI）；
- 混用 ADMET-AI web 与 local（权重不同版本，C74）；
- 把 pytest 全绿当科学结论（工程正确性 ≠ 科学有效性，须两栏分离，见 `STATISTICAL_POLICY.md`）；
- 用污染数据报绝对 MAE（F2/F6 数值须在去污染子集复核后以去污染版为准，见 `DECONTAMINATION_PROTOCOL.md`）。

### 报告与引用格式（脚注必须包含）
```
admet-screening vX.Y.Z | sources=[版本快照列表] | env=[digest] | prereg=[hash 或 "无"]
```

## 文献锚点与外部事实核查（评审 v4.0 editorial：U1 / U4 / C8）

> 评审要求对引用与外部事实锚点逐项钉死。本 skill 分发的文档遵守以下规则：

- **U1｜"Chow 1957" 为误引 → 已纠正为 Chow (1960)**：评审材料草稿写的"Chow 1957"年份错误。
  正确出处：**Chow, G.C. (1960), "Tests of Equality Between Sets of Coefficients in Two Linear Regressions",
  *Econometrica* 28(3): 591–605**（结构断点/参数恒定性检验的标准引用）。
  本 skill 分发文档此前未收录该引用；若任何章节需引用结构断点检验，须用 **1960** 而非 1957。
- **U4｜外部事实锚点已钉死可点击链接（2026-10-31 联网核实，全部 HTTP 可达）**：
  - **OpenADMET** 系列（CC-BY-4.0，已核实持久化 Zenodo DOI）：
    - PXR blind challenge data — https://doi.org/10.5281/zenodo.21617804
    - ASAP-Polaris-OpenADMET blind challenge data — https://doi.org/10.5281/zenodo.15582067
    - ASAP-Polaris ligand pose PDBs — https://doi.org/10.5281/zenodo.15320448
    - （随包 `assets/external/openadmet/`：train 5,326 / test 2,282 × 9 端点）
  - **NPASS 3.0 curated**（随包 `assets/external/npass/`：1,307 rat-LD50 + 76 ADME）：
    ⚠️ **许可纠正**：NPASS 为 **CC-BY-NC（非商业）**，此前文档误写为 CC-BY-4.0；OpenADMET 才是 CC-BY-4.0。
    官方主页 http://bidd.group/NPASS/ ；论文 Zeng et al. 2018, *Nucleic Acids Research*, doi:10.1093/nar/gkx1026。
  - Sahigara 2012 / OECD QAF 2023 / NPASS 3.0 已在 `08_literature_map.md` 列明且附录 B 抽样核验属实。
- **C8｜核心命题与 F11 降级一致**：已通过 P9 改写核心命题句（删除"共同跳过"、显式化为"独立、可审计、带归因的决策层"），
  与 F11 的 novelty 主动降级不再自相矛盾；措辞 diff 留痕于 `V4_ELEVATION_PLAN.md`（G4 supersede 机制对齐）。

## 样例边界声明与阈值普查（评审 v4.0，P12 / U9）

> 评审要求把"演示性样例"与"外部效度证据"严格区分，并对全部阈值做来源普查。

- **样例1 边界声明（C13 中）**：14 个甘草苷是同系物（congeners），在其上展示的 ρ 与分歧
  **仅演示准入机制**，**不构成外部效度证据**——同系物内部的 ρ 不能外推到化学空间其他区域。
  任何引用样例1 的结论都必须附带此声明，不得写成"在 X 类分子上源独立"。
- **22 阈值来源普查（U9）**：对 F8/判决中使用的 22 个阈值做"文献锚定 / 校准得出 / 特设"三分类计数。
  下表为**待回填模板**（不编造分类；拿到清单后逐条归类并计数）：

| 阈值 | 端点 | 来源分类（literature / calibrated / ad hoc） | 依据 |
|---|---|---|---|
| 待填 | 待填 | 待填 | 待填 |
| …（共 22 项） | | | |

  验收：普查表进附录；凡标 `ad hoc` 的阈值须补敏感性分析（±20%/±50% 翻转率，见判据速查表"阈值稳健性"）。

## 文件

```
# ---- v4.23 换机可复现层（2026-11-05 全量环境排查后新增）----
bootstrap.py               一键幂等重建：核心/可选/外部工具/指纹/自检/测试；日志落盘 logs/
bootstrap.bat / .sh        Windows / Unix 入口（CRLF+ASCII / LF，bash -n 通过）
adt/env_audit.py           纯标准库环境自检：包 import+最小功能、外部 exe 实跑、数据完整性、指纹漂移
.env_audit_paths.json      bootstrap 生成的**本机**路径映射（不要跨机拷贝）
requirements.lock          核心 10 包精确钉版（2026-11-05 实测栈）
requirements-optional.txt  可选层精确钉版（pharmpy-core / pytdc --no-deps 分组）
env_audit_report.json      env-audit 产物：每项检查的第一手证据，随复现材料归档
SETUP_REPRODUCE.md         换机复现唯一入口文档（官方网址、注册项、环境坑、四层验证、§5.1 模块 L 复现链）
env_audit_deep.json        env-audit --deep 产物：ORCA 单点能量 + 1.2 GB SI SHA256/行数证据
# ---- v4.24 OneADMET SI / ORCA 入包（2026-11-05 全盘定位后新增）----
assets/external/oneadmet/  oneADMET.csv（1.2 GB / 738,162 行）+ PROVENANCE.json（SHA256、口径、许可）
tools/                     3 个零硬编码重建脚本：SI->长表 / 量纲探针 / TDC 联网重取
tools/ 下的脚本默认按 SI SHA256 校验口径，口径不符直接拒绝复现
instances/v350/            模块 L 三组测量长表与 transfer 产物快照（可逐字节比对）
# ---- 本地无 API 工具（admet-pkpd 6 工具离线替代；2026-11-07 新增）----
local_admet/               离线、无 API 的 6 工具近似实现（RDKit）：tools.py + cli.py + __main__.py + README.md
                           工具：ADMET Predictor / AOMP / OBA / Graph-pKa / DeepEsol / Molecular Descriptors
                           用法：python -m local_admet --tool ... （无需 SciMiner key / 积分 / 联网）
                           边界：rule-based-local-proxy，非 SciMiner 模型；source=local_admet 不进 reliab 计票
# ---- 结构干扰红旗层 / 源健康 / 口径登记（2026-11-11 新增，全离线）----
adt/interference.py        PAINS_A/B/C + BRENK + NIH 离线红旗层；按 catalog 来源+结构上下文分档；
                           含类药性三态（admissible_for_rejection=False）与措辞封顶模板；产物逐字节确定
adt/source_health.py       源健康 GET 探针：带时间戳、失败落盘、不提交作业、不自动改写注册表
adt/cli.py                 新增子命令 interference / source-health
adt/claims_audit.py        新增 verify_interference_phrasing() + --interference-phrasing（F2 断言）
references/03_endpoint_rules.yaml   新增 f_oral（三分口径）+ not_covered_endpoints（5 条显式缺口）
references/VERSION_POLICY.yaml     分歧台账 4.22→4.25 补登记（修复版本守卫真实失败）
references/U9_THRESHOLD_CENSUS.md  附录：FLAG_WEAK_ONLY 命名误撞登记（枚举标签，非数值阈值）
tests/test_smoke_pytest.py SKIP 补登记 test_local_admet.py / test_interference.py（pytest 原生风格）
tests/test_interference.py 13 例回归：catalog 来源归属 / C87 / 确定性 / 不投票 / 断言正反双向
out_interference/          真实 WBLG-A/B 的干扰层产物（CSV + JSON，确定性可比对）
out_source_health/         源健康快照 source_health_latest.json
adt/env_audit.py           新增 data.oneadmet / ext.orca / --deep；discover_orca() 有限广度自动发现
# ---- 2026-11-11 第二轮：登记接线 / 物理干扰 / 统一入口 ----
adt/coverage_gate.py       未覆盖端点强制声明闸门：load_not_covered / declaration_lines /
                           verify_declaration / audit_texts / selftest；不含时间戳、确定性
adt/cli.py                 新增 coverage-gate / local-tools 子命令；report 强制并入声明段；
                           report 新增 --rules（回归注入）；命令总数 70 → 72
adt/claims_audit.py        新增 --coverage-declaration（C82 闭环断言）
adt/interference.py        新增 physical_interference() + physical_selftest()（聚集/自荧光/成醌）；
                           CSV 增 4 列 phys_*；产物仍逐字节确定
references/03_endpoint_rules.yaml  not_covered 3 项升 partially_covered（仅结构预警），
                           cyp_induction / cyp_tdi 保持 not_covered（需湿实验）
tests/test_coverage_gate.py 声明闸门回归：正反双向 / 改注册表→产物变化 / report 接线 / 不误伤
tests/test_interference.py 扩展物理层回归（C87 愈创木基 + 干净对照 + 确定性）
tests/test_local_admet.py  local-tools 主 CLI 入口回归
tests/test_module_wiring.py 零引用模块（paired_stats / saturation / tdc_local）可用性回归
out_cg_probe/              声明接线 e2e 产物（含注入缺条目规则表的负向证据）

adt/                     可执行工具包（schema / normalize / saturation / phrasing / manifest / ledger / adapters）
references/
  00_scope.md            9 层框架与边界
  01_structure_and_state.md  结构 gate 判据 + 状态标准化规则
  02_source_registry.yaml    **源清单：URL、实测状态、端点、限流、化学类白名单**
  03_endpoint_rules.yaml     端点阈值与 desirability 形状
  04_decision_funnel.md      门控与"何时才允许排名"
  05_qa_gates.md             11 条 QA gate
  06_in_silico_playbook.md   **计算模拟 playbook**：PBPK 暴露模型 / 对接红ocking Gate / MD 坑清单 / PySCF 替代 ORCA / NMR 证据分级 / **MM-GBSA 证据等级**（外部会话实测 + 本项目互证）
  07_case_lessons.md         **案例库**：17 轮实测 37 条 症状→根因→预防→自动捕获；第四列"人肉"的密度 = skill 欠账清单
  02_source_registry.yaml 内含 endpoint_aliases 交叉引用
  endpoint_aliases.yaml     **跨源端点名 -> 规范 id**（显式映射优先，子串兜底留痕）
  transporter_priors.yaml   **转运体先验 + 实验处方**（无 in-silico 源，声明式）
adt/transport.py            读上面的先验表，输出"该测什么"（不是预测）
adt/background.py           **稳健 Z 背景归一化**：相对同化学型背景的异常度（E6a）
adt/rank.py                 **bootstrap 名次区间 + 并列集合**（E7c；默认拒绝 underpowered 排名）
adt/benchmark.py            **独立分类基准**：AUROC/AUPRC + 聚类 bootstrap + 消融（E8 改造）
adt/tiers.py                **运行档位 T1/T2/T3 + 项目级结论封顶**（E0）
> 以上四项 v2.6.0 **借鉴自 reverse-molecular-docking v2.0 的治理/定量层**；其对接实验模块
> （redocking/口袋/MM-GBSA/MD）本 skill 已有对应物，不重复建。

# ---- v3.0.0 学术化层（每项都有顶刊/官方指南出处，见 references/08_literature_map.md）----
adt/calibration.py          **概率端点校准**：Brier/BSS、校准斜率-截距、O:E、ECE、分箱表
                            （Van Calster 2019, BMC Med 17:230, DOI 10.1186/s12916-019-1466-7；只对概率量纲启用）
adt/conformal.py            **split conformal 区间**：有限样本覆盖率保证（Norinder 2014 JCIM）
adt/conformal_scale.py      **难度尺度 sigma**：描述符空间 k-NN 距离 -> normalized conformal（v3.2.1；工作包 F）
adt/conformal_check.py      **F 一致性核验**：UNDETERMINED vs PASS/FAIL 区间宽度 + AUC(宽度预测弃权)
adt/governance.py           **QAF 四原则 + Hanser 三层 AD + PROBAST 偏倚风险**
                            （OECD 2023 / Hanser 2016 / Wolff 2019）
adt/reporting.py            **TRIPOD+AI 自查 + model card + FAIR 映射**
                            （Collins 2024 BMJ / Mitchell 2019 / Wilkinson 2016）
references/source_cards.yaml 8 个预测源的 model card（预期用途/训练数据/已知失效/限流）

# ---- v3.1.0 学术化升级（工作包 A/C/D/E/H/I/J；见 references/09_reliability_landscape.md）----
adt/independence.py         **独立性量化 + 校准计票**：Spearman/Fleiss κ、组权重、
                            effective_votes（伪共识）、vote_calibration（Jeffreys 平滑）
adt/certainty.py            **GRADE 式确定性修饰符**：可解决/不可解决/需实验（GRADE 30）
adt/selective.py            **risk–coverage**：结构性弃权 vs 分数型弃权；支持留一源 holdout
adt/failure_modes.py        **失效模式目录**：7 类不变量 + precision/recall
adt/perturbation.py         **结构扰动**：去盐/中和/互变/立体翻转 + 位移/分歧比
adt/decision_value.py       **决策价值**：Vickers 决策曲线 + 预算三策略期望效用
adt/dst.py                  **Dempster-Shafer 对照**：all-in vs 证据准入、过度裁决计数
references/09_reliability_landscape.md  **与 conformal/AD/DST/多数投票的分工表**（工作包 K）
adt/landscape.py            **K 机器渲染**：把 reliability_landscape.yaml 输出 CSV/Markdown 分工表（v3.2.1）

# ---- v3.3.0 深水区拔高（外部评审二次核对 2.1/2.2/2.3；见 references/10_deep_water.md）----
adt/sar.py                 **SAR 预筛轴**：TPSA/MW/HBD/HBA/XlogP × BBB± 参照集 -> 结构-通透性瓶颈诊断
adt/bbb.py                 **BBB 双层机制**：reliab 内当 vnn_bbb 裁决为 UNDETERMINED/PASSTHRU 时
                           强制改写 action 为“P-gp 底物概率评估”并激活 transporter_priors.yaml
                           ⚠️ 机制落点限制（2026-11-03 B2 量化）：三通道仅被动层 + OATP2B1(黄酮) 层有可执行 moiety 规则；
                           P-gp/BCRP/GLUT1/SGLT1/OATP1A2/LAT1 仅叙事无结构判定（见 B2_transporter_coverage.md），须降级为“仅覆盖 OATP2B1 分支”
adt/efflux_heuristic.py    **BBB 外排通道启发式**（v4.11）：P-gp/BCRP 共识药效团（Seelig 1998 HBA 距离 + Penzotti/Crivori 2002/2006）→ “有结构依据的待验证假设”；强制 Caco-2 ± verapamil/elacridar 验证、不得进 reliab 计票
adt/uptake_heuristic.py    **BBB 摄取通道启发式**（v4.12）：OATP1A2 大体积有机阴离子 / LAT1 大中性 L-氨基酸 / GLUT1 仅游离单糖 共识药效团；强制过表达细胞 ± 竞争抑制剂验证；SGLT1 因 BBB 内皮无功能表达不纳入 BBB 侧结构规则
adt/acyl_glucuronide.py    **酰基葡糖苷酸结构警示**：羧酸存在/α-碳取代/共轭程度 -> high/medium/low 风险分级
references/10_deep_water.md **深水区拔高解读**：SAR 瓶颈 / BBB 被动×P-gp 双层 / 酰基葡糖苷酸生物活化

# ---- v4.14–v4.20 扩展（截图工具收编 + PK/PD；裁决书 references/EXTENSION_ANALYSIS_v4.14.md）----
adt/ionization.py           **pKa/电离状态层**：类别级文献 pKa 区间 → 电离分数/净电荷/logD 位移区间（不冒充实测 pKa）
adt/cardiac_panel.py        **心脏离子通道三联**：hERG+Cav1.2+Nav1.5 覆盖率闸门 + 通道级裕度；不做 ORd 净效应
adt/pd_link.py              **PK/PD 连接**：Hill / 效应室 ke0 / fT>EC50 / 最小 TMDD（缺参必抛）
adt/pbpk_qualify.py         **PBPK 资格认定**：AFE/AAFE/2倍内 + 三条拒绝条件（阈值标 convention）
adt/interop.py              **PK-Sim / NONMEM / nlmixr2 互操作桥**：参数表 + 数据集契约（CMT/ID/非正观测三重校验）+ R 骨架（已真跑）
adt/gut_microbiome.py       **肠道菌群代谢**：HGUT + biosystem 过滤 + 反应标注一致性 QC + 阳性对照闸门
adt/readback.py             **通用回填通道**：无 API 工具的人工导出 → 长表（结构对齐 + 未映射列报出）
references/readback_schemas.yaml  回填列映射（`endpoints: {}` = 列名未实测，必须 --map）
references/EXTENSION_ANALYSIS_v4.14.md  **14 个截图工具的逐项裁决**：加/不加/怎么加 + 未验证清单
references/MODULE_MAP_v4.21.md  **模块全景 + 运营流程 + 五组交叉印证矩阵**（先读这个再读代码）
tests/test_extension_v414.py  44 例（含成对断言：TMDD 缺参必抛、单位不一致必抛、measured 无引文必降级、回填禁写 out_of_domain/saturated/error、给药/观测同腔必被拒）+ nlmixr2 骨架必须带"ID=化合物不是 IIV"警语
references/desirability_method.md  几何平均为何成立（Derringer-Suich 1980 / CNS MPO）
references/truth_contract.md        truth.csv 字段、单位口径、回填与跑法
assets/truth_template.csv   空白真值模板（14×3 端点）
assets/controls/controls.csv 对照集（含期望值，接入新源必跑）
assets/external/            **随包公开数据（v3.2.0）**：openadmet/（CC-BY-4.0，train/test/raw）
                            + npass/（1,307 rat-LD50 + 76 ADME）；见其 README
adt/external.py             **外部数据接入 + RDKit/Morgan 基线**（v3.2.0；工作包 B/G）
adt/adapters/            各源适配器（biotransformer / chembl / xenosite / admet_ai / protox3 / admetlab3 / vnn）
adt/stats_ci.py          **P2 统计推断**：Clopper-Pearson 95% CI 注册门（registration_gate）+ 设计端通过概率曲线（gate_pass_probability）+ Holm–Bonferroni 多重比较校正（holm）+ 标准正态分位数（_z，已修复 alpha/3 静默退回 1.96 的伪校正；scipy）
adt/independence.py      **P1 扩展**：`rho_contraction_weight`（n_eff 截断 + ρ<0 冲突分流）+ 独立性决策（见 `INDEPENDENCE_DECISIONS.md`）
adt/prospective.py        **P4 扩展**：`paired_mcnemar` 配对检验（C7）
adt/phrasing.py          **P5 扩展**：`flag_unqualified_superiority` 略优审计护栏（C2）
examples/benchmark_vs_truth.py  **E1/E2 基准框架**：框架 vs 均值投票基线 vs 金标准
pyproject.toml / requirements.txt / LICENSE / .github/workflows/ci.yml

# ---- v4.0 拔高参考文档（评审 v4.0：P1–P13 / L1–L3；状态见 references/V4_ELEVATION_PLAN.md）----
references/V4_ELEVATION_PLAN.md     **中央台账**：35 项执行清单 + 状态（✅/🟡/⬜/⛔）
references/INDEPENDENCE_DECISIONS.md  **P10/C4**：三机制分工 + 冲突优先级 + ρ 三区分流决策表
references/STATISTICAL_POLICY.md      **P2/L1-2**：Clopper-Pearson 注册门 + n≳60 真实曲线 + 统计推断规范
references/RISK_COVERAGE_PROTOCOL.md **P3/P8/守护04**：risk–coverage + 随机化零对照 + kNN 阈值敏感性
references/DECONTAMINATION_PROTOCOL.md **P6/L2-4**：去污染子集复核 + 0.6/0.7/0.8 三档敏感性
references/SOURCE_REGISTRATION_POLICY.md **P11/L2-3**：源纳入/排除预注册 + ρ 元数据一等公民
references/ADAPTER_COMPLIANCE.md     **P13**：7 适配器 ToS 合规审查框架
references/BAYESIAN_DECISION.md      **L1-1/L1-3**：贝叶斯决策层 + 代价比敏感性网格
references/EXCHANGEABILITY_PROTOCOL.md **L2-1/D5**：conformal 交换性诊断 + weighted 对照
references/TDC_ALIGNMENT.md          **L2-2**：TDC 官方协议对齐 + 框架/leaderboard 脱钩
references/SAP_PROTOCOL.md           **L3-1~L3-4**：SAP/OSF + 契约测试重放 + 证据 DAG + 第二实现者
references/REPRODUCIBILITY.md        **P7**：lockfile + Docker digest + manifest.json 四元组

# ---- v4.4 第三轮评审落地（§A–§G；逐项执行记录见 references/REVIEW_ROUND3_CLOSEOUT_v4.4.md）----
adt/claims_audit.py          **G10**：主张登记表审计（产物存在 + 数字字面量命中）
adt/defaults.py              **G11**：负结果→默认配置（8 条默认值各带产物级证据）
adt/threshold_audit.py       **G12**：阈值冻结审计（登记值 vs 代码字面量漂移检查）
run_tail_risk_stratified.py  **E1**：外源集按 Tanimoto 分层的 AUC 趋势（决定性实验；`--year-mode` 控时间切分）
run_external_cuts_summary.py **E1 复审**：三切点并排，区分"稳健结论"与"切法产物"（v4.4 自查更正）
run_indifference.py          **A4**：无差异曲线（准入层的 c*）
run_spec_multiverse.py       **A6**：216 规格灵敏度（方向翻转率）
run_independence_gradient.py **A1**：受控独立性梯度（共享训练比例 α）
run_leakage_confound_check.py **E2**：近邻归因代理的负值复核
references/TAIL_RISK_THESIS.md           **E1+E3**：门的价值在尾部 + 域内/域外认识论分层
references/CLAIMS_REGISTRY.yaml          **G10 真源**：17 条数字主张 → 产物 + 字面量
references/NEGATIVE_RESULT_DEFAULTS.yaml **G11 真源**：8 条负结果 → 默认值
references/THRESHOLD_REGISTRY.yaml       **G12 真源**：11 条阈值来历/冻结/敏感性
tests/test_v44_guards.py     红线 7–9 的成对断言（违反必抛 + 合规必放行）
tests/test_v44_gates.py      G10/G11/G12 的门禁自检（含"构造坏数据必须 red"）
```

---

## 执行器能力边界与交付物唯一来源（v4.32 新增，技能市场移植）

> 借鉴 `@user_f4fc8899/bio-admet-prediction` 的诚实边界句式：
> **本 skill 的交付物 = 本地可复现命令 + manifest 身份 + 字段级证据链。**
> 本 skill **不运行上游工具链、不操作第三方账号**；只有**经核验的本地产物**才是可引用交付物。
> 外部源（PubChem/TDC/PK-Sim/第三方预测服务）的返回只作为**待准入证据**，
> 必须经 `source-admit` / `independence` / G13 estimand 门后才能进入裁决，
> 不得把第三方输出冒充本框架产出。此条与 `trust` 证书的
> `not_a_proof_of` 字段、`env-audit` 不伪造 git_commit、预注册不冒充已注册同属一条纪律。

## 合规映射矩阵（v4.32 新增，技能市场移植）

> 借鉴 `@user_15d05850/legal-regulatory-compliance-mapper` 的
> "义务→控制→证据→审查计划"四元映射。本 skill 已有四件但缺显式串联：
> `合规义务(端点/场景)` → `控制(G门禁 + 9红线)` → `证据(CLAIMS_REGISTRY 字段级绑定)` →
> `审查计划(review_cycle + 补实验 action)`。查某项合规要求时按此链逐跳给出可审计映射，
> 未覆盖的跳标 `coverage_gap`，不得跳级声称"已合规"。
> **注意**：本 skill 不对接任何具体法规的合规结论；只提供内部可审计映射，
> 不声称符合 FDA/OECD/ICH 任一体系（见 `references/POSITIONING_EVIDENCE` 的措辞纪律）。
