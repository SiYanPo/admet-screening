# 撤回记录 · RETRACTION NOTE（2026-11-04）

**触发来源**：`ADMET_Skill_PeerReview_2026-11-04.html`（综合性同行评审报告）§1.1 / §2.3 / §3.1 C01、§3.4 领域级修正、§4 A1/A2、§5.1 复审、§6.1 外审 A（C18）、§6.2 外审 B。
**执行对象**：`admet-screening` skill（版本标识 4.0-dev）。
**性质**：**结论撤回 + 推断资格撤销**，不是数值更正，也不是措辞润色。
**当前效力**：在 `references/ENDPOINT_ESTIMAND_CARDS.yaml` 完成端点 estimand 绑定、且 Q4/P4 求证闭合之前，本文所列结论**不得**进入论文、汇报、基金申请、组会 PPT 或对外材料。

---

## 一、被撤回的结论（旧句 → 新状态）

| # | 旧句（原文） | 位置 | 新状态 |
|---|---|---|---|
| R1 | 「三套集合的 overall AUC（0.581/0.584/0.598）全部低于同批 always-positive（0.679/0.632/0.628）→ 模型在域外没有排序能力，这条独立于切法」 | `run_external_cuts_summary.py` v1 docstring、`TAIL_RISK_THESIS.md` §1/§2/§3.3/§7/§8、`SKILL.md` §核心结论、`CLAIMS_REGISTRY.yaml::external_cuts_headline` | **撤回**：跨量纲比较，无效 |
| R2 | 「域外**处处**不可用；门全拒是**保守的正确**，不是精确的正确」 | `TAIL_RISK_THESIS.md` §3.3/§8、`PAPER_SKELETON_v4.4.md` 预测 #2 / Fig 6 / §3.2、`POSITIONING.md`、`SKILL.md` | **撤回**：由 R1 推出，支点失效 |
| R3 | 「在域外，准入层会拒答；而强行预测会显著劣于平凡基线——已证实（三切点）」 | `PAPER_SKELETON_v4.4.md:21` 可证伪预测 #2 | **撤回** |
| R4 | 「准入层的条件性价值可用弃权代价刻画，无差异点存在且可估计——已证实（c\* 0.21–0.26）」 | `PAPER_SKELETON_v4.4.md:22` 可证伪预测 #3 | **撤回**：会计恒等式，见 §五 |
| R5 | 「R2 要求的『复制一次』已做：两个年份切点结论同向」 | `TAIL_RISK_THESIS.md` §7 第 2 步 | **撤回**：嵌套子集 + 口径错误，✅→❌ |
| R6 | 「三条红线已在 `adt/guards.py` 代码化……发布门禁 G8 读取」 | `TAIL_RISK_THESIS.md` §8 末段、`SKILL.md` 红线章节 | **撤回**（C02 实跑证伪）：在 A3 修复前降级为「文档约定」 |

---

## 二、根因：一个跨量纲比较（C01）

`run_external_cuts_summary.py` v1 第 78–80 行：

```python
"below_trivial_baseline": (
    None if (ov.get("auc") is None or ov.get("always_positive_accuracy") is None)
    else bool(ov["auc"] < ov["always_positive_accuracy"])),
```

- `auc` 是**排序能力**指标，随机基线 **0.5**，量纲为「随机取一正一负时正例得分更高的概率」；
- `always_positive_accuracy` 是**分类准确率**（把所有样本判为阳性），恒等于该批 `prevalence`，量纲为「正确分类比例」；
- 二者不可比。`auc < prevalence` 在 prevalence > 0.5 的数据集上几乎必然为真，与模型好坏无关。

该字段导出 `robustness.below_trivial_baseline_all_cuts = true`，进而生成 `reading[]` 第 ①③ 条，是 `TAIL_RISK_THESIS` §2/§3、可证伪预测 #2、Fig 6 与「门全拒是保守的正确」的**唯一量化支点**。

**产物自带的三条反证**（无需新实验即可闭合）：

1. `auc_ci95` 三切点下界 **0.569 / 0.560 / 0.562 全部 > 0.5**；
2. y2021 `accuracy_at_0.5 = 0.634 > prevalence 0.632`，按正确 accuracy 口径**方向反转**；
3. `robustness.max_bucket_auc_below_065_all_cuts = false`，而 §3.3 写「三个切分里没有一个能稳定过 0.65」——产物自证结论反向。

---

## 三、正确双轨口径与实测数据支撑（v2 产物，已实跑）

`run_external_cuts_summary.py` v2 把一条错误 bool 拆成两条**不可合并**的轨道：

| 轨道 | 比较对象 | 方法 | 来源 |
|---|---|---|---|
| `auc_vs_chance` | AUC ↔ **0.5** | 引用上游已落盘 `auc_ci95`；单侧 p 由 CI 宽度反推 SE 的正态近似（`z=norm.ppf(0.975)` 动态求）；标 `ci_inversion_normal_approx` | `r1_interval_requests.auc_ci95` |
| `accuracy_vs_prevalence` | acc@0.5 ↔ **prevalence** | 引用上游**逐分子差配对 bootstrap 95%CI**（已存在于三份 `_stratified.json`，v1 汇总脚本从未使用）；McNemar 因缺逐样本 2×2 表如实标 `mcnemar_computable=false`，不伪造 | `r1_interval_requests.accuracy_at_0.5_minus_always_positive` |

