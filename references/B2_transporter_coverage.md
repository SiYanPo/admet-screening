# B2：BBB 双层机制的转运体先验覆盖度（黑榜 B2 / O5-D2 量化结果）

> 生成日期：2026-11-03
> 对应红黑榜条目：`references/REVIEW_2026-11-03_RED_BLACK.md` §2 B2、§4 B2
> 对应台账：`references/REVIEW_2026-11-03_LEDGER.md` O5-D2

## 0. 一句话结论

**本 skill 的转运体先验在"结构判定"层只实现了 1 个转运体（OATP2B1），且该规则是黄酮类专属骨架；**
**对 BBB_Martins 这套 406 个 CNS 药物，OATP2B1 先验几乎不触发。**
因此 `adt/bbb.py` 里"被动 × 外排(P-gp/BCRP) × 摄取(GLUT1/SGLT1/OATP2B1)"的**三通道决议是叙事级，不是机制级**——
三层里有两层（P-gp、BCRP、GLUT1、SGLT1、OATP1A2、LAT1…）**没有任何 moiety 规则支撑**。

建议：**"BBB 双层机制"表述降级为"仅覆盖 OATP2B1 分支（且限于黄酮类骨架，对通用 CNS 集几乎不触发）"**，
直到为 P-gp/BCRP/OATP1A2/LAT1/GLUT1 补上可执行的 moiety 规则或实验回填端点。

---

## 1. 数据来源（全部实测可达 / 已落盘）

| 角色 | 来源 | 状态 |
|---|---|---|
| 分子（406 个 SMILES） | `out_ext/tdc_cache/admet_group/bbb_martins/test.csv`（实为 `Drug_ID, Drug, Y`——`Drug` 列即 SMILES） | 本机已缓存，**无需外网**（原以为要 fetch，省了） |
| 现有先验 | `references/transporter_priors.yaml` v2.5.0 | 本机 |
| 分母转运体集合 | KEGG BRITE 02000（Transporters 分类，总页实测可达）+ UniProt REST | UniProt 实测返回 ABCB1/ABCG2/SLCO1A2/SLC2A1/SLC7A5/SLC29A1 真实条目 |
| 执行脚本 | `run_b2_coverage.py`（rdkit 本地跑 406 SMILES） | 本机，可复算 |

---

## 2. 方法

1. 用 rdkit 对 406 个 SMILES 套用 `transporter_priors.yaml` 中**真正做结构判定**的 chemotype SMARTS，
   统计每个 chemotype 命中数、命中任意规则的分子数。
2. **分母代理**：采用 yaml 自己的 `high_tpsa` 规则（TPSA>140 ⇒ 被动渗透不足、转运体主导），
   作为"应被转运体机制解释的分子"的**保守下界**。
   - 诚实说明：P-gp 外排、OATP1A2 摄取等对低极性分子同样起作用，真实相关集远大于 TPSA>140 子集；
     故下文 7.1% 是**上限式保守估计**，真实覆盖度更低。
3. **转运体级**：列出 canonical 人类 BBB 转运体集合（KEGG BRITE 02000 + UniProt 锚定的 18 个代表），
   与本 skill 实际有 moiety 规则的转运体对比。

---

## 3. 结果 A — 每个 chemotype SMARTS 在 406 分子中的命中数

| chemotype | SMARTS | 命中 / 406 |
|---|---|---|
| glucopyranoside（吡喃葡萄糖苷，OATP2B1 代理） | `OC1OC(CO)C(O)C(O)C1O` | **2** |
| cinnamoyl_ester（肉桂酰/咖啡酰酯） | `O=C(O)C=Cc1ccccc1` | 0 |
| catechol（邻苯二酚） | `[OH1]c1ccccc1[OH1]` | 0 |
| guaiacyl（愈创木基 4-OH-3-OMe，通用芳环片段） | `[OH1]c1ccccc1OC` | 7 |

> 注：guaiacyl 只是通用酚-甲氧基片段，并非经验证转运体底物；glucopyranoside 2 例才是 OATP2B1 先验最接近的结构代理。

## 4. 结果 B — 分子级覆盖度

- 分母（TPSA>140，转运体主导）：**28 / 406 = 6.9%**
- 命中任意 chemotype 规则：8 / 406 = 2.0%
- 含糖/吡喃糖骨架（OATP2B1 代理）：**2 / 406 = 0.5%**
- **OATP2B1 先验能解释"转运体主导"分子的：2 / 28 = 7.1%（保守上限）**

## 5. 结果 C — 转运体级覆盖度

- canonical 人类 BBB 相关转运体（代表集，KEGG BRITE 02000 + UniProt 锚定）：**18 个**
  - 外排（ABC）：ABCB1/P-gp、ABCG2/BCRP、ABCC1/MRP1、ABCC2/MRP2、ABCC4/MRP4、ABCC5/MRP5
  - 摄取（SLC, BBB）：OATP1A2、OATP2B1、OAT1、OAT3、OCT1、OCT2、ENT1、ENT2、LAT1、GLUT1、MCT1、PEPT2
