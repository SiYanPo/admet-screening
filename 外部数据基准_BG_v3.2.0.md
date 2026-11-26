# v3.2.0 工作包 B/G 实跑报告：外部公开数据随包分发 + 真实基准

> 目标：不再只给"接入协议"，而是把可再分发的公开数据随包放进 skill，并能离线跑出
> **真实实测真值**的 AUROC/AUPRC。
> 所有数字来自本机实跑（2026-10-29），不是示意值。

---

## 1. 随包数据

| 数据 | 许可证 | 规模 | 体积 | 官方来源 |
|---|---|---|---|---|
| OpenADMET-ExpansionRx FULL | **CC-BY-4.0** | train 5,326 / test 2,282 分子 × 9 终点；raw 15,226 行含 RLM | ~1.4 MB | Zenodo 21504733（DOI 10.5281/zenodo.21504733） |
| NPASS 3.0 curated | 学术免费（cite NAR 2026;54:D1519） | 1,307 个大鼠 LD50 化合物 + 76 条 ADME + 1,338 结构 | ~240 KB | bidd.group/NPASS（官方下载页） |

目录：`assets/external/openadmet/`、`assets/external/npass/`；各自有 `README.md`、
`PROVENANCE.json`，OpenADMET 另有 `LICENSE.md`（CC-BY-4.0）。

> **没有分发**：评审提到的"NPASS 3.0 三工具基准（201,905 化合物 + 142 Caco-2 实测）"
> 不在 NPASS 官方下载包中（官方 `activities` 里 ADME 记录仅 1,521 条且多数单位不明）。
> 本报告分发的是**官方实测 ADME/Tox curated 子集**；三工具预测可用 skill 的 `web`
> 适配器重建。

---

## 2. 接入命令（可复现）

```bash
PY="C:/Users/huawei/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

# OpenADMET：train/test -> 契约表
$PY -m adt.cli external --dataset openadmet --data-dir assets/external/openadmet \
    --split train --outdir out_ext
$PY -m adt.cli external --dataset openadmet --data-dir assets/external/openadmet \
    --split test --outdir out_ext

# 基线：RDKit 描述符 / Morgan 指纹 + Ridge
$PY -m adt.cli baseline --train-meas out_ext/measurements_train.csv \
    --test-meas out_ext/measurements_test.csv \
    --train-compounds out_ext/compounds_train.csv \
    --test-compounds out_ext/compounds_test.csv \
    --method both --rules out_ext/external_rules.yaml --outdir out_ext

# 真实基准（必须用 *_risk.csv）
$PY -m adt.cli benchmark --predictions out_ext/measurements_baseline_rdkit_risk.csv \
    --truth out_ext/truth_test.csv --rules out_ext/external_rules.yaml --outdir out_ext/bench_rdkit
$PY -m adt.cli benchmark --predictions out_ext/measurements_baseline_morgan_risk.csv \
    --truth out_ext/truth_test.csv --rules out_ext/external_rules.yaml --outdir out_ext/bench_morgan

# NPASS：curated 子集 -> 70/30 确定性切分 -> 基线 -> 基准
$PY -m adt.cli external --dataset npass --data-dir assets/external/npass --outdir out_npass
$PY -m adt.cli baseline --train-meas out_npass/measurements_train.csv \
    --test-meas out_npass/measurements_test.csv \
    --train-compounds out_npass/compounds_train.csv \
    --test-compounds out_npass/compounds_test.csv \
    --method both --rules out_npass/npass_rules.yaml --outdir out_npass
$PY -m adt.cli benchmark --predictions out_npass/measurements_baseline_rdkit_risk.csv \
    --truth out_npass/truth_test.csv --rules out_npass/npass_rules.yaml --outdir out_npass/bench_rdkit
```

---

## 3. OpenADMET-ExpansionRx 结果（test 2,282 分子 / 10,738 对）

