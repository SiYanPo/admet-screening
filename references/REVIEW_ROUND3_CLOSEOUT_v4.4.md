# 第三轮评审（v4.2/v4.3 合并终版）逐项执行记录 v4.4

> 对端：`references/REVIEW_ROUND3_CHECKLIST_v4.4.md` 的 33 项清单。
> 体例对标 `UNRESOLVED_CLOSEOUT_v4.3.md`：**每项写"做了什么 / 产物在哪 / 还剩什么"**，
> 不写"已按意见整改"这种无法验证的话。
>
> 本文档额外记录一件评审没提、由本包自查发现的事：**"post-cutoff" 标签是错的**（§C 专项）。

---

## A. §A 传输与指纹（#1 #2）

| # | 结论 | 产物 |
|---|---|---|
| 1 | 打包缺口：见 §G「v4.4 材料包」——v4.3 五项 + v4.4 新增 9 项全部入包，MANIFEST 重算 | `外部评审材料产物_v4.4/`（工作目录） |
| 2 | 轮次命名统一：CLAIMS 头部改为 **材料轮次 v4.4**，并新增"本版相对 v4.1 的三处更正" | 同上 `CLAIMS.md` |

---

## B. §B 首轮闭合（#3 #4）

| # | 结论 | 产物 |
|---|---|---|
| 3 | **"✅ 附产物路径 + 数字"已机器化**：19 条主张 × 产物 × 字面量 token，`verify_registry()` 逐条核对；新增 `tier=headline` 断言（**恰好一条 + 必须带 CI**），负例实测会失败 | `references/CLAIMS_REGISTRY.yaml`、`adt/claims_audit.py`、`out_ext/claims_registry_check.json`（19/19 通过） |
| 4 | 红 6 公式纠正：`n_eff = k²/(1ᵀR1)`；特征值式保留为 `n_eff_kish_eigen()` 但**禁用于计票权重**；台账 R03 行已加注 + 新增"v4.4 更正"节 | `adt/independence.py`、`references/REVIEW_v4.1_LEDGER.md` |

---

## C. §C 次轮 A1–A10（#5–#11）

| # | 结论 | 产物 |
|---|---|---|
| 5 | **A1 已做（第一悬案关闭）**：α∈{0,.25,.5,1} × 20 种子。ρ_within 0.655→0.978、一致率 0.939→0.977（伪共识签名），但 **vote_gain 在所有 α 上 ≤0** → `overlap_raises_agreement_not_value`：**瓶颈是方法同源，不是共享数据** | `run_independence_gradient.py`、`out_ext/tdc/independence_gradient.json`、`INDEPENDENCE_DECISIONS.md` §6 |
| 6 | A2 语义固化（`insufficient_power`）：已确认在 `adt/mmp.py` + 判据表 | — |
| 7 | **A3 已做**：8 条负结果 → 默认值，每条带产物级证据，`assert_consistent()` 三重校验（yaml↔代码↔产物字面量） | `references/NEGATIVE_RESULT_DEFAULTS.yaml`、`adt/defaults.py`、`release_gate.G11` |
| 8 | **A4 已做**：c\*(abstain) hERG 0.26 / BBB 0.2091 / DILI 未识别；口径纠正 **9 个代价点**（非 12） | `run_indifference.py`、`out_ext/keystone_indifference.json/.md` |
| 9 | **A6 已做**：216 规格（9×4×2×3），better 72 / worse 109 / mixed 35，翻转率 **0.398** → `specification_fragile`；ref 点 S4−S5 与报告逐位吻合 | `run_spec_multiverse.py`、`out_ext/keystone_spec_multiverse.json/.md` |
| 10 | **A8 已做**：11 条阈值登记，漂移=阻断、未冻结=告警；`ad_anchor 0.35` 有意不冻结（附近无断点） | `references/THRESHOLD_REGISTRY.yaml`、`adt/threshold_audit.py`、`out_ext/threshold_freeze_audit.json` |
| 11 | A5/A7/A9/A10 回填：A5「基线过强」→ 已被 S5 否证，v4.2 计分卡加"v4.4 追注"；A7 N1–N5 保留；A9 第二实现者维持 🟡（自检，非第三方，不改口）；A10 外源前瞻的"非预注册"标注保留并在 §C 专项里加严 | `TASK_SCORECARD_v4.2.md`（追注）、`POSITIONING.md` §4b |

---

## C′. 专项：**"post-cutoff" 标签更正**（自查发现，评审未提）

