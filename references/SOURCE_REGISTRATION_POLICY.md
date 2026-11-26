# 源注册与纳入/排除预注册政策（SOURCE_REGISTRATION_POLICY）

> 对应处方：**P11（C12 确认偏差通道，阻断项）/ L2-3（R-4 ρ 元数据一等公民）**。
> P11 含可立即落地的预注册机制（部分 ✅）；L2-3 的 registry 字段扩展为方法学（🟡 待数据回填）。

## 1. P11：源纳入/排除预注册化（C12 高，阻断项）
**问题**：mppb 因 ρ 符号翻转被**事后排除**——以不稳健统计做纳入/排除决策，系统性抬高"矩阵内一致性"叙事
（C12 确认偏差通道）。

**处方（可立即落地）**：
1. **先定标准、后看数据**：独立性矩阵的源纳入/排除标准**写入预注册**（`prereg.py`，沿用 G4 的
   freeze/verify(sha256)/supersede/diff 机制），不得在看数据后临时增删。
2. **已发生的 mppb 排除**：按 supersede 机制补留痕（原决策 + 新评估结论 + 触发重评的统计量），
   并在矩阵脚注声明"全部纳入/排除决策的登记位置"。
3. 任何源的新增/剔除都生成一条 `prereg` 记录，报告脚注引用其 hash。

**当前落地**：`adt/manifest.py` 已提供 run manifest（预注册判据版本）；P11 要求把"源纳入/排除标准"
也纳入同一预注册链。状态：🟡 待把 mppb 排除决策补 supersede 留痕（需在评审材料侧回填，非代码阻断）。

## 2. L2-3：ρ 元数据登记为 registry 一等公民（R-4）
**问题**：ρ 估计质量未解决，`source_registry` 未把 ρ 当一等元数据。

**处方**：`02_source_registry.yaml` 的每个源增加字段：
```yaml
rho_metadata:            # 一等公民元数据（L2-3）
  per_endpoint:          # 端点级 ρ 与 CI（禁止跨端点共享）
    herg: {rho: -0.574, ci_lo: -0.78, ci_hi: -0.30, n: 14, dataset: cinnamon_glycoside, version: "2026-10"}
    dili: {rho: 0.12, ci_lo: -0.35, ci_hi: 0.55, n: 14, dataset: cinnamon_glycoside, version: "2026-10"}
  expiry: "2026-12-31"  # 过期自动回落保守值
```
- **过期 ρ 自动回落保守值**（如 ρ=0 或按 worst-case 收缩）并**标注**，不得静默沿用陈旧 ρ。
- `source_rho.compare` 的输出应直接写回该字段（待接 `manifest` 链路）。

**验收**：registry 含 ρ/CI/端点/数据集/版本/过期字段；过期回落逻辑 + 标注。状态：🟡 字段 schema 已定义，待逐源回填真实 ρ/CI（数据依赖）。