| 切点 | n | prevalence | AUC | auc_ci95 | acc@0.5 | acc−prev | 配对 bootstrap CI | `accuracy_below_majority_class` |
|---|---|---|---|---|---|---|---|---|
| mixed | 9443 | 0.679 | 0.581 | [0.569, 0.593] | 0.674 | −0.005 | [−0.0084, −0.0005] | **True**（显著） |
| y2021 | 1941 | 0.632 | 0.584 | [0.560, 0.610] | 0.634 | **+0.002** | [−0.0062, +0.0108] | **False**（不显著，方向为正） |
| y2023 | 959 | 0.628 | 0.598 | [0.562, 0.635] | 0.620 | −0.008 | [−0.0209, +0.0063] | **True**（不显著） |

因此：
- `accuracy_below_majority_class_all_cuts = false`（不是「三切点一致」）；
- `auc_ci95_lower_above_chance_all_cuts = true`；
- `nested_subsets_not_independent = true`：y2023 ⊂ y2021 ⊂ mixed，同一 ChEMBL_37 快照、同一靶点 CHEMBL240，`all(...)` 属**伪重复**，不构成独立复现。

**产物处置**：新写 `out_ext/external/external_cuts_summary_v2.json`（`schema_version=2.0`、含 `supersedes`）；旧 `external_cuts_summary.json` 保留全部原字段，仅注入 `superseded_by` / `superseded_reason` / `retained_for_audit_only`，使错误结论可审计但不再被引用。

---

## 四、领域级修正：**禁止翻转**（外审 B，本报告采纳）

统计上把「怎么比」纠正为「AUC 对照 0.5、accuracy 对照 prevalence」是成立的；但从 ADMET 决策角度，**"域外仍有弱排序能力"这一外推同样不可接受**：

- hERG gate AUC 0.580 伴随误杀率 0.826；BBB AUC 0.514 [0.440, 0.595] 近乎随机；对安全端点而言 AUC 略高于 0.5 不产生决策价值；
- 更根本的是**真值仍是未定义标签**：hERG 的实验金标准应是膜片钳 IC50（电压协议／温度／血清／尾峰电流），而本框架 `03_endpoint_rules.yaml` 把它写成 `unit: probability` + `pass:0.1 / fail:0.5`，并混用 `class_map{"0":PASS,"1":FAIL}`；
- 因此正确处置不是把结论从「无排序能力」翻转为「有弱排序能力」，而是**撤销该结论的推断资格**：`inference_status = inference_revoked_pending_estimand`，并标 `estimand_status = NOT_AN_ESTIMAND`。

**重估的前置条件**（缺一不可）：
1. `references/ENDPOINT_ESTIMAND_CARDS.yaml` 为 hERG 写出完整端点卡（实验金标准、单位与浓度标度、正负判定规则、实际暴露物种、实验室间一致性）；
2. Q4（Ames 规则层覆盖度是否造成错判）与 P4（心脏安全／CiPA 专家核 Redfern 2003 与 ICH S7B）求证闭合；
3. 三切点伪重复按 `references/SPEC_CURVE_POLICY.md` 正式处理，或用第二数据源／第二端点重跑。

在此之前：**AUC 与 accuracy 都不承载「门该不该拒答」的决策含义**。

---

## 五、第二次撤回：Δu / c\* 是会计恒等式（C18，外审 A 独立复算）

- `costs` 在 `pick_threshold` / `strategies` 函数体内**零引用**（AST 已证）；`run_keystone.py:272-278` 明写「同一预测，只改代价，不重训」；
- 故 Δu(c) = a − q·c（q = 弃权率），外审 A 对 `results.json::cost_sweep` 线性回归得 **R² = 0.9999995**、斜率 **0.8189**、c\* = **0.2598 ≈ 登记值 0.26**；
- 「无差异点存在且可估计」是线性函数零点的**代数必然**，不是可证伪命题；「条件性优势区 c ≤ 0.26」由同一批数据倒推，不是事前假设；
- 处置：撤回可证伪预测 #3 与 Fig 3 的「已证实」字样；`cost_sweep` 每档落 `sha256(decided_mask)`，若 hash 集合大小 = 1 即标 `accounting_only=true` 并由 `phrasing` 拦截 `c* / 条件性优势区 / 无差异点` 出现在对外文本。真正的重构（代价进入决策 π(c)）见 `references/ESTIMAND.yaml` 与 `references/COST_ELICITATION.md`。

---

## 六、影响范围清单（逐项已改 / 待改）

