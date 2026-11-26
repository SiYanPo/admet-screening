# 命令使用率普查（78 命令；数据窗=fullrun_20261122 + logs）

> 生成器：`tools/command_usage_census.py`（可重算）。
> **数据窗声明**：这不是 6 个月用户日志，而是本仓库 2026-11-22 实跑的 73 次调用 +
> `logs/*.log` 中的命令串。用它只能支持「分阶段收敛提案」，**不能**支持「已删减」。

## 汇总

| 口径 | 数量 |
|---|---|
| 注册命令总数 | 78 |
| 本窗口有调用 | 61 |
| 本窗口零调用 | 17 |
| 建议核心集（20） | 20 |

## 有调用的命令（按次数降序）

| 命令 | 层 | evidence_role | 次数 | 在建议核心集 |
|---|---|---|---|---|
| `env-audit` | core | governance | 11 | 是 |
| `ablate` | evidence | evidence_only | 1 | 是 |
| `abstain-cmp` | evidence | evidence_only | 1 |  |
| `abstain-why` | decision | decision_chain | 1 |  |
| `ac-plan` | experimental | experimental | 1 |  |
| `acyl-glucuronide` | sources | evidence_only | 1 |  |
| `advisory-check` | decision | decision_chain | 1 |  |
| `background` | sources | evidence_only | 1 |  |
| `baseline` | evidence | evidence_only | 1 |  |
| `benchmark` | evidence | evidence_only | 1 | 是 |
| `certainty` | decision | decision_chain | 1 |  |
| `claims-fragility` | decision | decision_chain | 1 | 是 |
| `conformal` | evidence | evidence_only | 1 | 是 |
| `conformal-check` | evidence | evidence_only | 1 |  |
| `conformal-class` | evidence | evidence_only | 1 |  |
| `conformal-scale` | evidence | evidence_only | 1 |  |
| `coverage` | evidence | evidence_only | 1 |  |
| `coverage-gate` | decision | decision_chain | 1 | 是 |
| `cross-class` | evidence | evidence_only | 1 |  |
| `decision-value` | decision | decision_chain | 1 |  |
| `desire` | decision | decision_chain | 1 | 是 |
| `dst` | evidence | evidence_only | 1 |  |
| `endpoint-tiers` | evidence | evidence_only | 1 |  |
| `env-fp` | core | governance | 1 |  |
| `fail-layers` | evidence | evidence_only | 1 |  |
| `failure-modes` | evidence | evidence_only | 1 |  |
| `glycoside-hyd` | sources | evidence_only | 1 |  |
| `indep-bayes` | evidence | evidence_only | 1 |  |
| `indep-power` | evidence | evidence_only | 1 |  |
| `independence` | evidence | evidence_only | 1 |  |
| `interference` | evidence | evidence_only | 1 |  |
| `interop` | core | io_utility | 1 |  |
| `knn-sensitivity` | evidence | evidence_only | 1 |  |
| `landscape` | evidence | evidence_only | 1 |  |
| `ledger` | core | governance | 1 |  |
| `local-tools` | experimental | experimental | 1 | 是 |
| `normalize` | core | io_utility | 1 | 是 |
| `pbpk` | experimental | experimental | 1 |  |
| `perturb` | evidence | evidence_only | 1 |  |
| `pka` | sources | evidence_only | 1 |  |
| `prereg-status` | evidence | governance | 1 | 是 |
| `prospect` | evidence | evidence_only | 1 |  |
| `qaf` | decision | decision_chain | 1 | 是 |
| `rank` | decision | decision_chain | 1 |  |
| `regaloside-ab` | experimental | experimental | 1 |  |
| `release-check` | core | governance | 1 | 是 |
| `report` | core | io_utility | 1 |  |
| `reporting` | core | io_utility | 1 | 是 |
| `sar` | experimental | experimental | 1 |  |
| `selective` | decision | decision_chain | 1 |  |
| `sensitize` | evidence | evidence_only | 1 |  |
| `snapshot-summary` | core | io_utility | 1 |  |
| `snapshot-verify` | core | governance | 1 |  |
| `source-admit` | evidence | evidence_only | 1 | 是 |
| `source-health` | evidence | evidence_only | 1 |  |
| `source-rho` | evidence | evidence_only | 1 |  |
| `tier` | decision | decision_chain | 1 |  |
| `transfer` | evidence | evidence_only | 1 |  |
| `transport` | sources | evidence_only | 1 |  |
| `validate` | core | governance | 1 |  |
| `xeno-prep` | sources | evidence_only | 1 |  |

## 零调用命令（按层分组）

- **core**（3）：`merge`、`readback`、`saturate`
- **sources**（7）：`bt`、`cardiac`、`chembl`、`external`、`gut-micro`、`web`、`xeno-ingest`
- **decision**（2）：`reliab`、`trust`
- **evidence**（3）：`estimand`、`pred-shift`、`prereg-init`
- **experimental**（2）：`pbpk-qualify`、`pd`

## 使用这份表的纪律

1. 零调用 ≠ 可删：`evidence` 层命令是**门禁/审计**，平时不跑、审稿/发布时必跑。
2. 真正的删减依据是「6 个月零调用 + 非门禁层 + 非契约端点」，三者同时满足才降级为 experimental。
3. 建议核心集是**声明**：把 20 条之外的命令在文档里标 `peripheral`，不物理删除，保留可复算路径。
4. 任何删减都要在 CHANGELOG 里写「为什么删 + 怎么恢复」。
