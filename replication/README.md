# 复现挑战包 keystone-v41

本包**只给**：指标定义（到公式）、容差、数据快照指纹、实验设置。
本包**不给**：预测概率、每种子明细、任何中间产物——第二实现者必须自己跑出流程。
**通过判据**：`counted=true` 的指标全部落在容差内（共 6 项）；`counted=false` 的指标容差已接近其量级，判别力不足，只作参考、不参与判定。

## 指标与容差（容差 = k × 种子标准差）

| 指标 | 期望值 | 容差 | 种子 sd | n_seeds | 类型 | 计入判定 |
|---|---|---|---|---|---|---|
| `hERG.S1_naive_majority.auc` | 0.8352 | ±0.021562 | 0.010781 | 20 | auc | 是 |
| `hERG.S1_naive_majority.utility` | -0.2348 | ±0.009128 | 0.004564 | 20 | utility | 是 |
| `hERG.S4_full_admission.coverage` | 0.182 | ±0.05623 | 0.028115 | 20 | coverage | 是 |
| `hERG.S4_full_admission.risk_decided` | 0.1025 | ±0.100698 | 0.050349 | 20 | risk_decided | 否（判别力不足） |
| `DILI.S4_full_admission.utility` | -0.4479 | ±0.024396 | 0.012198 | 20 | utility | 是 |
| `BBB_Martins.S4_full_admission.utility` | -0.3818 | ±0.007082 | 0.003541 | 20 | utility | 是 |
| `hERG.delta_utility.S4_minus_S1` | -0.197 | ±0.015358 | 0.007679 | 20 | delta_utility | 是 |

## 指标定义

- `hERG.S1_naive_majority.auc`：AUC-ROC，以 FAIL=1 为正类，用该策略实际使用的分数（校准后概率或原始概率）
  - 注：无准入基线的判别力（校准前原始分数）；期望值取 20 个种子的中位数，容差=2×种子sd
- `hERG.S1_naive_majority.utility`：cost-weighted utility = −(1/N)·Σ cost_i，cost = c_abstain（弃权）/ c_false_PASS（真 FAIL 判 PASS）/ c_false_FAIL（真 PASS 判 FAIL）/ 0（判对）。y=1 表示 FAIL。
  - 注：无准入基线的代价加权效用（delta 指标的分母侧，用于定位误差来源）；期望值取 20 个种子的中位数，容差=2×种子sd
- `hERG.S4_full_admission.coverage`：coverage = (给出 PASS/FAIL 的样本数) / N（弃权不进分子）
  - 注：完整准入层的判定覆盖率——**准入层的代价就体现在这里**；期望值取 20 个种子的中位数，容差=2×种子sd
- `hERG.S4_full_admission.risk_decided`：risk_decided = 在已判定样本中的错误率 = 错判数 / 已判定数
  - 注：已判定样本内的错误率（与 coverage 必须成对读，单看会误判）；期望值取 20 个种子的中位数，容差=2×种子sd；⚠ 容差/量级=0.98≥0.5，该指标判别力不足，仅作参考、不计入 all_pass
- `DILI.S4_full_admission.utility`：cost-weighted utility = −(1/N)·Σ cost_i，cost = c_abstain（弃权）/ c_false_PASS（真 FAIL 判 PASS）/ c_false_FAIL（真 PASS 判 FAIL）/ 0（判对）。y=1 表示 FAIL。
  - 注：代价加权效用（c=(5,1,0.5)）；期望值取 20 个种子的中位数，容差=2×种子sd
- `BBB_Martins.S4_full_admission.utility`：cost-weighted utility = −(1/N)·Σ cost_i，cost = c_abstain（弃权）/ c_false_PASS（真 FAIL 判 PASS）/ c_false_FAIL（真 PASS 判 FAIL）/ 0（判对）。y=1 表示 FAIL。
  - 注：端特异代价（c=(3,1,0.5)）；期望值取 20 个种子的中位数，容差=2×种子sd
- `hERG.delta_utility.S4_minus_S1`：Δutility = utility(A) − utility(B)，逐种子配对后取中位数
  - 注：逐种子配对差；其余端点中位数（仅供对照，不单独做容差）：DILI +0.0130, BBB_Martins -0.2229

## 数据快照（必须用同一快照，否则数字不可比）

| source | snapshot_id | sha256 | bytes |
|---|---|---|---|
| admet_ai | `batch_run6__0739335b93b1__20261031T140641Z` | `0739335b93b16620` | 13701 |
| admetlab3 | `batch_run6__ab79d850b067__20261031T140641Z` | `ab79d850b067f6c6` | 13441 |
| biotransformer | `batch_run6__39f960aeba29__20261031T140651Z` | `39f960aeba295a41` | 2019 |
| chembl | `batch_run6__dbce090ea31a__20261031T140641Z` | `dbce090ea31a27e2` | 14703 |
| protox3 | `batch_run6__7a0f5d563cd2__20261031T140651Z` | `7a0f5d563cd20914` | 4625 |

## 实验设置（必须照此实现，不得替换组件）


### 1. 数据与切分

- **source**：TDC ADMET_Group 的 hERG / DILI / BBB_Martins 三个端点
- **columns**：SMILES 在列 `Drug`，标签在列 `Y`；列名不同时按下标取第 1/2 列
- **split**：对每个端点的 train_val 取 numpy.random.default_rng(0).permutation(n)，前 80% 为 fit 集、后 20% 为 calibration 集（取整：cut=int(0.8*n)）；test 集全量用于评估，**不参与任何拟合、校准或阈值选择**
- **label_semantics**：y=1 表示 FAIL（阳性）
- **invalid_molecules**：RDKit 无法解析的 SMILES 直接丢弃，不插补、不替换

