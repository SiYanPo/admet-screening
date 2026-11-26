# 成本边界诊断方法论（c* 与分离原则）

> 来源：J Cheminform 投稿稿件《When does source-level evidence admission pay off?》的 Methods 与 Discussion。
> 落地：`adt/cost_boundary.py` + `adt cstar` 命令。
> 本文档的作用是让"为什么这样做"成为 skill 的长期资产，而不是只存在于论文里。

---

## 1. 要回答的问题

多源 ADMET 聚合里，**源级准入**（判断某个源在该端点/化学类上有没有资格投票）通常被当成"总是有利"的工程改进。这个文档给出一个可计算的判据，回答：

> 在什么弃权价格下，这个准入层才值得它的工程复杂度？

判据不是"准入是否提高 AUC"，而是"准入带来的效用增量在什么成本下转负"。

---

## 2. 关键区分：选择与拒绝

- **选择**：哪些源可以参与聚合（source-level admission）
- **拒绝**：系统是否弃权、覆盖率多少（abstention rule）

多数选择性预测框架把两者耦合在一个门控里（一个机制同时回答"信谁"和"要不要"）。本框架**分离**它们：准入在聚合前独立决定，覆盖率由另一套规则单独校准。

分离的代价是工程（两套判定、两套审计）；回报是两个决策可以各自定价。`c*` 就是给这个分离定价的量。

**为什么分离值得讨论**：耦合设计永远可用（总能退化成"只弃权、不裁定源"），所以问题不是"分离对不对"，而是"分离在这个价格下是否划算"——纯经济问题，`c*` 即答案。

---

## 3. 闭式解与适用条件

在固定决策规则下（分类阈值冻结，成本只进入评分、不改变决定集），效用为

    u(c) = -[ c_abst·n_abstain + c_fp_pass·n_FPpass + c_fp_fail·n_FPfail ] / n

错误项在微分时消失，故 `du/dc_abst = -(1-coverage)`。于是配对差 `Δu` 对弃权价格**严格线性**，拐点为

    c* = Δu(0) / (cov_baseline − cov_admission)

**这是代数恒等，不是拟合。** 因此：
- 无自由参数，不可能过拟合到某个期望结论；
- 恒等式自检：拟合斜率必须等于覆盖率差（实测偏差 ≤ 0.0002）；
- R² 是恒等的数值确认（实测 ≥ 0.9999999），不是拟合优度。

**适用边界**：仅当成本不进入决策规则时成立。在成本敏感阈值（`adt.cost_decision.pi_cost_sensitive`，S6 分支）下决定集随价格变动，线性破坏，c\* 必须数值求解。

---

## 4. 参考成本三元组怎么定

`c_ref = (c_false_PASS, c_false_FAIL, c_abstain)`。当前取值按**漏检后果是否可逆**分两类：

| 类别 | 三元组 | 端点 | 理由 |
|---|---|---|---|
| 安全与药物相互作用 | 5 : 1 : 0.5 | hERG、DILI、Ames、CYP 抑制/底物、PGP | 漏检导致患者暴露于不可逆风险（毒性或治疗失败），下游无法补救 |
| 药代/暴露 | 3 : 1 : 0.5 | BBB、生物利用度、肠吸收 | 漏检可由后续 PK 或配方实验纠正，代价较低 |

弃权统一 0.5 = false_PASS 的十分之一：代表"可补实验，但非免费"。

**重要**：这是判断，不是测量。文档与论文都明确"不声称这些值是某个项目应该用的值"。正因为单点选择本身可争议，交付物才应该是阈值 `c*` 而不是某个价格上的 verdict。

---

## 5. 跨基线：结论是否依赖"弱基线"

`c*` 依赖基线。同一批数据下：

| 端点 | vs 朴素投票(S1) | vs 共形校准(S3) |
|---|---|---|
| hERG | 0.2602 | 0.0613 |
| DILI | 0.5150 | 0.2279 |
| BBB_Martins | 0.2091 | 0.2073 |

**观察**：
1. 换成已经带覆盖保证的基线后，`c*` 大幅下降（hERG −76%）——即**相对于更强的基线，准入更难划算**，因为 S3 本身已弃权掉近一半化合物，再加一层的边际空间小。
2. **端点排序也变**：S1 基线 BBB < hERG < DILI；S3 基线 hERG < BBB < DILI。

第 2 点是诚实的负面发现：`c*` 的绝对值和排序都依赖比较对象，所以它不能当作端点的固有属性排序。这与"阈值是局部参数"的主张一致，但比论文正文的表述更强——正文主要报告 vs S1。

复现：

```bash
adt cstar --results out_keystone_v43/results.json \
    --endpoints hERG,DILI,BBB_Martins \
    --baseline S3_calibrated_conformal \
    --out-md references/CRITICAL_COST_VS_CONFORMAL.md \
    --out-csv out_sensitivity/critical_cost_vs_conformal.csv
```

---

## 6. 使用方式

```bash
# 对自己的结果文件定价（默认 vs 朴素投票）
adt cstar --results <results.json> --endpoints <ep1,ep2> \
    --out-md c.md --out-csv c.csv

# 对已带覆盖保证的基线定价
adt cstar ... --baseline S3_calibrated_conformal
```

输入要求：`results.json` 含 `per_run` 记录，每条有 `endpoint/strategy/cost_point/seed/utility/coverage`，且五个弃权价格（0.05/0.10/0.20/0.50/1.00）齐全。

---

## 7. 三条必读局限

1. **不是总体估计**：五到十三个端点仍是有限集合，`c*` 的跨端点范围是"下界"而非分布。
2. **不是模型无关**：`c*` 依赖预测器的归纳偏置（见 robustness 模块）。
3. **不是机制发现**：在固定规则配置下，它刻画的是"重定价"而非"决策随成本改变"。