### 发生了什么

v4.3 把外源集写成 "post-cutoff 外源留出（文献年 ≥ 2023，n=9443）"。
时间条件交给了 ChEMBL 服务端 `document__year__gte=2023`，**该参数在 activity 端点实测不生效**：

- `>=2015 / >=2021 / >=2022 / >=2023` 四种取值返回同一个 `total_count = 19130`；
- 落盘缓存里 `document_year` 覆盖 **1995–2025**，≥2023 仅 **9.6%**（1842/19130）。

结论：n=9443 那批是 **ChEMBL_37 hERG IC50 全集去重（时间混合）**，不是时间留出。

### 为什么必须自曝

本包整套外源认识论（红线 8）建立在"这是后见数据"这个前提上。前提错 → 标签错 →
等于给回溯性结果贴前瞻性标签。这正是本包一直批评别人的那种"用标签代替证据"。

### 改了什么

1. `fetch_activities` 增 `year_mode`：**一律本地按 `document_year` 切分**，
   `requested/applied_min_year、n_before/after、year_unknown、cache_year_min|max、
   server_side_filter_reliable` 全部落盘（`LAST_FETCH_META` → 产物 `source.year_filter`）。
2. 顺手修 `_get()`："先 `import requests` 再查缓存" → 干净机/评审复现包离线必崩。改为缓存优先。
3. 新增 `run_external_cuts_summary.py`：三切点并排成一张表。

### 更正后的事实表

| 集合 | 条件 | n | overall AUC | 同批平凡基线 | 桶级趋势 | 判定码 |
|---|---|---|---|---|---|---|
| mixed | 不过滤 | 9443 | 0.581 | 0.679 | 单调↑（ρ=0.90） | `boundary_quantified_but_no_usable_region` |
| y2021 | ≥2021 | 1941 | 0.584 | 0.632 | **非单调** | **`trend_not_robust`** |
| y2023 | ≥2023 | 959 | 0.598 | 0.628 | **非单调**（0.599/0.422/0.588/0.663/0.627） | **`trend_not_robust`** |

### 结论怎么改的

| 命题 | 更正前 | 更正后 |
|---|---|---|
| 域外有排序能力吗 | 弱 | **没有**（三切点 0.58–0.60 全低于平凡基线）→ 更强 |
| AUC 随 Tanimoto 单调上升 | 是 | **撤回**（2/3 切分非单调） |
| 门精确划出了能力边界 | 方向正确 | **撤回**；只能说域外**处处**不可用 |
| 门该不该全拒 | 该 | **该**——理由是"处处不可用"，不是"知道边界在哪" |

**新合成句**：门在域外的正确性是**保守的正确**，不是**精确的正确**。

> 这一条比原表述弱，但它是**两个独立切点支持**的。按本包自己的标准：弱的真话 > 强的假话。

---

## D. §D 新实证裁决（#12–#17）

| # | 结论 | 产物 |
|---|---|---|
| 12 | 红线 9 已代码化（三端点并列），gate 数字必须带种子范围 | `adt/guards.py::endpoint_plurality_line`、`tests/test_v44_guards.py` |
| 13 | `compressed` 回归支语义已固化（R<1 的均值回归必然性 + 符号一致率合读） | `references/GATE_AND_P8_MMP_v4.2.md` §压缩语义 |
| 14 | **新增统计口径节**：绝对 MAE/RMSE 一律报**中位数 [Q1,Q3]**；并新增"统计量与 CI 必须同源"的错配禁令 | `references/STATISTICAL_POLICY.md` §4 |
| 15 | "基线过强"措辞清理：v4.2 计分卡加 v4.4 追注，明令不得再写成"尚未排除" | `TASK_SCORECARD_v4.2.md` |
| 16 | headline 数字已登记：**三切点版本**（含不稳健那半句），`tier=headline` + `rank:1` + `interval` + `supersedes`；G10 会断言"恰好一条" | `CLAIMS_REGISTRY.yaml::external_cuts_headline` |
| 17 | Ames 产品故事：0.269→**0.177**（少放行 116 个致突变物），代价同句报出（放行率 0.399→0.155） | `references/POSITIONING.md` §4b、`README_CN.md` |

---

## E. §E 合并核心判断（#18–#23）

