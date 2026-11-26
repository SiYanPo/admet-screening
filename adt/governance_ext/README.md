# adt.governance_ext（实验性治理扩展层）

这是从 `adt_proto` 原型移植进本 skill 的**治理/审计扩展层**，不是主决策链的
默认入口。它解决的是"证据可信度"而非"预测精度"：

| 模块 | 作用 | 状态 |
|---|---|---|
| `zk_audit.py` | SMILES+salt 哈希承诺 + Merkle 盲化审计 | 实验 |
| `dependency_guard.py` | rdkit 版本绑定断言 + 黄金快照 + 自动差异评估 | 实验 |
| `chained_exemption.py` | 首席科学家带镣铐豁免 + 哈希链 + T0 锁 | 实验 |
| `regulatory_seal.py` | 输入/源码/环境/电子签名联合封印 + 审计链 | 实验 |
| `stratified_monitor.py` | 骨架/药效团分层锚点 + CUSUM + 算子库 | 实验 |
| `incremental_recert.py` | 知识更新批量静默重跑 + 冲突报警 | 实验 |
| `trust_inheritance.py` | lineage_id 派生账本 + 信任继承封顶 | 实验 |
| `uncertainty_quantification.py` | samples/ensemble + kNN 代理 + 偏移 coverage | 实验 |
| `split_audit.py` | random/scaffold/cluster/time 分割敏感性 | 实验 |
| `ood_monotonicity.py` | 偏移递增时 UNDETERMINED/T0/coverage 单调性 | 实验 |
| `active_review.py` | 10%-15% 探索配额 + TrustGuard + 动态配额 | 实验 |
| 其余 | 断言账本 / 变异 / CI / 水印 / 并发 / 锚点 / 算力指令 | 实验 |

## 为什么不直接接进 `adt.cli`

主 CLI 已有 100+ 命令、4.7k 行；本层尚未经过真实药企数据与真实监管审查，
直接接线会把"实验性证据"混进生产结论。正确顺序是：

1. 用 `tests/test_governance_ext.py` 做机制回归；
2. 用真实 endpoint 数据跑 `split_audit` / `ood_monotonicity` / UQ 标定；
3. 通过科学审查后，再以 `adt gov-*` 子命令逐条接入，并保留 SHADOW 模式。

## 最小自检

```bash
python -m pytest tests/test_governance_ext.py -q
```
