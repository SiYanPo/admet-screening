# 截图工具收编 + PK/PD 扩展：逐项裁决与实测记录（v4.14–v4.20）

> **一句话结论**：截图里 14 个工具/网址中，**只有 5 个值得以"新证据"形式接入**
> （SwissADME、BioTransformer-HGUT、MicrobeTCM、GutBugDB、Cardiomimetic 类模型）；
> **2 个实测已死**（pkCSM），**4 个没有可验证入口**（HerbToxNet、KAN-PROSPECT、
> CardioSafe、Cardiosim-Tox）只能登记为 `paper_only`；**剩下的是"补端点"而不是"补源"**。
> 真正让本 skill 变强的是四类**结构性缺口**（§3），不是多加几个投票源。

---

## 1. 判断标准：为什么"加更多预测工具"几乎不会提升这个 skill

本 skill 自己的三条实测结论决定了这件事（都在 `references/BLACKLIST_CLOSEOUT.md` /
`TAIL_RISK_THESIS.md` 里有产物）：

| 已有实测结论 | 对"新增工具"的直接含义 |
|---|---|
| **A1**：方法同源的两源，α=0 时误差相关仍有 **0.655**，两源均值增益 **≤0** | 新源只有在**不同方法族**时才算"多一票"；同族只是伪共识 |
| **S4**：完整准入层 vs 未校准置信度，hERG **−0.133** / DILI **−0.115** / BBB **−0.219** | 多源并不会自动变准；组合层已有代价 |
| **铁律 2**：不知道源能不能信，就不要投票 | 新源必须先过注册门（Clopper-Pearson CI 上界 ≤5%），而不是先投票 |
| **v4.0 定位（R31/B7）**：本工作是**方法学贡献**，不是工具箱 | 功能数量本身不是贡献；写进 SKILL 的功能必须能改变**决策质量** |

所以本轮的验收问题不是"多了几个工具"，而是：
**它能不能补上一个让现有结论必然失真的结构性缺口？**

---

## 2. 逐项裁决（14 项，全部 2026-11-04 实测）

| # | 工具 | 现状 | 裁决 | 落地形式 | 独立性组 | 证据 |
|---|---|---|---|---|---|---|
| 1 | **SwissADME** | 已登记 ok，`adapter: null` | ✅ **接入（回填）** | `adt/readback.py` + schema | `descriptor_rules`（**跨族**） | GET 200 / POST `index.php` **403**（不可爬） |
| 2 | **pkCSM** | 已登记 `dead`（旧证据：5 次 500） | ❌ **维持 dead，证据升级** | 无（`verified_20261104` 落 8 条复现证据） | — | 域名迁移到 UQ 后前端全活；`POST /pkcsm/admet_prediction` **8/8 → 500**；单列头文件也 500（崩在预测引擎），双列头 → "invalid SMILES file" |
| 3 | **ProTox 3.0** | 已有适配器 | ⚪ 不动 | — | `neighbor_qsar` | 已有（18 端点，实测可用） |
| 4 | **ADMETlab 3.0** | 已有适配器 | ⚪ 不动 | — | `descriptor_ml` | 已有（122 列，含限流退避） |
| 5 | **BioTransformer 3.0** | 已有适配器 + REST | ✅ **补菌群子模块** | `adt/gut_microbiome.py` | `rule_engine` | `HGUT` 选项实测可用：APAP→3、quercetin→7 |
| 6 | **MicrobeTCM** | 未登记 | ✅ **登记为 database（不投票）** | `readback --source microbetcm` | `database` | GET **200** |
| 7 | **GutBugDB** | 未登记 | ✅ 同上 | `readback --source gutbugdb` | `database` | GET **200** |
| 8 | **MASI** | 未登记 | ⚠️ **登记为 needs_probe** | `readback --source masi`（待可达） | `database` | **DNS 解析失败**（`web.idrblab.cn` getaddrinfo failed） |
| 9 | **HerbToxNet** | 未登记 | ⚠️ **paper_only**（不假装接入） | registry + readback schema 骨架 | `tcm_specific` | **未找到公开推理端点** |
| 10 | **KAN-PROSPECT** | 未登记 | ⚠️ **paper_only** | 同上 | `tcm_specific` | 同上 |
| 11 | **CardioSafe** | 未登记 | ⚠️ **paper_only** | 同上 | `herg_specialist` | 同上（价值在原子级归因） |
| 12 | **Cardiosim-Tox** | 未登记 | ⚠️ paper_only + **端点已建** | `cardiac_*` 端点 + `adt/cardiac_panel.py` | `herg_specialist` | 同上 |
| 13 | **hERG/Cav1.2/Nav1.5 通道** | 只有 hERG 概率 | ✅✅ **建能力（最高价值）** | `adt/cardiac_panel.py` + 6 个新端点 | 不投票（reference） | 已有 `pbpk` 输出的升级路径原文即写"要升级需要 Na_v1.5/Ca_v1.2 抑制率" |
| 14 | **AOMP / Graph-pKa** | 未登记 | ✅ **建回填通道 + pKa 自建层** | `adt/ionization.py`、`readback --source aoamp/graphpka` | `dl_atomwise` / 独立 | 列名未实测 → 必须 `--map` |

