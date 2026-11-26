# 证据 DAG（自动生成）

> 生成器：`tools/build_evidence_dag.py`；源：`adt/command_roles.py`
> 源码哈希：`753c30f0ed265ceb`
> 规模：78 节点 / 50 边；分层 {'core': 14, 'sources': 13, 'decision': 13, 'evidence': 31, 'experimental': 7}
> 状态：`active`（由注册表重算，不依赖人工维护）

## 层间含义

| 层 | 含义 | 命令数 |
|---|---|---|
| `core` | 输入规整与基础度量（不产生结论） | 14 |
| `sources` | 外部证据源接入（产物受许可证与可达性约束） | 13 |
| `decision` | 决策层：准入/组合/弃权（结论在此产生） | 13 |
| `evidence` | 证据治理：门禁、预注册、manifest、审计 | 31 |
| `experimental` | 实验层：不进主结论链（SHADOW） | 7 |

## 契约边（按层对聚合，完整清单见 EVIDENCE_DAG.yaml）

| 源层 → 目标层 | 边数 | 代表契约 |
|---|---|---|
| sources → evidence | 12 | `measurement` |
| sources → decision | 12 | `measurement` |
| core → sources | 10 | `compound` |
| core → experimental | 5 | `compound` |
| decision → decision | 4 | `reliability` |
| evidence → evidence | 2 | `conformal` |
| core → evidence | 1 | `compound` |
| core → decision | 1 | `compound` |
| experimental → experimental | 1 | `pbpk` |
| decision → evidence | 1 | `abstention` |
| core → core | 1 | `snapshot` |

## 边界声明（必须随图一起引用）

1. 契约级依赖不等于统计依赖：本 DAG 说明 A 的产物是 B 的合法输入，不说明 A 对 B 的结论有贡献；贡献判定见 adt/ablation.py 的同覆盖判据。
2. `evidence_role` 为 `io_utility` / `governance` / `experimental` 的命令**不**
   授予结论资格；其产物可作输入，但不得被引用为证据。
3. 本图不含数据资产（见 `DATA_MANIFEST.json`）与外部服务可用性（见 `env-audit`）。
4. 分层是**治理标记**，不是调用顺序；实际执行顺序由 CLI 契约与 `ADT_ENFORCE_ROLES` 决定。
