# 去污染子集复核协议（DECONTAMINATION_PROTOCOL）

> 对应处方：**P6（C6 致命）/ L2-4（R-2 去污染阈值敏感性）**。
> 本文档为**方法学 + 待真实数据闭环**项（🟡）。数值不伪造，拿到数据即按此跑。

## 1. 问题（C6 致命）
F2 报告 OpenADMET 预测级训练污染 36.65% 且"全部端点 MAE(污染) < MAE(干净)"（**采信为工作假设，非既定事实**）。
若成立，则 F6 stacking 对比、前瞻 PASS 失败率等**绝对数值都建立在污染测试集上**，
须"去污染子集"复核后才可辩护。同时 U3 要求 36.65% 污染率口径在方法学附录完整定义。

## 2. 去污染方法（P6）
1. 以 **Tanimoto ≥ 0.7** 剔除与训练集邻居重合的测试分子（移除"污染邻居"）。
2. 在去污染子集上**重跑**：
   - F6 stacking 对比（Δ=+0.005 类结论）；
   - 前瞻 PASS 失败率（8.28% vs 45.27% 类结论）。
3. **两版数字并列报告**（污染全集 vs 去污染子集），**结论以去污染版为准**。
4. 在方法学附录完整定义 36.65% 污染率口径 + 复现脚本对照（U3）。

**命令骨架**（待实现 `out_ext/run_decontam_*.py`）：
```bash
# 1) 计算测试集与训练集的 Tanimoto 邻居重叠
$PY -m adt.cli neighbor-overlap --test out_ext/compounds_test.csv \
    --train out_ext/compounds_train.csv --threshold 0.7 --outdir out_ext
# 2) 在去污染子集上重跑 F6 / 前瞻
$PY -m adt.cli ablate --sources "..." --exclude out_ext/decontam_ids.csv \
    --truth out_ext/truth_test.csv --rules ... --outdir out_ext/decontam
$PY -m adt.cli prospect --measurements out_ext/measurements_decontam.csv \
    --truth out_ext/truth_decontam.csv --rules ... --outdir out_ext/decontam
```

## 3. L2-4：去污染阈值敏感性（R-2）
P6 用的 0.7 **未校准**，必须带阈值敏感性：**0.6 / 0.7 / 0.8 三档**清洗阈值下并列报告 F6 / 前瞻结论，
观察结论是否随阈值跳变。若三档结论一致 → 稳健；若跳变 → 结论须标 `threshold_critical`。

| 清洗阈值 | F6 Δ | 前瞻 PASS 失败率(去污染) | 结论稳定性 |
|---|---|---|---|
| Tanimoto ≥ 0.6 | 待跑 | 待跑 | 待评 |
| Tanimoto ≥ 0.7 | 待跑 | 待跑 | 待评 |
| Tanimoto ≥ 0.8 | 待跑 | 待跑 | 待评 |

**验收**：新 `out_ext/run_decontam_*.py` + 报告节；三档并列表进附录。状态：🟡 待真实数据闭环。
