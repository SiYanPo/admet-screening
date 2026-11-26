# local_admet —— 离线、无 API 的 6 工具本地实现

把 `admet-pkpd` skill 里原本要走 **SciMiner API**（需 `~/.config/sciminer/credentials.json`
+ 积分）的 6 个工具，做成**纯本地、离线、零依赖外部服务**的近似实现。

| 原工具（SciMiner） | 本地函数 | 本地方法 | 保真度 |
|---|---|---|---|
| Molecular Descriptors | `molecular_descriptors()` | RDKit 精确计算 | **高** |
| DeepEsol | `deep_esol()` | Delaney ESOL 溶解度 + ΔG 代理 | 中 |
| Graph-pKa | `graph_pka()` | 官能团 SMARTS + 文献 pKa 经验值 | 低-中 |
| OBA | `oba()` | Martin(2005) 评分 + 剂量-溶解度粗判 | 低 |
| AOMP | `aomp()` | AOX 结构警报 + SOM 启发 | 低 |
| ADMET Predictor | `admet_predictor()` | 多端点规则/警报筛查 | 低 |

## 必须声明（否则视为误用）

- 这些是 **rule-based-local-proxy**，**不是** SciMiner 的训练模型；数值仅供**筛查排序**，
  **不得**当作 SciMiner 输出、**不得**用于对外定论。
- `ADMET Predictor` 各端点 `prob_proxy` 是**名义值**（0.2–0.75），不是校准概率；
  `E` 类（清除/t½）尤其粗糙。
- `Graph-pKa` 不建模取代基/邻位效应；`DeepEsol` 的 `dG_solv_proxy` 与真实 ΔG_solv **不等价**。
- 需要 regulator-grade 或对外数字时，仍应走 SciMiner API 或把它当 `readback` 的实测回填源。

## 用法

```bash
cd "C:/Users/huawei/.workbuddy/skills/admet-screening"

# 列出工具
python -m local_admet --list-tools

# 单分子，单工具（输出 JSON）
python -m local_admet --tool "Molecular Descriptors" --smiles "CC(=O)Oc1ccccc1C(=O)O"

# 单分子，跑全部 6 个工具
python -m local_admet --tool all --smiles "Cn1cnc2c1c(=O)n(C)c(=O)n2C"

# 批量文件（每行：SMILES [id]），只跑 ADMET Predictor 的毒性类
python -m local_admet --tool "ADMET Predictor" --smiles-file lib.smi \
    --features T --out out/admet_pred.json

# 输出 measurements.csv 兼容长表（source=local_admet, domain_flag=predicted）
python -m local_admet --tool "Molecular Descriptors" --smiles-file lib.smi \
    --format long --out out/local_admet_desc.csv

# 自检（6 分子 × 6 工具）
python -m local_admet --selftest
```

## 与 admet-screening 长表契约的关系

`--format long` 输出的列：`compound_id, endpoint, value, unit, source, source_version,
retrieved_at, domain_flag, uncertainty, provenance_url, note`。

- `source = local_admet`，`source_version = 1.0.0`，`domain_flag = predicted`。
- **不要**把 `source=local_admet` 直接塞进 `reliab` 计票：它不在
  `references/02_source_registry.yaml` 的注册源里，属**探索/筛查层**，不进多源裁决。
- 若要进入正式流程，应作为 `readback` 的实测回填源（`--provenance-url` 给实验/工具引文），
  而不是冒充一个预测源。
- **确定性档（2026-11-11 补）**：默认 `retrieved_at` 写运行时间戳，两次运行不能逐字节
  比对。加 `--deterministic` 后写固定占位 `DETERMINISTIC`，可与 skill 其他产物一样做
  sha256 复现校验；默认行为不变（向后兼容）。主 CLI 同样支持：
  `python -m adt.cli local-tools --tool DeepEsol --smiles "CCO" --format long \
      --deterministic --out out/esol.csv`