- 本 skill **有 moiety 规则（结构判定）的转运体：仅 `OATP2B1`**
- yaml chemotype 文字**提及**但无结构规则的转运体：P-gp、BCRP/MRP2、GLUT1、SGLT1、OATP1A2/1B3、LAT/MCT
- **转运体级覆盖率（有结构规则）：1 / 18 ≈ 5.6%**

## 6. 结果 D — 三通道决议的机制落点

`adt/bbb.py` 把 BBB 重述为 `passive(closed) × efflux(P-gp/BCRP) × uptake(OATP1A2/LAT1/GLUT1)`。
逐项核对是否有**可执行的 moiety 规则**：

| 通道 | 命名于 bbb.py | 有 moiety 规则？ | 落点 |
|---|---|---|---|
| 被动 | SAR 预筛 | — | 独立通道，OK |
| 外排 P-gp/BCRP | ✅ | ⚠️ **启发式骨架**（v4.11，`adt/efflux_heuristic.py`，共识药效团，非实测） | 有结构依据的待验证假设 |
| 摄取 OATP1A2 / LAT1 / GLUT1 | ✅ | ⚠️ **启发式骨架**（v4.12，`adt/uptake_heuristic.py`，共识药效团，非实测） | 有结构依据的待验证假设 |
| 摄取 OATP2B1 | ✅ | ⚠️ 仅黄酮专属 chemotype，406 个 CNS 分子几乎不命中（2 例糖） | 几乎不触发（属肠侧 Fa 通道） |
| 摄取 SGLT1 | ✅ | ❌ 无（且按生物学保真，SGLT1 在 BBB 内皮无功能性表达，属肠侧 Fa 通道，不纳入 BBB 侧结构规则） | 仅叙事 |

→ **三层决议现已全部从"纯叙事"升级为"有结构依据的待验证假设"（被动层 + 外排启发式 + 摄取启发式）；**
**但仍均非量化级**——所有命中必须经指定实验验证、且不得进 reliab 计票。量化级需对 P-gp/BCRP/OATP1A2/LAT1 做实验回填端点（role=reference）。

---

## 7. 降级判定与后续动作

- **表述降级**：所有出现"BBB 双层机制 / 三通道决议"之处（SKILL.md、bbb.py docstring、`09_reliability_landscape.md` 等）
  改为"**双层机制框架（被动层 + 外排 P-gp/BCRP 启发式 + 摄取 OATP1A2/LAT1/GLUT1 启发式，均非实测、须验证；
  OATP2B1 仅黄酮专属且对 CNS 集几乎不触发，SGLT1 为肠侧 Fa 通道不纳入 BBB 侧）**"。
- **补规则进度**（按对 BBB 透穿的解释力）：
  1. **P-gp / BCRP 外排（主导负项，CNS 药物最常见）→ ✅ 已补启发式骨架（v4.11）**：
     `adt/efflux_heuristic.py` 用 P-gp 共识药效团（Seelig 1998 HBA 距离模型 + Penzotti/Crivori 2002/2006
     ADMET Predictor 药效团）近似评估底物 plausibility，明确标注**启发式、非实测、须 Caco-2 ± verapamil/elacridar
     验证、不得进 reliab 计票**。这是把外排通道从"纯叙事"升级为"有结构依据的待验证假设"——**不是量化级**。
  2. **OATP1A2 / LAT1 / GLUT1 摄取（脑暴露正项）→ ✅ 已补启发式骨架（v4.12）**：
     `adt/uptake_heuristic.py` 用 OATP1A2 大体积有机阴离子、LAT1 大中性 L-氨基酸、GLUT1 仅游离单糖的共识药效团
     近似评估 plausibility，明确标注**启发式、非实测、须经过表达细胞摄取 ± 竞争抑制剂验证、不得进 reliab 计票**；
     SGLT1 因在 BBB 内皮无功能性表达（属肠侧 Fa 通道）**不含结构规则**。这是把摄取通道从"纯叙事"升级为
     "有结构依据的待验证假设"——**不是量化级**。
  3. 上述完成前，`three_channel_resolution` 仍不得给人"已机制化/已量化"的印象。
- **不要做的事**：不得用"双层机制"暗示任一通道已被本 skill 量化——目前它们都只是"待验证假设"。

---

## 8. 诚实性声明（方法局限）

- 本条覆盖度是**结构先验覆盖度**，不是实验验证；转运体底物结构识别本身可靠性有限（P-gp 共识药效团尤其粗）。
- 分母"18 个"是代表集，非穷举；穷举会略增，但 1/N 的量级结论不变。
- 分子级 7.1% 是**保守上限**（因 TPSA>140 分母偏窄）；按机制相关集 ~全 406 计，真实覆盖度趋近于 0。
- 所有数字由 `run_b2_coverage.py` 复算（**v4.13 起该脚本产 `out_ext/tdc/b2_coverage.json` 可核对产物**，并已登记进 `tests/test_experiment_scripts.py` 的核心脚本表 + `CLAIMS_REGISTRY.yaml` 的 `b2_transporter_coverage` 条），数据源与脚本路径见 §1，可审计。
