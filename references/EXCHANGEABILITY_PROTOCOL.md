# 交换性诊断与保形覆盖保证（EXCHANGEABILITY_PROTOCOL）

> 对应处方：**L2-1（D5 落地）/ 评审 §2.4（conformal 在时序 regime 下的覆盖保证）**。
> 状态：✅ 分箱诊断已实现（`adt/conformal.exchangeability_drift`，2026-10-31 落地并测试）；weighted conformal 对照通道 + 真实前瞻数据闭环待 P3/P6 数据。

## 1. 张力（D5 学术分歧）
材料在**官方时序切分**上做时间留出裁决（temporal holdout；原文档误称 prospective，2026-11-04 C08 已更正），同时又跑 **conformal 覆盖审计**。conformal 依赖**交换性**
（exchangeability）；时序切分天然违反交换性。材料必须二选一或显式声明：
- 给出时序设置下的**交换性诊断**，或
- 明确声明覆盖保证在时序 regime 下仅为**渐近/近似**，并引相应文献。

## 2. 做法（L2-1）
1. conformal 模块增加**按时间 / 结构分箱的覆盖漂移检验**：把测试集按训练/测试时间窗或
   结构簇分箱，报告每箱的 empirical coverage 与名义 1−α 的偏差。
2. 时序前瞻报告的覆盖**注明 regime 限定**（"仅在 i.i.d. 近似成立时保证"）。
3. 实现 **weighted conformal**（按时间衰减加权）作为**对照通道**，比较其覆盖与时序分箱表现。
4. 在方法学章节引用 conformal 在分布漂移/时序下的覆盖保证文献（评审 §11-2 建议旗舰检索）。

**命令骨架**（待实现）：
```bash
$PY -m adt.cli conformal --predictions out/measurements.csv --truth truth.csv \
    --alpha 0.2 --min-n 20 --stratify-by time_bin,structure_bin --outdir out   # 新增分箱
$PY -m adt.cli conformal-weighted --predictions out/measurements.csv --truth truth.csv \
    --alpha 0.2 --weight-decay 0.9 --outdir out_wc   # 对照通道
```
**验收**：覆盖漂移分箱图 + 时序 regime 声明 + weighted conformal 对照。状态：✅ `exchangeability_drift` 已实现并测试；weighted conformal 对照 + 真实前瞻数据闭环待 P3/P6 数据。

## 3. D5 关键文献（2024 旗舰检索，已核实）
时序/漂移 regime 下 conformal 覆盖保证的最新依据（评审 §11-2 要求旗舰检索）：

- **Han, E., Huang, C., Wang, K. (2024).** *Distribution-Free Predictive Inference under Unknown Temporal Drift.* — 提出 **Adaptive Rolling Window (ARW)**，在未知时变漂移下给出 **PAC（概率近似正确）覆盖保证**，并证明 oracle 不等式（性能逼近已知最优窗长）。直接支撑"时序前瞻下 conformal 覆盖仅为近似、需用滚动窗重标定"的论断。arXiv 2024。
- **Chen, B., Ren, Z., Cheng, L. (2024).** *Conformalized Time Series with Semantic Features (CT-SSF).* Advances in Neural Information Processing Systems (NeurIPS) 37: 121449–121474. — 在违反交换性假设的时序上，通过深度表征空间的语义特征动态学权重，在保持有效覆盖的同时显著收窄区间宽度。支撑"weighted/语义加权 conformal 对照"通道。
- **基础参照**：Vovk, Gammerman, Shafer 的 conformal prediction 经典框架（交换性下的有限样本覆盖保证）；标准 split/weighted conformal 覆盖证明见 `adt/conformal.py` 注释。

> 引用规范：D5 相关论断须在方法学章节同时给出 (a) 交换性诊断结果 与 (b) 上述时序覆盖保证文献之一，不得只声称"conformal 保证 1−α 覆盖"而不声明 regime 限定。