**图例**：✅ = 已落地并有实跑；⚪ = 无变化；⚠️ = 只登记不宣称可用；❌ = 明确不加。

---

## 3. 真正值得加的四类理由（都是"结构性缺口"，不是"准确率"）

### 缺口 A：端点级覆盖空白 —— hERG 单通道无法下结论

**缺口事实（不是猜测，是 skill 自己写下的）**：
`adt/pbpk.py` 的 `herg_evidence_route()` 输出原文就是
> "要升级需要：hERG 膜片钳 IC50（含尾电流）、Na_v1.5 / Ca_v1.2 峰值电流抑制率"

而现有三个计算源**一个都不给** Cav1.2/Nav1.5 —— 这不是"不够准"，是**结构性无法判断**。
更关键的是 C85 已记录：糖苷不必然是阻断剂（人参皂苷 Rg3 是**激动剂**；
taxifolin 糖苷最大抑制 36.9% 即平台）；而 Cav1.2 阻断会**抵消** hERG 的 APD 延长。
**方向可以相反**，单通道连"方向"都给不出。

→ 落地：`adt/cardiac_panel.py`。它**不预测净效应**（没 ORd 就不假装有），只做两件
可以严格做到的事：① 通道覆盖率闸门（只有 hERG → `herg_only_*`，措辞里硬禁"清除"）；
② 通道级裕度分档（`Cmax,u/IC50` 或 `%抑制@Cmax`）。实测：Terfenadine 判 `panel_high`
（hERG margin 0.62），Quercetin/Digoxin 判 `herg_only_low` 且 allowed_statement
明确写"**不能**据此排除多通道风险"。

### 缺口 B：P-gp **底物**（不是抑制剂）——三个源全缺

注册表原文：ADMET-AI 只有 Pgp 抑制剂；ADMETlab 本类 14/14 恒为 N；vNN 全 NoPrediction。
这是**没有量**，不是"量不准"。SwissADME 的 `Pgp substrate` 列是目前唯一可批量取的
第二个来源（回填），实测 Terfenadine → `Yes`（与已知药理一致，可作为 sanity check）。

→ 落地：`pgp_substrate` 端点（`role: reference`，**单源不得下判决**）+ readback schema。

### 缺口 C：中药口服后的"第二套代谢系统"——且现有实现有实测缺陷

菌群代谢对中药（糖苷、多酚）本来就是主通路，但此前只有 `bt --option`，没有：
① **biosystem 过滤**；② **标注可信度检查**；③ **0 产物的判定规则**。

实测（原始 JSON 已落盘，`--dump-raw`）：
- `HGUT` 对 APAP → 3 个代谢物（阳性对照），对 quercetin → 7 个；
- **同一次 HGUT 查询里混进了一条 `biosystem="Human"`**（儿茶酚 O-甲基化）
  → 不过滤就会把**人体代谢算成菌群代谢**；
- **7/7 条 `reaction_type` 与质量差矛盾**：4 个葡糖醛酸苷（Δm=+176.03）被标成
  "Decarboxylation of aromatic L-amino acid"；2 条被标 "Hydroxylation" 而产物
  **少一个 O**（Δm=−15.99，方向相反）。
  结论：`reaction_type/enzymes` 是**规则名**，会串到别的底物类上 ——
  **只可引用 smiles/inchikey**。这条不是"推测"，是可复现的。

→ 落地：`adt/gut_microbiome.py`（`gut-micro`），含阳性对照闸门 + `biosystem` 过滤
+ 质量差一致性 QC + `out_of_domain` 规则。

### 缺口 D：暴露侧只有"峰值"，没有"时间" —— Margin 是最弱的一环

`pbpk.margin_table` 的 `Margin = IC50/Cmax` 有三个结构性缺陷：
① 只用峰值；② 没有 `fT>IC50`；③ 没有效应室滞后。
这是**方法论问题**，不是数据问题 —— 换更多预测源完全修不了。

→ 落地：`adt/pd_link.py`（Hill / 效应室 / `fT>EC50` / 最小 TMDD）
+ `adt/pbpk_qualify.py`（AFE/AAFE/2 倍内，把"会算"升级为"能用"）
+ `adt/interop.py`（PK-Sim 参数表 / NONMEM-nlmixr2 数据集，把参数交给真正的建模软件）。

