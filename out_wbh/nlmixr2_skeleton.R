# nlmixr2 骨架 —— validated_against_tool = nlmixr2_fit_passed
# 实测环境：R 4.5.3 + nlmixr2 5.0.0 + rxode2 5.0.2（conda-forge，Windows）
# 实测结果：11228 行 / 28 受试者 / FOCEI 60 s 收敛，"Normal exit from bobyqa"
# 安装：install.packages("nlmixr2")（运行时编译模型还需要 Rtools）
library(nlmixr2)

# 两个由实测暴露、必须写进报告的前提（不要把这份结果当常规 popPK）：
# 1) 本数据集的 ID = 化合物，不是人体受试者。eta 估出来的是"化合物间变异"，
#    不得当作 IIV/BSV 报告。实测 eta 收缩为负（-72% / -281%）正是这个原因。
# 2) 实测辨识性只有 V：V=1433 L（RSE 3.8%，95%CI 1330–1540）可估；
#    CL / ka / F 的 95%CI 跨四个数量级（RSE 3.6e3% / 2.0e6%），是 flip-flop
#    与"曲线几乎无噪声"共同导致的不可辨识。这些数字不要当估计结果写进报告。
#    另：曲线在 12–30 h 已衰减到 0，后续时点是 ODE 数值零，导出时已置 MDV=1；
#    真正做 BLQ 需 CENS=1 的删失似然，本骨架不假装能处理。

# 初值由 pk_initials 从 C(t) 推得（2 个化合物取中位数）：V0=AMT/Cmax、ka0=1/Tmax、CL0=λz·V0、addSd=0.05·median(C)。
# 这些是初值不是估计结果；{'v_init': 1568.3, 'ka_init': 0.833, 'cl_init': 683.12, 'add_sd': 0.0044, 'n_compounds': 2, 'dose_mg': 100.0}

f <- function() {
  ini({
    tcl   <- 683.12      # L/h
    tv    <- 1568.3       # L
    tka   <- 0.833      # 1/h
    tf    <- 1.0       # 生物利用度（口服单次给药下与 V 不可同时辨识 → 建议 fix(1.0)）
    addSd <- 0.0044       # 加性误差（浓度单位）
    eta_cl ~ 0.2
    eta_v  ~ 0.2
  })
  model({
    cl <- tcl * exp(eta_cl)
    v  <- tv  * exp(eta_v)
    ka <- tka
    f  <- tf
    d/dt(depot)      <- -ka * depot
    d/dt(central)    <-  ka * depot - (cl / v) * central
    cp <- central / v
    cp ~ add(addSd)
  })
}

# 读入 adt.interop 导出的数据集（UTF-8 无 BOM；给药 CMT=1 胃肠道 / 观测 CMT=2 中央室）
# 若用 --obs-cmt / --dose-cmt 改过腔号，以 nonmem_dataset.csv 的 CMT 列实际值为准。
d <- read.csv("C:/Users/huawei/.workbuddy/skills/admet-screening/out_wbh/nonmem_dataset.csv")

fit <- nlmixr2(f, d, est = "focei", control = foceiControl(print = 0))
print(fit)

# PD（Emax）阶段：把个体 PK 参数代入 Hill 模型，或改用 nlmixr2 的 PD compartment
# Ec50 / Emax 初值须来自体外实测；不要用 ADMET 预测值直接当 Ec50。
