# 风险–覆盖曲线与扰动零对照协议（RISK_COVERAGE_PROTOCOL）

> 对应处方：**P3（risk–coverage，C3 致命）/ P8（扰动随机化零对照，C9 高）/ 守护项04（kNN 阈值敏感性）**。
> 本文档为**方法学 + 待真实数据闭环**项：命令与脚本已给定，数值栏在拿到实验室数据前以"待跑"占位（不伪造）。

## 1. P3：risk–coverage 曲线 + 全弃权基线对照（C3）
**问题**：三态裁决（PASS/FAIL/UNDETERMINED）无任何成本矩阵、风险–覆盖权衡或最优弃权率推导；
"全部 UNDETERMINED"策略同样零假阳性，框架无法证明它比"永远弃权"提供了更多信息（C3 致命）。

**做法**（基于已有 `selective` 模块，扩到前瞻性输出）：
1. 对 ExpansionRx 前瞻输出（`prospective` 产物）绘制 risk–coverage 曲线：x=覆盖率，y=在该覆盖率下
   被裁决子集的失败率（或期望损失）。
2. **显式报告"全弃权"基线的点**（覆盖率 0、风险=整体 base rate），并标注框架曲线是否在
   该点之上构成**支配**（dominance）。
3. 给定代价矩阵示例（如 FP 代价 c_fp、FN 代价 c_fn），给出**最优弃权率**（使期望损失最小化的弃权比例）。
4. **分层与指标**：按端点类型（分类/连续）与 base rate 分层绘制；新增 **AUARC**（Area Under the
   Abstention–Risk Curve）作为选择性质量的可比指标；聚合曲线仅作汇总、不作论据。
5. 三态阈值的**代价比出处**写入文档（见 `BAYESIAN_DECISION.md`）。

**命令骨架**：
```bash
$PY -m adt.cli selective --reliability out/reliability.csv --truth truth.csv --outdir out   # 已有
# 新增：前瞻性 risk–coverage（待实现 out_ext/run_risk_coverage_*.py）
$PY -m adt.cli risk-coverage --prospect out/prospect_admission.csv --truth late_truth.csv \
    --stratify-by endpoint_type,base_rate --outdir out_ext
```
**验收**：分层图 + AUARC 表进主材料；三态阈值的代价比出处写入文档。状态：🟡 待真实前瞻数据闭环。

## 2. P8：结构扰动随机化零对照（C9 高）
**问题**：45 SMILES、63 例翻转、中位比 0.57——作为敏感性证据合格，但**无参照系**，效应量无定义（C9）。

**做法**：
1. 为 45 SMILES 各生成 **≥100 个合法分子随机扰动**（保持原子数/官能团、仅改连接/立体/互变异构的
   随机合法变体；用 RDKit 合法性校验过滤）。
2. 零模型报**翻转率与中位比的分布**；真实扰动效应（去盐/中和/互变/立体翻转）报告为**率差 + 95% CI**
   （bootstrap 或正态近似），效应 = 真实翻转率 − 零模型翻转率。
3. 零模型分布图 + 率差 CI 表进附录。

**命令骨架**：
```bash
$PY -m adt.cli perturb --compounds out/compounds.csv --outdir out          # 已有真实扰动
# 新增：随机化零模型（待实现 out_ext/run_null_model_*.py）
$PY -m adt.cli perturb-null --compounds out/compounds.csv --n-per 120 --outdir out_ext
```
**验收**：零模型分布图 + 率差 CI 表。状态：🟡 待合成合法扰动库闭环。

## 3. 守护项04：kNN Tanimoto 阈值敏感性 —— ✅ 2026-11-18 已闭环（诚实边界见下）
- 0.35（饱和判别）在 [0.25, 0.5]、0.7（污染筛查）在 [0.6, 0.9] 网格上做敏感性，
  报告翻转/新增/丢失判定的网格敏感性。
- **方法偏离说明（必须随结果一起引用）**：原计划用 SALib 全局敏感性；因本问题只有
  **单个阈值旋钮**，Sobol 方差分解退化（单输入方差占比恒为 1），不提供超出一维网格的信息，
  且为退化指标引入 SALib 依赖违背"简单优先"。故改用 **1D 网格扫描**，这是单旋钮敏感性
  的正确工具。若将来 0.35/0.7 变为 2+ 个联合旋钮，再补 SALib。
- 命令：`$PY -m adt.cli knn-sensitivity --outdir out_sensitivity`（新增专用模块 `adt/knn_sensitivity.py`）
  自检：`$PY -m adt.cli knn-sensitivity --selftest`
- 数据：`out_ext/tdc/gate_scores_{hERG,DILI,BBB_Martins}.csv`（逐分子 y_true/sim/gate_passed，真实数据非合成）。
- **实测结果（2026-11-18，产物 out_sensitivity/knn_threshold_sensitivity.json）**：
  | 端点 | 旋钮 | 基线域内 n | max\|Δaccuracy\| | 判定 |
  |---|---|---|---|---|
  | hERG | saturation(0.35) | 86 | 0.1424 | threshold_critical |
  | hERG | contamination(0.7) | 25 | 0.0800 | stable_under_grid |
  | DILI | saturation(0.35) | 33 | 0.1939 | threshold_critical |
  | DILI | contamination(0.7) | 1 | 0.2500 | threshold_critical（基线域内仅 1 例，结论脆弱） |
  | BBB_Martins | saturation(0.35) | 229 | 0.1928 | threshold_critical |
  | BBB_Martins | contamination(0.7) | 30 | 0.3667 | threshold_critical |
  - **负结果**：6 个端点×旋钮组合中 **5 个**在网格上准确率摆动 14%–37%，
    即基于单一 0.35/0.7 阈值的结论**不稳健**，不得作为对外结论的支点；
    必须在材料中同时报告阈值网格区间。DILI contamination 基线域内仅 1 例，
    该档结论的推断资格应撤销（样本不足）。
- 诚实边界：本扫描量化的是"域内子集 gate 准确率"对阈值的敏感度，
  不等于完整 SALib 意义上多参数交互的全局敏感性；这是欠账的正确关闭方式，
  不是把 🟡 洗白成 ✅ 的全面验证。