---

## 4. 明确"不加"的清单与理由（写下来比加更重要的部分）

| 不加的东西 | 理由 |
|---|---|
| **pkCSM 适配器** | 前端全活、后端 500（8/8）。写了适配器就是**给用户一个必然失败的入口**。已把 8 条复现证据写进 registry，防下一个人再"基于首页 200"重新采纳 |
| **SwissADME 爬虫** | `index.php` POST 实测 **403**；且站点无 API、无批量。爬 = 违反 ToS + 脆弱。只做回填 |
| **HerbToxNet / KAN-PROSPECT 适配器** | 找不到公开推理端点。写适配器只能靠**猜接口**——`admetasar3` 的教训（猜 access_key 发放路径猜了两轮没成） |
| **CardioSafe / Cardiosim-Tox 的"三通道概率"** | 即使拿到入口，同一模型的三通道也**不是三个独立源**；且概率化会掩盖"没做 ORd"这一事实 |
| **自建 ORd / AP 仿真** | 需 7 通道完整 + 离子流模型 + 心肌细胞电生理参数，本机不具备；半吊子实现会比"不实现"更有害（会被当成净效应预测） |
| **把 MicrobeTCM 结果计票** | 数据库注解 = 文献级证据，不是预测。计票会制造"菌群代谢有 2 票支持"的假象 |
| **重写 PK-Sim / nlmixr2** | 那是另一个软件的职责；本 skill 的职责是把参数与数据**无损**交出去 |

---

## 5. PK/PD 与 PBPK 的定位（为什么是 qualification 而不是更复杂的模型）

用户要求"引入 PBPK 建模"。本 skill **已经有** 12 状态灌注限制 PBPK（v2.4.0），
带三项自校验（质量守恒 / 场景稳健性 / MC 收敛）+ IVIVE 假设 + EHR 边界扫描。
**缺的不是模型，是"模型能不能用"这一步。** 所以本轮加的是：

1. **资格认定**（`pbpk-qualify`）：AFE / AAFE / 2 倍内比例 + 三条拒绝条件
   （n<5、每化合物 <2 时点、观测与预测单位不一致）。实测两条路径：
   `insufficient_timepoints`（5 化合物 × 1 时点）与 `qualified_conventional`
   （5 × 8 = 40 配对，AAFE 1.20，2 倍内 98%）。
   **阈值明标 `convention`**：EMA 2018 要求报 fold error 但**未规定通过线**，
   2 倍/80% 是工业界工作点，不能写成"符合法规"。
2. **PK/PD 连接**（`pd`）：`fT>EC50`、`fT>EC90`、效应 AUC、峰效应、达峰时间、
   效应室（ke0）、最小 TMDD。实测：5 分子 × 12 h 间隔 → 2/5 在间隔内 ≥50% 时间高于 EC50。
   **TMDD 缺参数直接报错**（不用默认值凑）。
3. **互操作桥**（`interop`）：PK-Sim 化合物参数表（含 `unmapped` 显式列表）、
   NONMEM/nlmixr2 数据集（含契约校验）、nlmixr2 R 骨架（`nlmixr2_fit_passed`）。

**为什么不做 regulator-grade PBPK**：SKILL.md 的定位没变 ——
"需要 regulator-grade PBPK 要用 Simcyp/GastroPlus，本 skill 只给量级估算"。
把自建模型包装成"PBPK 平台"是**过度声称**，会破坏整个 skill 的可信度。

---

## 6. 新增能力清单（v4.14–v4.20）

| 版本 | 模块 | CLI | 产物 | 实跑证据 |
|---|---|---|---|---|
| v4.14 | `adt/ionization.py` | `pka` | `ionization.csv` | 14 分子：3 个显著电离、2 个两性离子判定正确（甘氨酸/阿莫西林）；咖啡因/葡萄糖正确判中性 |
| v4.15 | `adt/cardiac_panel.py` | `cardiac` | `cardiac_panel.csv` | Terfenadine `panel_high`（margin 0.62）；Quercetin/Digoxin `herg_only_low` 且禁"清除"表述 |
| v4.16 | `adt/pd_link.py` | `pd` | `pd_metrics.csv` / `pd_tmdd.csv` | 5 分子 × 12 h：fT>EC50 0–105 h，2/5 覆盖 ≥50% |
| v4.17 | `adt/pbpk_qualify.py` | `pbpk-qualify` | `pbpk_qualification.csv/.json` | 两路径：`insufficient_timepoints` / `qualified_conventional`（AAFE 1.20） |
| v4.18 | `adt/interop.py` | `interop` | `pk_sim_compounds.csv` / `nonmem_dataset.csv` / `nlmixr2_skeleton.R` | 6 化合物参数表（Diclofenac 判 ampholyte）；2005 行数据集契约校验通过 |
| v4.19 | `adt/gut_microbiome.py` | `gut-micro` | `metabolites_gut.csv` / `bt_raw_*.json` | 阳性对照 PASS（APAP→3）；quercetin→7；**7/7 标注矛盾被抓出** |
| v4.20 | `adt/readback.py` + schema | `readback` | `measurements_readback_<src>.csv` | SwissADME 假数据：3 行→12 长表行/2 分子；1 行结构不符被丢弃并报出；未映射列被报出 |
| — | `pbpk --dump-curves` | — | `pbpk_curves.csv` | 2001 行 C(t)，直接喂 `pd` |

