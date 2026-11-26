# truth.csv 契约（独立基准的实测真值）

> 用途：`adt.cli benchmark` 的唯一合法真值来源。**没有实测就没有真 AUROC**——
> `--demo` 只是验证指标代码，产物在 `tier` 里**不计入** `has_benchmark`。

## 1 为什么必须是实测

本 skill 的铁律：**预测值不能当真值**。用某个源的预测去"验证"另一个源，是循环论证；
用 `--demo` 的合成真值报 AUROC，是自欺。`benchmark` 的数字只有在 truth.csv 来自
**实验测量**时才可引用。

对应反向 skill E8 的"真值构建"要求：有实验证据的直接测量；未知不标阴性；重复去重。

## 2 字段（`assets/truth_template.csv` 已按 14 分子 × 3 端点生成空白模板）

| 列 | 必填 | 说明 |
|---|---|---|
| `compound_id` | ✅ | 与 compounds.csv 一致（A–N） |
| `endpoint` | ✅ | 规范 id：`caco2_papp_ab` / `ppb_fu` / `clint_microsome`（可扩展） |
| `truth_value` | ✅ | 实测值，单位见 §3；数值必须有限 |
| `truth_class` | 可选 | `PASS`/`FAIL`；留空则由 rules 阈值从 truth_value 判定 |
| `source` | ✅ | 实验来源（实验室/文献/外包 CRO） |
| `assay` | ✅ | 方法（如 "Caco-2 21d TEER>400, 双向"、"平衡透析 37°C 24h"、"HLM+NADPH 时程"） |
| `provenance_url` | ✅ | 文献 DOI/报告号/原始数据文件名——**缺失即无溯源链（C49 同源）** |
| `note` | 可选 | n、重复、异常说明 |

## 3 单位与端点（必须与 `03_endpoint_rules.yaml` 一致）

| endpoint | 单位 | 说明 |
|---|---|---|
| `caco2_papp_ab` | `log10(cm/s)` | **不是** cm/s；线性 Papp 先取 log10 再填 |
| `ppb_fu` | `fraction` | 游离分数 0–1；若测的是 %bound，先换算 `fu = 1 − bound/100` |
| `clint_microsome` | `uL/min/mg` | 微粒体固有清除；负值/越界会被 `phys_range` 挡掉 |

## 4 优先级（按性价比，与 `04_decision_funnel` §5 / 湿实验方案一致）

1. **Caco-2 双向**（14 个）→ 同时解决渗透 + 外排；是 `Fa` 最大不确定源。
2. **平衡透析 fu**（14 个）→ 直接替换 PPB 预测；影响 Margin 口径。
3. **HLM CLint**（14 个）→ 替换清除率预测（当前 ADMET-AI 偏低/偏快，是 t½ 分歧主因）。

> 哪怕只测 **3–5 个代表分子 × 1 个端点**，`benchmark` 就能出第一个真实 AUROC；
> 但 `n_pairs < 30` 时会打"不足以支撑统计结论"的警告——那是诚实的提示，不是故障。

## 5 回填后怎么跑

```bash
# PY 换成任意可用的 Python 3.11+ 解释器（依赖见 requirements.txt）；
# 以下两种调用方式等价（adt 包带 __main__.py）：
#   python -m adt.cli ...
#   python -m adt ...
# 1) 用模板填出 truth.csv（保留表头，删掉未测行或留空）
# 2) 跑基准（预测长表 + 真值）
$PY -m adt benchmark --predictions out/measurements.csv --truth truth.csv \
    --clusters clusters.csv --outdir out
# 3) 重新评估档位：有真值基准后 tier 才可能升到 T3
$PY -m adt tier --reliability out/reliability.csv --coverage out/coverage_matrix.csv \
    --benchmark out/benchmark.csv --request T3 --outdir out
```

`benchmark` 会拒绝把缺 `provenance_url` 的真值当作合格实测（打警告并要求补齐），
这与 `tier` 的"demo 不计入 has_benchmark"是同一条纪律的两端。