| 对象 | 处置 | 状态 |
|---|---|---|
| `run_external_cuts_summary.py` | 全量重写为 v2 双轨口径 | ✅ 已改并实跑 |
| `out_ext/external/external_cuts_summary_v2.json` | 新产物，含 `supersedes` / `inference_status` | ✅ 已生成 |
| `out_ext/external/external_cuts_summary.json` | 注入 `superseded_by`，原字段保留 | ✅ 已标记 |
| `references/TAIL_RISK_THESIS.md` | §1 / §2 / §3.3 / §7 / §8 逐处加撤回标记 | ✅ 已改 |
| `references/PAPER_SKELETON_v4.4.md` | 预测 #2/#3、Fig 6 行、Fig 6 警告段 | ✅ 已改 |
| `SKILL.md` | 核心结论第 1 条、v4.4 自查段「仍在的」 | ✅ 已改 |
| `references/CLAIMS_REGISTRY.yaml` | headline 标 `status: superseded` + `admissible_for_external_use: false`；`external_holdout_auc` 补 CI | ✅ 已改 |
| `references/POSITIONING.md`「保守的正确」 | 撤回并连到本文 | ⏳ 见执行项 21 |
| `TAIL_RISK_THESIS.md` §4 / §6 | 连带撤回 | ⏳ 见执行项 21 |
| `PHRASING` 禁用词表 | 加入五类禁句 | ⏳ 见执行项 10 |

---

## 七、核验命令与验收判据（可复制执行）

```bash
PY="C:/Users/huawei/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
ROOT="C:/Users/huawei/.workbuddy/skills/admet-screening"
cd "$ROOT"

# 1) 重跑汇总并核对双轨判据
"$PY" run_external_cuts_summary.py
"$PY" -c "import json;d=json.load(open('out_ext/external/external_cuts_summary_v2.json',encoding='utf-8'));\
print([c['accuracy_below_majority_class'] for c in d['cuts']]);\
print(d['robustness']['auc_ci95_lower_above_chance_all_cuts'], d['robustness']['inference_status'])"
# 期望: [True, False, True] / True / inference_revoked_pending_estimand

# 2) 旧产物必须带撤回标记且原字段未丢
"$PY" -c "import json;d=json.load(open('out_ext/external/external_cuts_summary.json',encoding='utf-8'));\
print(d['superseded_by'], len(d['reading']))"

# 3) 全文检索：所有旧句命中处必须带「已撤回/RETRACTED/superseded」标记
grep -rn "保守的正确\|处处不可用\|全部低于同批\|低于平凡基线" . --include=*.md --include=*.yaml --include=*.py
```

**判据**：v2 产物 `below_trivial_baseline` 字段在 `cuts[]` 中零命中；`cross_dimensional_comparison.valid=false`；`inference_status=inference_revoked_pending_estimand`；旧产物 `retained_for_audit_only=true`；所有旧句命中行含撤回标记。

---

## 八、状态与责任边界

- **当前状态**：`RETRACTED / pending re-estimation`。不是「已修复」，不是「已重估」。
- **对外引用冻结**：`CLAIMS_REGISTRY.yaml::external_cuts_headline` 的 `admissible_for_external_use=false`；发布门禁应对任何 `status: superseded` 且被 `tier=headline` 引用的条目报 warn（见 `HARD_CONSTRAINTS_v5.md`）。
- **不得洗白**：本次撤回是**评审外部发现**（C01），不是本框架第五次「自己推翻自己」。`CHANGELOG.md` 必须如实记为外部评审发现，不得写入自我更正叙事。
- **仍保留的资产**：v4.4 post-cutoff 标签更正（真实、自主发现）、桶级单调趋势不稳健（与 C01 无关）、Clopper–Pearson 主实现与 Holm 校正、`run_gate_multiplicity.py` 的多重比较处理、负结果如实登记的传统。撤回不抹杀这些。

## 九、必须保留的求证项（不得以臆测代替结论）

| # | 求证对象 | 问题 | 判定标准 |
|---|---|---|---|
| P4 | 心脏安全／CiPA 电生理专家 | Redfern 2003 是否给出 10/30/100 三档；hERG IC50 与游离 Cmax,u 是否可比 | 原文条款编号 + ICH S7B Q&A；产出「哪些量不可相除」清单 |
| Q4 | 统计审稿人 | Ames「规则层未覆盖」是否被读成阴性并造成实际错判 | 逐分子 `alert_hit` 重跑 + 95%CI |
| D01 / P9 | 方法学编委 | 端点 estimand 未定义时，「负结果 + 失效边界」是否足以构成方法学主文 | 近 3 年该刊受理标准 + 一条「estimand 未定义即拒稿」可引用判例 |
| Q01 | 数据审计 | 外源集与 TDC 训练集的 InChIKey／骨架重叠 | 逐键比对 `out_ext/tdc_cache/` 与 `out_ext/external/cache/` |

---

*本文为 2026-11-04 评审落地产物；所有数字来自本机实跑的 v2 产物，外审独立复算结果（R²=0.9999995）已标注来源，未冒充一手证据。*