**测试**：`tests/test_extension_v414.py`（44 例，全通过），含成对断言
（TMDD 缺参必抛、单位不一致必抛、measured 无引文必降级、结构不符必进 unmatched 报表、
回填通道禁写 out_of_domain/saturated/error）。

---

## 7. 未验证清单（必须随材料一起给出）

0. **两个 PBPK/PopPK 候选未核实**：用户提到的 `DallphinAtoM`（原文如此）与
   `OpenDose-PopPK` **未找到可验证的官方仓库/文档**，因此**未登记、未接入**。
   已核实并登记的是：PK-Sim / MoBi（open-systems-pharmacology.org，200）、
   nlmixr2（nlmixr2.org，200）、Pharmpy（pharmpy.github.io，200）。
   需要这两个的话请给仓库链接，我按 `paper_only` / `ok` 的同一套证据标准再登记。
1. **外部工具已装齐，但闭环程度不同（v4.21 更新，原"均未安装"已不成立）**。
   四个工具全部走**官方来源**安装并实测可运行：
   PK-Sim 12.3.173 + MoBi 12.3.136（OSP 官方 GitHub Releases，portable ZIP）、
   Pharmpy 2.3.0（官方 PyPI）、R 4.5.3 + nlmixr2 5.0.0 + rxode2 5.0.2（conda-forge）。
   因此 `validated_against_tool` 从布尔值改为**三级**：
   - `pk_sim_cli_snap_passed`：`--snapshot` → `pk_sim_snapshot.pksim5` → `snap -p` 往返，
     **32/32 化合物逐位一致**（logP/pKa/MW 全部保真）。**仅化合物层**。
   - `pharmpy_dataset_ok`：`create_datainfo` + `read_dataset_from_datainfo` 真读
     11228 行 / 12 列 / 28 受试者 / 28 次给药（EVID、MDV 计数自洽）。
   - `nlmixr2_fit_passed`：**COMPILE_OK + FOCEI 收敛**（"Normal exit from bobyqa"）。
     卡点不在编译器：是 conda 的 `r-qs2 0.2.1` 与 RcppParallel 自带 `tbb.dll` 死锁，
     换成官方 CRAN 的 `qs2_0.3.1` Windows 二进制后一次通过（**不需要 Rtools**）。
     但只有 V 可辨识（1433 L / RSE 3.8%），CL/ka/F 的 CI 跨四个数量级。
   **仿真层未闭环**：PK-Sim `snap -p` 退出码 0、日志写 "Project saved" 但 `Simulations` 恒为 0
   （官方 Midazolam 快照 37 条仿真裁到 1 条仍丢；已排除 `ParameterIdentifications` /
   `ObservedData` 两个诱因）。→ **验收看产物计数，不看退出码**；仿真层往返不得写入材料。
   `pk_sim_compounds.csv` 的列名与单位仍建议在 PK-Sim 导入窗口人工核对一次。
2. **AOMP / Graph-pKa / CardioSafe / Cardiosim-Tox / HerbToxNet / KAN-PROSPECT 的列名未实测**
   → schema 里 `endpoints: {}`，必须用 `--map` 显式映射；否则直接报错，不做列名模糊匹配。
3. **MASI 不可达**（DNS 失败），网址照留。
4. **pKa 是类别级文献区间**（±1 log），不是本分子实测；嘌呤/黄嘌呤环 N 高估碱性约 5 log
   （但 pH 7.4 下结论仍为"中性"）。
5. **cardiac_panel 未做 ORd 净效应**；"三通道全 LOW" ≠ 安全。
6. **gut-micro 的反应标注 QC 是必要条件**：质量差对得上不代表反应对，只代表"不是错的"。
7. **`fT>EC50` 依赖 EC50 假设**；Hill 系数固定时 `fT>EC90` 是反算值，不是独立信息。
