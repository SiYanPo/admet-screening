### 表 1 · C9 统一分数口径（同 pred、同 score，只差弃权规则）

| 端点 | 策略 | coverage | risk_decided | 同覆盖率前沿 risk | efficiency_gap | 95%CI | utility |
|---|---|---|---|---|---|---|---|
| BBB_Martins | S1_naive_majority | 1.000 | 0.117 | 0.117 | +0.000 | [+0.000, +0.000] | -0.164 |
| BBB_Martins | S2_ad_guard | 0.527 | 0.107 | 0.034 | +0.073 | [+0.069, +0.082] | -0.320 |
| BBB_Martins | S3_calibrated_conformal | 0.238 | 0.013 | 0.017 | -0.000 | [-0.001, -0.000] | -0.385 |
| BBB_Martins | S4_full_admission | 0.132 | 0.023 | 0.020 | -0.000 | [-0.001, +0.017] | -0.437 |
| DILI | S1_naive_majority | 1.000 | 0.208 | 0.208 | +0.000 | [+0.000, +0.000] | -0.385 |
| DILI | S2_ad_guard | 0.281 | 0.093 | 0.079 | +0.016 | [-0.005, +0.016] | -0.391 |
| DILI | S3_calibrated_conformal | 0.849 | 0.147 | 0.148 | +0.000 | [-0.004, +0.002] | -0.286 |
| DILI | S4_full_admission | 0.208 | 0.049 | 0.049 | -0.001 | [-0.001, +0.000] | -0.406 |
| hERG | S1_naive_majority | 1.000 | 0.174 | 0.174 | +0.000 | [+0.000, +0.000] | -0.265 |
| hERG | S2_ad_guard | 0.644 | 0.165 | 0.098 | +0.067 | [+0.063, +0.074] | -0.314 |
| hERG | S3_calibrated_conformal | 0.644 | 0.086 | 0.094 | -0.007 | [-0.010, -0.003] | -0.284 |
| hERG | S4_full_admission | 0.235 | 0.118 | 0.065 | +0.061 | [+0.033, +0.071] | -0.443 |

统一口径 AURC（越低越好）与域内/域外错误率：

| 端点 | AURC | 域内 risk | 域外 risk | 域外样本数 |
|---|---|---|---|---|
| BBB_Martins | 0.0477 | 0.107 | 0.130 | 192 |
| DILI | 0.1008 | 0.093 | 0.254 | 69 |
| hERG | 0.1029 | 0.165 | 0.192 | 47 |

### 表 2 · A1 四种权重方案（cal 上估权重，test 上打分）

| 端点 | 方案 | log-loss | Brier | AUC | acc@0.5 | 权重（中位数） |
|---|---|---|---|---|---|---|
| BBB_Martins | equal | 0.3029 | 0.0893 | 0.8932 | 0.8830 | [0.333, 0.333, 0.333] |
| BBB_Martins | shrink | 0.3039 | 0.0897 | 0.8926 | 0.8830 | [0.326, 0.349, 0.326] |
| BBB_Martins | bma | 0.2981 | 0.0879 | 0.8954 | 0.8867 | [0.382, 0.239, 0.382] |
| BBB_Martins | diversity | 0.3008 | 0.0887 | 0.8942 | 0.8855 | [0.350, 0.296, 0.354] |
| DILI | equal | 0.4571 | 0.1465 | 0.8916 | 0.7917 | [0.333, 0.333, 0.333] |
| DILI | shrink | 0.4572 | 0.1466 | 0.8909 | 0.7917 | [0.330, 0.342, 0.329] |
| DILI | bma | 0.4544 | 0.1453 | 0.8940 | 0.7969 | [0.330, 0.319, 0.354] |
| DILI | diversity | 0.4571 | 0.1472 | 0.8921 | 0.7917 | [0.377, 0.272, 0.352] |
| hERG | equal | 0.4361 | 0.1356 | 0.8351 | 0.8258 | [0.333, 0.333, 0.333] |
| hERG | shrink | 0.4359 | 0.1356 | 0.8346 | 0.8258 | [0.328, 0.341, 0.331] |
| hERG | bma | 0.4358 | 0.1351 | 0.8302 | 0.8333 | [0.390, 0.343, 0.272] |
| hERG | diversity | 0.4357 | 0.1356 | 0.8346 | 0.8258 | [0.333, 0.337, 0.329] |

