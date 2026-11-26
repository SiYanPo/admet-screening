# 全生命周期 run_report（命令收敛决策证据表）

> 生成器：`tools/run_report_lifecycle.py`（可重算）。
> **数据窗声明**：本 skill 首次提交 2026-11-05，生命周期约 3 周（2026-11-05 → 2026-11-23，18 天）。
> 因此**不存在 6 个月日志**——这不是欠账，而是时间未到。本表是已观测窗口的真实证据，只支持分阶段收敛提案，不支持「已删减」结论。
> 6 个月窗口到达后重跑本脚本即可自动扩展，无需改代码。

## 1. 数据源

- `fullrun_20261122/runlog.jsonl`（73 条结构化调用）
- `logs/*.log`（26 个日志文件，9 条命令串）

## 2. 汇总

| 口径 | 数值 |
|---|---|
| 观测数据窗 | 2026-11-05 → 2026-11-23（18 天） |
| 注册命令总数 | 78 |
| 窗口内有调用的命令 | 61 |
| 窗口内零调用的命令 | 17 |
| 结构化调用条数（runlog） | 73 |
| 日志命令串条数 | 9 |
| runlog 记录失败数 | 6 |
| runlog 累计执行秒数 | 1716.8 |

## 3. 高频命令（Top 20）

| 命令 | 层 | evidence_role | 调用次数 |
|---|---|---|---|
| `env-audit` | core | governance | 11 |
| `ablate` | evidence | evidence_only | 1 |
| `abstain-cmp` | evidence | evidence_only | 1 |
| `abstain-why` | decision | decision_chain | 1 |
| `ac-plan` | experimental | experimental | 1 |
| `acyl-glucuronide` | sources | evidence_only | 1 |
| `advisory-check` | decision | decision_chain | 1 |
| `background` | sources | evidence_only | 1 |
| `baseline` | evidence | evidence_only | 1 |
| `benchmark` | evidence | evidence_only | 1 |
| `benchmark-demo` | ? | ? | 1 |
| `benchmark-split` | ? | ? | 1 |
| `bt-sygma` | ? | ? | 1 |
| `certainty` | decision | decision_chain | 1 |
| `claims-fragility` | decision | decision_chain | 1 |
| `conformal` | evidence | evidence_only | 1 |
| `conformal-check` | evidence | evidence_only | 1 |
| `conformal-class` | evidence | evidence_only | 1 |
| `conformal-scale` | evidence | evidence_only | 1 |
| `coverage` | evidence | evidence_only | 1 |

## 4. 收敛决策纪律

1. 本表**不是**删减决定：evidence 层命令（门禁/审计）平时零调用、发布/审稿时必跑，   零调用 ≠ 可删。
2. 真正的删减门槛仍是「6 个月零调用 + 非门禁层 + 非契约端点」三者同时满足；   当前窗口只有 3 周，任何命令都**尚未**满足时间条件。
3. 建议的「核心 20 / peripheral 58」仅作文档分层声明，不物理删除，保留可复算路径。
4. 本表取代旧的「等 6 个月」待办：时间到达后重跑即可，无需人工复算。