| # | 结论 | 产物 |
|---|---|---|
| 18 | E1 联合结论已写，但**强度被 §C′ 下调**（见该节） | `references/TAIL_RISK_THESIS.md` |
| 19 | E1 决定性实验已做 ×3 切点；`mixed` 判 `boundary_quantified_but_no_usable_region`，两个真时间留出判 `trend_not_robust` | `run_tail_risk_stratified.py`、`run_external_cuts_summary.py` |
| 20 | E2 补检验：H1（记忆驱动）/H2（一致率驱动）**均不成立** → BBB 的 −0.212 **回退为未解释**，不硬编解释 | `run_leakage_confound_check.py`、`out_ext/tdc/leakage_confound_check.json` |
| 21 | **F4"非我方可关闭"定性已撤回**并附实验 | `INDEPENDENCE_DECISIONS.md` §6 |
| 22 | E3 认识论分层（域内/域外）+ 合成句 | `TAIL_RISK_THESIS.md` §6 |
| 23 | E4 四项（A3/A4/A6/A8）全部落地 | 同 #7–#10 |

---

## F. §F 三位专家增补（#24–#28）

| # | 结论 | 产物 |
|---|---|---|
| 24 | 0.098 差距已给区间：AUC CI **[0.569, 0.593]**（全在 0.679 之下）；另给"阈值 0.5 准确率 − always-positive"的配对 bootstrap CI。**口径微调**：原表报"差值中位数 0.0"易误读，已加均值与说明 | `herg_holdout_stratified.json::r1_interval_requests`（mixed 版保留在 `_legacy_stratified.json`） |
| 25 | 循环论：①分层不用 0.35（用分位数）；②**R2 要求的复制做了**（两个年份切点），且复制**否掉了初版强表述**；③第二**数据源/端点**仍未做 → ⛔ 登记开放 | `TAIL_RISK_THESIS.md` §7 |
| 26 | `ad_anchor 0.35` 不冻结的理由已写入阈值登记表（附近无断点，仅工程工作点） | `THRESHOLD_REGISTRY.yaml::ad_anchor` |
| 27 | 方法学短文骨架已成文 | `references/METASCIENCE_NOTE_OUTLINE.md` |
| 28 | 版本纪律：`4.0-dev` 未动（G9 按 R11 拒绝授 v4.0） | `SKILL.md` frontmatter |

---

## G. §G 三条新红线（#29–#31）与 §H（#32）

| # | 结论 | 产物 |
|---|---|---|
| 29–31 | 红线 7/8/9 代码化，成对断言（违反必抛 + 合规必放行）+ 元断言（登记恰好 9 条） | `adt/guards.py`、`tests/test_v44_guards.py`（18 项） |
| 32 | 论文骨架 + OSF 预注册清单已成文（报告 §H 的"该停止做实验了"） | `references/PAPER_SKELETON_v4.4.md` |

---

## H. v4.4 材料包（#1 #2 的落地）

见工作目录 `外部评审材料产物_v4.4/`：

- 五件：`CLAIMS.md`（轮次改 v4.4 + 三处更正声明）、`README.md`、`README_INDEX.md`、`VERIFICATION.md`、`MANIFEST.sha256`
- 数据包：`admet-screening-review-data_v4.4.tar.gz`
  新增入包：`out_keystone_v43/results.json`、`out_ext/tdc/ad_multicriteria.json`、
  `out_ext/external/herg_holdout.json` + 三切点产物、`out_ext/tdc/independence_gradient.json`、
  `out_ext/tdc/leakage_confound_check.json`、`out_ext/keystone_indifference.*`、
  `out_ext/keystone_spec_multiverse.*`、`out_ext/threshold_freeze_audit.json`、
  `out_ext/claims_registry_check.json`、`UNRESOLVED_CLOSEOUT_v4.3.md`、
  `TAIL_RISK_THESIS.md`、`CLAIMS_REGISTRY.yaml`、`NEGATIVE_RESULT_DEFAULTS.yaml`、
  `THRESHOLD_REGISTRY.yaml`、`REVIEW_ROUND3_CHECKLIST_v4.4.md`、本文档
- 包内 `MANIFEST.internal.sha256` 全量 `-c` 校验通过

---

## 一句话总结（放这里，因为它是本轮的真正产出）

> 这一轮把评审要的四项处方（A3/A4/A6/A8）全做了，把第一悬案（A1）做了，
> 把三条新红线代码化了——**然后在做的过程中发现自己上一个结论的标签是错的，
> 并把它撤回了。**
> 一个能在自己身上查出"post-cutoff 其实是时间混合"的框架，
> 比一个只会按评审清单打钩的框架更值得被信任。