### 2. 预测源（逐一实现，不得替换）

- name=rf_morgan；features=Morgan 指纹 radius=2, nBits=2048（ECFP4 等价）；model=RandomForestClassifier(n_estimators=300, random_state=seed, n_jobs=1)；score=predict_proba(X)[:, 1]
- name=ridge_desc；features=10 个 RDKit 描述符，顺序固定：MolWt, MolLogP, TPSA, NumHDonors, NumHAcceptors, RingCount, CalcFractionCSP3, NumRotatableBonds, NumAromaticRings, MaxPartialCharge；NaN/inf 一律置 0；model=StandardScaler（在 fit 集拟合）+ RidgeClassifier(alpha=1.0)；score=sigmoid(decision_function)；这是伪概率，只用于排序与求均值
- name=rf_maccs；features=MACCS keys，167 位；model=RandomForestClassifier(n_estimators=300, random_state=seed, n_jobs=1)；score=predict_proba(X)[:, 1]

### 3. 校准

- **method**：每个源各拟合一个 IsotonicRegression(out_of_bounds='clip')，x=该源在 calibration 集上的原始分数，y=calibration 标签；同一转换再应用到 test
- **mean**：mean_pc = 三个源校准后概率的算术平均
- **fallback**：任一源拟合抛异常时，该源退化为恒等映射（不得借此剔除该源）

### 4. 适用域判据

- **rule**：对每个 test 分子，计算它到 **fit 集全部训练分子** 的 Morgan2-2048 Tanimoto 相似度的最大值；max_sim ≥ 0.35 判为域内
- **note**：域判据只用 fit 集做参照，不得用 calibration 或 test

### 5. 阈值规则（在 calibration 上选，应用到 test）

- **grid**：t 取 numpy.linspace(0.05, 0.95, 19)
- **min_keep**：只接受 keep=(mean_pc_cal ≥ t) 且 keep.sum() ≥ max(10, 0.2×len(cal)) 的 t
- **risk**：在 keep 子集上 pred=(mean_pc_cal ≥ 0.5)，risk=mean(pred ≠ y_cal)
- **select**：在 risk ≤ 0.15 的候选中取 coverage 最大者对应的 t；若无候选满足，取 t=0.5
- **apply**：选出的 t 原样用于 test，不得在 test 上重新调

### 6. 四个策略的精确定义

- **S1_naive_majority**：pred = 三源**未校准**概率各自以 0.5 二值化后的多数投票（≥2 票为 FAIL）；对全部 test 样本给出判定（不弃权）。注意：不是用均值概率阈值（那与票数多数在本数据上差约 0.03 效用），而是用三源二值票数的多数
- **S2_ad_guard**：pred 同 S1（票数多数）；仅当 max_sim ≥ 0.35 时给出判定，否则弃权
- **S3_calibrated_conformal**：pred = (mean_pc ≥ 0.5)；仅当 mean_pc ≥ t 时给出判定
- **S4_full_admission**：pred = (mean_pc ≥ 0.5)；仅当 mean_pc ≥ t 且 max_sim ≥ 0.35 且 spread ≤ 0.30 时给出判定，其中 spread = max(三源**未校准**概率) − min(三源未校准概率)
- **口径说明（重要）**：auc / risk 字段一律在 mean_pc_te（三源校准后概率均值）上计算，**与策略无关**；指标名前缀只表示该策略对应的基线，不代表 AUC 用的是该策略自己的二值分数——这是已知的命名缺陷，读取时请按本条理解

### 7. 代价与效用

- **formula**：utility = −(1/N)·Σ_i cost_i，N=test 样本数；cost = 0（判对）/ c_false_PASS（y=1 判成 PASS）/ c_false_FAIL（y=0 判成 FAIL）/ c_abstain（弃权）
- **costs**：
  - `hERG`: [5.0, 1.0, 0.5]
  - `DILI`: [5.0, 1.0, 0.5]
  - `BBB_Martins`: [3.0, 1.0, 0.5]
- **note**：弃权样本计入分母 N，且只计 c_abstain

### 8. 随机种子

- 0
- 1
- 2
- 3
- 4
- 5
- 6
- 7
- 8
- 9
- 10
- 11
- 12
- 13
- 14
- 15
- 16
- 17
- 18
- 19

### 9. 环境指纹

- **note**：提交时必须附 python/rdkit/scikit-learn/numpy 实测版本

## 怎么交

1. 按 `SUBMISSION_TEMPLATE.json` 填 `metrics.<name>.value`（数字）。
2. 填 `implementation`（`code` / `repo` / `files` 至少一项）与 `environment`
   （`python` / `rdkit` / `numpy`）——**只交数字不算复现**。
3. 跑 `python score.py submission.json` 自评：

| verdict | 退出码 | 含义 |
|---|---|---|
| `pass` | 0 | 数字全过 + 实现/环境齐备 → 视为复现成功（仍需人审代码） |
| `pass_with_manual_review` | 0 | 数字全过但零偏差 → 规范确定时属必然，须人审 |
| `numbers_only` | 2 | 数字全过但缺实现/环境 → **不构成复现**，退回补交 |
| `fail` | 1 | 至少一个 counted 指标超容差 |

