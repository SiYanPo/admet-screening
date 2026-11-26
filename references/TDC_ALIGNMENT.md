# TDC 公开基准对齐（TDC_ALIGNMENT）

> 对应处方：**L2-2**。状态：**✅ 已用真实数据闭环**（2026-10-31）。
> 真实结果见 `out_ext/tdc/REAL_TDC_CLOSURE.md`：hERG（AUC-ROC 0.792 / AURC 0.227 / 交换性无漂移）
> 与 Caco2_Wang（MAE 0.4128→0.3883 / 近重复泄漏率 17.0% / 去污染三档 41.5·32.1·19.9%）。
>
> **2026-11-01 种子裁决（`run_p6_seed_ci.py`，20 种子配对）**：泄漏增益 Δ 中位 **−0.0228**，
> 95%CI **[−0.0274, −0.0206]** 完全 <0 → **原结论成立**，不属于种子噪声。
> 但单次点估计不可直接引用：seed0 的绝对 MAE（0.4128 / 0.3883）比 20 种子中位数
> （0.3964 / 0.3730）都高约 0.016，说明历史单点对**绝对水平**是悲观的、对**差值**无偏。
> 结论：差值可用，绝对 MAE 必须报中位数 [IQR]。
>
> **环境须知（以实测为准，勿凭旧记忆）**：本机主环境 numpy **2.5.4** 下，已安装的 `pytdc`
> **实测可导入 `BenchmarkGroup` 并完成 TDC 数据拉取与基准运行**——早期"pytdc 必须 numpy<2、
> 严禁装主环境"的说法**与本版不符**。但不同 pytdc 版本的依赖约束不同，**装之前必须先 dry-run**
> （`pip install --dry-run pytdc`）确认不会把 numpy 降级；若确认会降级，再走下方隔离 venv。

## 1. 目的
把框架自己的数字与 **TDC ADMET benchmark 官方协议 / leaderboard** 脱钩报告，
以第三方可对照的数字证明框架的横向有效性，而非"自说自话"。

## 2. 做法
1. 以 **TDC ADMET benchmark** 官方划分（官方 train/valid/test 或官方 CV）跑框架的准入层，
   产出可与 leaderboard 对照的 AUROC/AUPRC/coverage 数字。
2. **框架数字与 leaderboard 数字脱钩报告**：明确区分
   - "本框架在 TDC 官方协议上的绝对表现"（横向对照）；
   - "本框架在自有化学类上的准入增益"（纵向对照）。
   二者不得混为一谈（避免把纵向增益误读为横向 SOTA）。
3. G3 外部工具横评改为在 TDC 协议上跑成**公开可复现对照**（评审 §9-3 推广建议）。

**隔离环境安装（官方源 PyPI，勿装进主环境）**：
```bash
# 1) 建隔离 venv（Python 3.10，pytdc 兼容最佳）
python -m venv .venv_tdc && .venv_tdc/Scripts/activate   # Windows
#   或 source .venv_tdc/bin/activate                       # Linux/macOS
# 2) 官方源安装 pytdc（含 TDC ADMET benchmark 官方划分）
pip install -i https://pypi.org/simple pytdc
# 3) 在该隔离环境内跑框架的 TDC 协议对齐（复用本 skill 的 benchmark 逻辑，仅载入层换 tdc）
python -m adt.cli benchmark --predictions out_ext/measurements_tdc.csv \
    --truth-format tdc --tdc-endpoint DILI --official-split --outdir out_ext/tdc
```
> 注：本机主环境 numpy 2.5.4 下 **75/75 测试全绿**，且现有 pytdc 实测可直接使用（见文件头）；
> 隔离 venv 是**保底方案**：一旦 dry-run 显示会降 numpy，就用它，避免污染主环境回归基线。
> TDC 对齐产物（`out_ext/tdc/`）单独提交，不与主环境依赖混用。

**TDC ADMET benchmark 官方分组（横向对照用，节选）**：
`Caco2_Wang`、`HIA_Hou`、`Pgp_Broccatelli`、`Bioavailability_Ma`、`BBB_Martins`、
`PPB_Bound`、`CYP2C19_Veith`、`CYP2D6_Veith`、`CYP3A4_Veith`、`CYP1A2_Veith`、
`CYP2C9_Veith`、`CYP2C9_Substrate_CarbonMangels`、`CYP3A4_Substrate_CarbonMangels`、
`Half_Life_Obach`、`Clearance_Hepatocyte_AZ`、`DILI`、`Skin_Reaction`、`Carcinogens_Lagunin`、
`Clintox`、`hERG`、`AMES`、`pKa`、`VDSSTrafficLight`、`B3P` 等（以 `tdc.benchmark_group('ADMET_Group')` 实际返回为准）。

**验收**：TDC 官方协议下的可对照数字表；框架 vs leaderboard 脱钩声明。状态：🟡 待隔离 TDC 环境跑通（命令与上表已就绪）。