配对差（同种子，vs equal）：

| 端点 | 比较 | Δlog-loss | 95%CI | 显著 | 方向 |
|---|---|---|---|---|---|
| BBB_Martins | shrink - equal | +0.00090 | [+0.00090, +0.00100] | 是 | worse |
| BBB_Martins | bma - equal | -0.00450 | [-0.00500, -0.00410] | 是 | better |
| BBB_Martins | diversity - equal | -0.00200 | [-0.00210, -0.00190] | 是 | better |
| DILI | shrink - equal | +0.00020 | [+0.00010, +0.00030] | 是 | worse |
| DILI | bma - equal | -0.00050 | [-0.00180, +0.00020] | 否 | better |
| DILI | diversity - equal | +0.00040 | [-0.00040, +0.00090] | 否 | worse |
| hERG | shrink - equal | -0.00020 | [-0.00030, -0.00020] | 是 | better |
| hERG | bma - equal | +0.00000 | [-0.00070, +0.00050] | 否 | better |
| hERG | diversity - equal | -0.00020 | [-0.00020, -0.00010] | 是 | better |

### 表 3 · A4 基线强度外推（只把最弱的 ridge 换成 HGB，其余不变）

| 端点 | 变体 | U(S1) | U(S4) | Δutility(S4−S1) | 95%CI | 显著 | 方向 |
|---|---|---|---|---|---|---|---|
| BBB_Martins | weak3 | -0.1638 | -0.4372 | -0.2771 | [-0.2826, -0.2697] | 是 | worse |
| BBB_Martins | strong_swap | -0.1761 | -0.3892 | -0.2155 | [-0.2211, -0.2094] | 是 | worse |
| DILI | weak3 | -0.3854 | -0.4062 | -0.0208 | [-0.0521, +0.0078] | 否 | worse |
| DILI | strong_swap | -0.3281 | -0.4167 | -0.0938 | [-0.1667, -0.0651] | 是 | worse |
| hERG | weak3 | -0.2652 | -0.4432 | -0.1799 | [-0.1875, -0.1705] | 是 | worse |
| hERG | strong_swap | -0.2576 | -0.3655 | -0.1023 | [-0.1155, -0.0985] | 是 | worse |

| 端点 | 结论翻转（weak3 与 strong_swap 方向相反） | 单源校准 AUC |
|---|---|---|
| BBB_Martins | 否 | rf_morgan=0.869, ridge_desc=0.804, rf_maccs=0.899, strong_hgb=0.907 |
| DILI | 否 | rf_morgan=0.815, ridge_desc=0.842, rf_maccs=0.886, strong_hgb=0.909 |
| hERG | 否 | rf_morgan=0.778, ridge_desc=0.740, rf_maccs=0.812, strong_hgb=0.763 |

### 表 4 · C6 误差方差分解（成因的行为层代理）

| 端点 | 源对 | 总相关 corr(p_i,p_j) | 误差相关 r_e | 共享误差占比 | 判定 |
|---|---|---|---|---|---|
| BBB_Martins | rf_morgan|ridge_desc | +0.6471 | +0.7970 | 0.442 | shared_errors |
| BBB_Martins | rf_morgan|rf_maccs | +0.8894 | +0.9102 | 0.476 | shared_errors |
| BBB_Martins | ridge_desc|rf_maccs | +0.6890 | +0.8212 | 0.448 | shared_errors |
| DILI | rf_morgan|ridge_desc | +0.6343 | +0.8125 | 0.448 | shared_errors |
| DILI | rf_morgan|rf_maccs | +0.6877 | +0.8425 | 0.456 | shared_errors |
| DILI | ridge_desc|rf_maccs | +0.6634 | +0.8149 | 0.448 | shared_errors |
| hERG | rf_morgan|ridge_desc | +0.7410 | +0.8877 | 0.470 | shared_errors |
| hERG | rf_morgan|rf_maccs | +0.7474 | +0.8899 | 0.471 | shared_errors |
| hERG | ridge_desc|rf_maccs | +0.6369 | +0.8770 | 0.467 | shared_errors |

