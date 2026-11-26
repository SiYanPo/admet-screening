# 第二实现（self-audit replication）

## 这是什么 / 不是什么

| | 结论 |
|---|---|
| **是** | 一条**独立代码路径**：不 import `adt.*`、不 import `run_keystone`、不读 `out_keystone/results.json`，所有取值只来自 `../README.md` 的「实验设置」章节与 `../expected.json` 的指标定义。 |
| **是** | 对"规范可执行性"的检验：任何人拿着挑战包，能不能把流程搭出来。 |
| **不是** | 独立第三方复现。作者与原实现相同，且编写前已看过期望值。 |
| **不是** | 对"结论正确"的检验。它只能说明数字**可移植**，不能说明结论**可信**。 |

评审 C11 要求的"外部第二实现者"**仍未闭环**。本目录把状态从"完全没有第二实现"
推进到"规范已可执行 + 一条独立代码路径通过"，剩余缺口只有第三方本身。

## 这一步发现了什么（比结果更重要）

**发现 1：原挑战包的规范不可执行（已修）**

原 `spec` 写的是「切分脚本与种子列表见 `run_keystone.py`」——而包内**不提供**该文件。
这等于要求第二实现者去读原实现，那是照抄，不是复现。

修法有两层：
- `run_replication_pack.py` 把 spec 写成**自足**的描述（数据切分规则 / 三个源的特征与超参 /
  校准方式 / 域判据 / 阈值规则 / 策略定义 / 代价公式 / 种子）；
- `adt/replication.py` 加了**反循环依赖闸门**：spec 的序列化文本里出现 `.py` 文件名
  （`score.py` 除外）就 `raise`，拒绝出包。这样"指向源码"的包以后出不来。

**发现 2：包里的「数据快照」与本实验无关**

`expected.json` 的 `snapshots` 列的是 `admet_ai / admetlab3 / chembl / protox3 / biotransformer`
——那是 run6 多源实跑的产物快照，**不是** keystone 实验用的 TDC 公开数据。
本实现改为打印 TDC 数据集指纹（对 `SMILES\tlabel` 逐行 sha256），
并已在 README 的「实验设置」里要求提交方一并上报，用于核对"是否同一份数据"：

| endpoint | train_val 指纹（前 16 位） | test 指纹（前 16 位） |
|---|---|---|
| hERG | `f7701a87fc1aac85` | `635c90e14f252dff` |
| DILI | `229abfcb6ef77a7f` | `275b6895e40e5ef5` |
| BBB_Martins | `0bfbe72ab2601cbc` | `0c6bf418662e6c4d` |

**发现 3：`Descriptors.MaxPartialCharge` 是版本依赖的**

规范把第 10 个描述符写成 `MaxPartialCharge`，但该函数在部分 RDKit 版本不存在。
原实现用 `hasattr` 静默回退 0；本实现同样回退，但**记录为规范缺口**——
正确做法是规范里写明"若不存在则该维置 0"，否则两个人会得到不同的特征矩阵。

## 怎么跑

```bash
python replication/second_implementer/impl.py --seeds 20
python replication/score.py replication/second_implementer/submission.json
```

首次运行约 3–5 分钟（3 端点 × 20 种子 × 2 个 RF(300 树)）。

## 判定规则（不要放宽）

- `counted=true` 的 5 项**全部**落容差内 → `all_pass=true`；
- 全部同时落在容差 5% 内 → 触发 `suspicious_identical`，**视为可疑而非优秀**
  （真正独立的实现不可能把噪声级波动复现到这个精度）；
- `risk_decided` 因容差/量级 = 0.98 被判为 INFO，不参与判定（它在任何 0–0.2 之间都算"通过"）。

## 已知局限（不得省略）

1. 作者同源 + 已见期望值 → 存在"照着答案写实现"的风险。缓解手段只有一条：
   **首次成功运行的结果即提交，未据期望值调参**；若未来有第三方，本条自动失效。
2. 只覆盖 6 个主数字，不覆盖 cost sweep、gate audit、MMP 等扩展分析。
3. 数据侧只核对指纹，未核对 TDC 包版本（`tdc` 库自身的缓存格式可能变）。