| 端点 | RDKit AUROC [95% CI] | Morgan AUROC [95% CI] | 读法 |
|---|---|---|---|
| Caco-2 Efflux | 0.800 [0.779–0.820] | 0.706 [0.681–0.729] | 外排比最好预测 |
| Caco-2 Papp | 0.728 [0.704–0.752] | 0.644 [0.620–0.670] | RDKit 描述符占优 |
| HLM CLint | 0.642 [0.608–0.675] | 0.644 [0.612–0.675] | 中等 |
| KSOL | 0.695 [0.670–0.718] | **0.823 [0.800–0.844]** | 指纹明显更好 |
| LogD | 0.530 [0.511–0.549] | **0.692 [0.658–0.726]** | 指纹明显更好 |
| MBPB | 0.696 [0.647–0.740] | **0.824 [0.789–0.857]** | 指纹明显更好 |
| MGMB | 0.804 [0.745–0.860] | 0.802 [0.720–0.881] | 两者都好 |
| MLM CLint | 0.508 [0.471–0.546] | 0.516 [0.471–0.560] | **接近随机**（清除率难预测） |
| MPPB | 0.498 [0.324–0.675] | **0.918 [0.883–0.953]** | 小样本，区间宽 |
| **平均** | **0.656** | **0.730** | Morgan 总体更好 |

**解读**：
- 这不是"本 skill 的预测性能"，而是两个 **Ridge 基线**在真实项目数据上的表现；
  它的用途是给 `benchmark`、`selective`、`decision-value` 提供真实真值入口。
- MLM CLint 接近随机，与文献"微粒体清除率跨项目难外推"一致；提示该端点应强制
  `UNDETERMINED` 或补实测，而不是硬报。
- Morgan 在 LogD/KSOL/MBPB 上显著优于 RDKit 描述符，说明"描述符够不够"本身是
  端点依赖的——这正是 skill 的 `independence` / `background` 要暴露的。

---

## 4. NPASS 3.0 curated 结果（1,307 化合物；916 train / 391 test）

| 基线 | AUROC [95% CI] | AUPRC | 备注 |
|---|---|---|---|
| RDKit 描述符 | **0.660 [0.595–0.720]** | 0.243 | 391 对；优于随机 |
| Morgan 指纹 | 0.562 [0.481–0.643] | 0.221 | 接近随机 |

标签：大鼠 LD50 **< 300 mg/kg = FAIL（高毒）**，≥300 = PASS；阈值是**分析选择**，
不是监管阈值。天然产物化学空间与 OpenADMET 的药物样空间差异很大，这个结果说明
"同一基线跨化学类会退化"——正好支撑 skill 的"化学类→源白名单"判据。

---

## 5. 实跑中发现并修复的 bug（3 个）

| # | 症状 | 根因 | 修复 |
|---|---|---|---|
| 1 | 同一基线 AUROC 系统性 <0.5（Caco-2 Papp 0.272、MGMB 0.196） | benchmark 以 FAIL=正类计分，而 KSOL/Papp/% unbound 是"越高越好"，原始预测方向相反 | `oriented_score()` 按 shape 翻转；另存 `*_risk.csv` 供 benchmark；修复后同基线 0.66–0.73 |
| 2 | `external` 直接 `PermissionError` | `write_manifest` 对 data_dir（目录）做 SHA1 | 只把产物入 manifest |
| 3 | `baseline` 超时（>120 s 被杀） | 每个端点都重新解析 5k 分子的描述符/指纹 | 每 split 矩阵只算一次，再按端点切片（RDKit 21.8 s / Morgan 25.2 s） |

---

## 6. 诚实边界（写论文时必须带）

- `baseline_rdkit` / `baseline_morgan` 是 **Ridge 基线**，不是 ADMET-AI/ADMETlab/admetSAR；
  不能拿它声称"本 skill 的预测性能"。
- PASS/FAIL 阈值（OpenADMET 的 KSOL 10 µM、HLM 30 mL/min/kg、LD50 300 mg/kg 等）
  是**分析选择**，用于二分类基准，不是监管阈值。
- OpenADMET 是真实项目数据（Expansion Therapeutics），CC-BY-4.0；使用时必须署名。
- NPASS 学术免费；商业使用需自行核对 NPASS 条款。
- 评审提到的"201,905 化合物三工具预测表"未随包分发；本 skill 只分发官方实测子集。
- `benchmark` 的 CI 是**按化学簇 bootstrap**；当前基线的簇来自 `--scaffold-from` 未启用，
  因此区间是 pair-level bootstrap，**偏窄**；论文中应补 scaffold split。

---

## 7. 产物索引

- `out_ext/`：OpenADMET 契约表、基线预测、`bench_rdkit/benchmark.csv`、`bench_morgan/benchmark.csv`
- `out_npass/`：NPASS 契约表、基线预测、`bench_rdkit/benchmark.csv`
- `assets/external/`：随包数据 + 许可证 + `README.md`
- `examples/extract_npass.py`：NPASS 子集抽取脚本（可复现）
